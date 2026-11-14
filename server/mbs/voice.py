"""Voice enrolment (H17, H25, H54), verification (H55) and identification (H56), both also from recording files (H57).

The microphone belongs to the client: the page records a sentence of about four seconds as a WAV of 16 kHz, one
channel and 16-bit PCM, shows its own level meter and timer, and sends each recording. Every recording passes
the same checks here: three to thirty seconds long, at least two seconds of speech that stands out of the room's
noise, and hardly any clipped samples (no standard voice quality score is used). Of the recordings that pass, the
enrolment keeps three whose three pairs are all above SpeechBrain's threshold, as H15 does for fingerprints and
H48 for the face; when no three do, the client records another, up to six that pass. The recordings are sealed
like every finding, each bound to its row and its subject (H25); the embeddings are pgvector values (H14), and
every voice score is pgvector's cosine similarity, as every face score is.

The server keeps nothing between requests: the enrolment request carries the recordings again, and every check
is made anew on them. Enrolment, verification, identification and deletion are the flows the voice shares with
the face (mbs/embeddings.py); this module holds the voice's own steps: the engine's measurements and their checks,
the checks of a recording file, and what of a recording is sealed and shown.
"""

from __future__ import annotations

import logging
import math
import struct
import uuid
from dataclasses import dataclass
from datetime import datetime

from . import embeddings
from .config import REPOSITORY, Config
from .db import Databases
from .embeddings import EngineService, Modality, ModalityError, base64_text, card, decode
from .embeddings import check as _check
from .engines import Engine, EngineError, conda_environment
from .keys import Keys
from .models import Enrolment, Sample

logger = logging.getLogger("mbs.voice")

VOICE = "voice"
ECAPA = "ecapa-voxceleb"
MODEL_FILES = ("hyperparams.yaml", "embedding_model.ckpt", "mean_var_norm_emb.ckpt", "classifier.ckpt",
               "label_encoder.txt")  # speechbrain/spkrec-ecapa-voxceleb, pinned by the engine (engines/README.md)
RECORDINGS = 3  # H17
MOST_KEPT = 6  # recordings that pass the checks, while looking for three that match each other (as H48)
EMBEDDING_LENGTH = 192  # read from the model by the engine (specification 5.3)
SAMPLE_RATE = 16000  # the model's rate; the page records at it
RECORDING_SECONDS = 5  # how long the page records: a sentence of about four seconds (H17) and some margin
RECORDING_BYTES = 1 << 20  # a recording of the page: 16-bit samples of one channel, at most about 32 seconds
DURATION_MINIMUM, DURATION_MAXIMUM = 3.0, 30.0  # seconds, the limits H27 sets for recordings
SPEECH_MINIMUM = 2.0  # seconds of speech that stand out of the room's noise (H54)
CLIPPED_MAXIMUM = 0.001  # the share of samples at the 16-bit limits (H54)
# H27, H57: a recording file, for 1:1 and 1:N only. Its kind comes from its first bytes; then the engine reads its
# header with libsndfile, and only a file within these limits is decoded (the engine keeps the same limits).
FILE_BYTES = 10 << 20
SOURCES = ("device", "file")
FILE_FORMATS = {"WAV": None, "WAVEX": None, "OGG": {"VORBIS", "OPUS"}, "MP3": {"MPEG_LAYER_III"}}  # None: any encoding
KINDS = {"WAV": {"WAV", "WAVEX"}, "OGG": {"OGG"}, "MP3": {"MP3"}}  # the formats each kind of first bytes may hold
FILE_RATES = (16000, 192000)  # at least the model's rate: resampling cannot add a band a file lacks
FILE_CHANNELS = (1, 2)
FILE_SECONDS_MAXIMUM = 120.0  # a file is compared whole up to two minutes; ECAPA's memory grows with the length


class VoiceError(ModalityError):
    """A refused voice request, answered as {"error": code, ...}."""


class VoiceService(EngineService):
    """The voice engine (H54), started in the background, so the first recording does not wait for PyTorch to load."""


def from_config(config: Config) -> tuple[VoiceService | None, str]:
    """The service with this machine's voice environment and model, or None and what is missing."""
    python, models = config.voice_python, config.voice_models
    missing = [name for name, ok in (
        ("voice_python (the multimodal-voice environment)", python and python.exists()),
        ("voice_models with the five files of the ECAPA-TDNN model",
         models and all((models / name).exists() for name in MODEL_FILES)),
    ) if not ok]
    if missing:
        return None, "missing: " + ", ".join(missing)
    command = [str(python), "-I", str(REPOSITORY / "engines" / "voice.py"), str(models)]
    return VoiceService(Engine(VOICE, command, conda_environment(python))), ""


def decode_recording(data: str, limit: int) -> bytes:
    """A recording sent in base64; whether it is one is decided by the engine from its content."""
    return decode(data, limit, VoiceError, "invalid_recording")


MEASUREMENTS = (("duration", 0.0, 3600.0), ("speech", 0.0, 3600.0), ("speech_level", -100.0, 0.5),
                ("noise_level", -100.0, 0.5), ("clipped", 0.0, 1.0))


def _measurements(reply: dict) -> dict[str, float]:
    """The engine's measurements, checked before anything uses them."""
    if "invalid" in reply:
        raise VoiceError("invalid_recording")  # not a WAV of 16 kHz, one channel and 16-bit PCM
    if reply.get("sample_rate") != SAMPLE_RATE:
        raise EngineError("invalid voice reply")
    values = {}
    for name, low, high in MEASUREMENTS:
        value = reply.get(name)
        if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
            raise EngineError("invalid voice reply")
        values[name] = float(value)
    if values["speech"] > values["duration"] + 0.05:
        raise EngineError("invalid voice reply")
    return values


def _length(duration: float, maximum: float = DURATION_MAXIMUM) -> dict:
    return _check("length", DURATION_MINIMUM <= duration <= maximum,
                  f"{duration:.1f} seconds long, {DURATION_MINIMUM:g} to {maximum:g} needed",
                  seconds=round(duration, 2), minimum=DURATION_MINIMUM, maximum=maximum)


def checks_for(found: dict[str, float], maximum: float = DURATION_MAXIMUM) -> list[dict]:
    """The checks of one recording (H54), each with its measured value; a file may last longer (H57)."""
    duration, speech, clipped = found["duration"], found["speech"], found["clipped"]
    above = {"above_noise": round(found["speech_level"] - found["noise_level"], 1)} if speech > 0 else {}
    return [
        _length(duration, maximum),
        _check("speech", speech >= SPEECH_MINIMUM,
               f"{speech:.1f} seconds of speech above the room's noise, at least {SPEECH_MINIMUM:g} needed",
               seconds=round(speech, 2), minimum=SPEECH_MINIMUM, **above),
        _check("clipping", clipped <= CLIPPED_MAXIMUM,
               f"{100 * clipped:.2f} % of the samples at the limits, at most {100 * CLIPPED_MAXIMUM:.1f} %",
               share=round(clipped, 6), maximum=CLIPPED_MAXIMUM),
    ]


@dataclass
class Extracted:
    measured: dict[str, float]
    checks: list[dict]
    wav: bytes | None = None  # the recording again, made by the engine from its samples alone
    embedding: list[float] | None = None
    file: dict | None = None  # H57: what the engine read from a file's header

    @property
    def passed(self) -> bool:
        return all(check["passed"] for check in self.checks)

    @property
    def duration_ms(self) -> int:
        return round(1000 * self.measured["duration"])


def file_kind(data: bytes) -> str | None:
    """H57: a file's kind from its first bytes alone, before the engine reads it: a WAV (RIFF and WAVE), an OGG
    (its page marker) or an MP3 (an ID3 tag, or an MPEG audio frame of Layer III); anything else is None."""
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "WAV"
    if data[:4] == b"OggS":
        return "OGG"
    if data[:3] == b"ID3" or (len(data) >= 2 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0 and (data[1] >> 1) & 3 == 1):
        return "MP3"
    return None


def _file_facts(reply: dict) -> dict:
    facts = reply.get("file")
    if not isinstance(facts, dict) or not all(isinstance(facts.get(key), str) for key in ("format", "subtype")) \
            or not all(type(facts.get(key)) is int and facts[key] >= 0 for key in ("sample_rate", "channels")) \
            or type(facts.get("seconds")) not in (int, float) or not math.isfinite(facts["seconds"]) \
            or facts["seconds"] < 0 or type(reply.get("decoded")) is not bool:
        raise EngineError("invalid voice reply")
    return {key: facts[key] for key in ("format", "subtype", "sample_rate", "channels", "seconds")}


def file_checks(kind: str, facts: dict) -> list[dict]:
    """H57: the checks of a file's header, as the engine read it: its kind and format, its rate and channels."""
    fmt, encoding, rate, channels = facts["format"], facts["subtype"], facts["sample_rate"], facts["channels"]
    encodings = FILE_FORMATS.get(fmt, set())
    known = fmt in KINDS[kind] and (encodings is None or encoding in encodings)
    return [
        _check("file_type", known, f"{fmt} ({encoding}): a WAV, an MP3 or an OGG of Vorbis or Opus is needed",
               format=fmt, encoding=encoding),
        _check("sample_rate", FILE_RATES[0] <= rate <= FILE_RATES[1],
               f"{rate} Hz, {FILE_RATES[0]} to {FILE_RATES[1]} needed", rate=rate, minimum=FILE_RATES[0],
               maximum=FILE_RATES[1]),
        _check("channels", FILE_CHANNELS[0] <= channels <= FILE_CHANNELS[1],
               f"{channels} channels, {FILE_CHANNELS[0]} or {FILE_CHANNELS[1]} needed", channels=channels,
               maximum=FILE_CHANNELS[1]),
    ]


def _extract(service: VoiceService, recording: bytes, kind: str | None = None) -> Extracted:
    """A recording's measurements, checks and embedding; with `kind`, a file (H57), whose header's checks come first:
    a file outside them is not decoded, and only its header's length joins its checks."""
    reply, parts = service.engine.request({"op": "extract", **({"file": True} if kind else {})}, [recording])
    facts, checks = None, []
    if kind is not None:
        if "invalid" in reply:
            raise VoiceError("invalid_recording")
        facts = _file_facts(reply)
        checks = file_checks(kind, facts)
        if not reply["decoded"]:
            checks.append(_length(facts["seconds"], FILE_SECONDS_MAXIMUM))
            if all(check["passed"] for check in checks):
                raise EngineError("invalid voice reply")  # the engine refused a file that these checks allow
            return Extracted({}, checks, file=facts)
    measured = _measurements(reply)
    found = Extracted(measured, checks + checks_for(measured, FILE_SECONDS_MAXIMUM if kind else DURATION_MAXIMUM),
                      file=facts)
    if not found.passed:
        return found
    if reply.get("embedding_length") != EMBEDDING_LENGTH or len(parts) != 2 or len(parts[1]) != 4 * EMBEDDING_LENGTH:
        raise EngineError("invalid voice embedding")
    embedding = list(struct.unpack(f"<{EMBEDDING_LENGTH}f", parts[1]))
    if not all(math.isfinite(v) for v in embedding) or not any(embedding) or not parts[0].startswith(b"RIFF"):
        raise EngineError("invalid voice embedding")
    found.wav, found.embedding = parts[0], embedding
    return found


def check(service: VoiceService, recording: bytes) -> dict:
    """One recording's checks, for the page to show at once; nothing is kept."""
    found = _extract(service, recording)
    return {"checks": found.checks, "passed": found.passed, "duration": found.measured["duration"],
            "speech": found.measured["speech"]}


def method(databases: Databases, service: VoiceService | None) -> dict:
    """ECAPA-TDNN's card and the rules of a voice enrolment."""
    return {**card(databases, ECAPA, service), "recordings": RECORDINGS, "most_kept": MOST_KEPT,
            "embedding_length": EMBEDDING_LENGTH, "sample_rate": SAMPLE_RATE, "recording_seconds": RECORDING_SECONDS,
            "duration_minimum": DURATION_MINIMUM, "duration_maximum": DURATION_MAXIMUM,
            "speech_minimum": SPEECH_MINIMUM, "clipped_maximum": CLIPPED_MAXIMUM}


def current_enrolment(databases: Databases, subject: uuid.UUID) -> Enrolment | None:
    return embeddings.current_enrolment(databases, subject, VOICE)


def enrol(service: VoiceService, databases: Databases, keys: Keys, subject: uuid.UUID,
          recordings: list[tuple[bytes, datetime]]) -> dict:
    """The recordings made so far, in the order they were made: saved when three of them match each other,
    otherwise the client is asked for another recording, until six have passed the checks."""
    return embeddings.enrol(VOICES, service, databases, keys, subject, recordings)


def _save(databases: Databases, keys: Keys, subject: uuid.UUID, chosen: list[tuple[int, Extracted, datetime]],
          version: str) -> tuple[Enrolment, bool, list[Sample], list]:
    return embeddings.save(VOICES, databases, keys, subject, chosen, version)


def delete_voice(databases: Databases, subject: uuid.UUID) -> bool:
    """As H34 for a finger and H48 for the face: the voice enrolment and those it replaced are erased with their
    sealed recordings and embeddings, and (H55) with their verification attempts, whose link cascades; the
    identification attempts they led stay, with the link emptied (H41, H56). False when the voice is not enrolled."""
    return embeddings.delete_enrolments(databases, subject, VOICE)


def _take(service: VoiceService, recording: bytes, source: str) -> Extracted:
    """The new recording of a verification or an identification: from the microphone, or from a file (H27, H57),
    whose kind from its first bytes comes first and keeps any other file from the engine."""
    if source not in SOURCES:
        raise VoiceError("invalid_request")
    if source == "device":
        return _extract(service, recording)
    kind = file_kind(recording)
    if kind is None:
        return Extracted({}, [_check("file_type", False, "a WAV, an MP3 or an OGG of Vorbis or Opus is needed")])
    return _extract(service, recording, kind)


def _rejected(probe: Extracted, source: str) -> dict:
    return {"status": "rejected", "source": source, "checks": probe.checks,
            **({"file": probe.file} if probe.file is not None else {})}


def _origin(probe: Extracted, source: str) -> dict:
    """The answer's source; for a file (H57), what was read from its header and the recording compared, the caller's
    own, so the page can show it."""
    if source != "file":
        return {"source": source}
    return {"source": source, "file": probe.file, "probe": base64_text(probe.wav)}


def _repeat_view(service: VoiceService, keys: Keys, databases: Databases, subject: uuid.UUID, sample_id: uuid.UUID,
                 stored: list[float]) -> bytes:
    """The caller's own winning recording, for the result screen (H55); the engine's fixed threads make its repeated
    embedding exact."""
    return embeddings.repeat_view(VOICES, service, keys, databases, subject, sample_id, stored)


def verify(service: VoiceService, databases: Databases, keys: Keys, subject: uuid.UUID, recording: bytes,
           source: str = "device") -> dict:
    """H55: one recording against the caller's current voice enrolment, as H49 does for the face."""
    return embeddings.verify(VOICES, service, databases, keys, subject, recording, source)


def identify(service: VoiceService, databases: Databases, keys: Keys, subject: uuid.UUID, recording: bytes,
             source: str = "device") -> dict:
    """H56: one recording against every current voice enrolment of the active user accounts, as H50 does for the
    face."""
    return embeddings.identify(VOICES, service, databases, keys, subject, recording, source)


def _sample_json(sample: Sample, found: Extracted) -> dict:
    return {"id": str(sample.id), "placement": sample.placement, "captured_at": sample.captured_at.isoformat(),
            "duration_ms": sample.duration_ms, "sealed_length": len(sample.data), "checks": sample.checks}


VOICES = Modality(
    name=VOICE, algorithm=ECAPA, version_key="ecapa_sha256", per_enrolment=RECORDINGS, most_kept=MOST_KEPT,
    embedding_length=EMBEDDING_LENGTH, noun="recording", refusal=VoiceError,
    extract=lambda service, recording: _extract(service, recording),
    take=lambda service, recording, source: _take(service, recording, source),
    rejected=lambda probe, source: _rejected(probe, source),
    sealed=lambda found: found.wav,
    sample_fields=lambda found: {"media_type": "audio/wav", "duration_ms": found.duration_ms, "checks": found.checks},
    sample_json=lambda sample, found: _sample_json(sample, found),
    shown=lambda recording, again: recording,
    origin=lambda probe, source: _origin(probe, source),
    view=lambda probe, reference: {"reference": base64_text(reference)},
    repeat_view=lambda *args: _repeat_view(*args),
)
