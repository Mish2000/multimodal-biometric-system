"""Voice enrolment (H17, H25, H54).

The microphone belongs to the client: the page records a sentence of about four seconds as a WAV of 16 kHz, one
channel and 16-bit PCM, shows its own level meter and timer, and sends each recording. Every recording passes
the same checks here: three to thirty seconds long, at least two seconds of speech that stands out of the room's
noise, and hardly any clipped samples (no standard voice quality score is used). Of the recordings that pass, the
enrolment keeps three whose three pairs are all above SpeechBrain's threshold, as H15 does for fingerprints and
H48 for the face; when no three do, the client records another, up to six that pass. The recordings are sealed
like every finding, each bound to its row and its subject (H25); the embeddings are pgvector values (H14), and
every voice score is pgvector's cosine similarity, as every face score is.

The server keeps nothing between requests: the enrolment request carries the recordings again, and every check
is made anew on them.
"""

from __future__ import annotations

import base64
import itertools
import logging
import math
import struct
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import CursorResult, delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from . import keys as keyring
from .config import REPOSITORY, Config
from .db import Databases
from .engines import Engine, EngineError, conda_environment
from .face import similarity
from .fingerprint import best_three
from .keys import Keys
from .models import Algorithm, Enrolment, Sample, Template

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
CAPTURE_AGE = timedelta(minutes=30)  # an enrolment's recordings were made in the last half hour
CLOCK_SKEW = timedelta(minutes=1)


class VoiceError(Exception):
    """A refused voice request, answered as {"error": code, ...}."""

    def __init__(self, code: str, status: int = 422, **extra):
        super().__init__(code)
        self.code, self.status, self.extra = code, status, extra


@dataclass
class VoiceService:
    engine: Engine

    def warm_up(self) -> None:
        """Start the engine in the background, so the first recording does not wait for PyTorch to load."""
        def start():
            try:
                self.engine.start()
            except EngineError:
                pass  # reported when a request needs it
        threading.Thread(target=start, daemon=True).start()

    def close(self) -> None:
        self.engine.close()


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


def _db(engine) -> DbSession:
    return DbSession(engine, expire_on_commit=False)


def decode_recording(data: str, limit: int) -> bytes:
    """A recording sent in base64; whether it is one is decided by the engine from its content."""
    try:
        recording = base64.b64decode(data, validate=True)
    except ValueError:
        raise VoiceError("invalid_recording") from None
    if not recording or len(recording) > limit:
        raise VoiceError("invalid_recording")
    return recording


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


def _check(name: str, passed: bool, detail: str, **extra) -> dict:
    return {"name": name, "passed": passed, "detail": detail, **extra}


def checks_for(found: dict[str, float]) -> list[dict]:
    """The checks of one recording (H54), each with its measured value."""
    duration, speech, clipped = found["duration"], found["speech"], found["clipped"]
    above = {"above_noise": round(found["speech_level"] - found["noise_level"], 1)} if speech > 0 else {}
    return [
        _check("length", DURATION_MINIMUM <= duration <= DURATION_MAXIMUM,
               f"{duration:.1f} seconds long, {DURATION_MINIMUM:g} to {DURATION_MAXIMUM:g} needed",
               seconds=round(duration, 2), minimum=DURATION_MINIMUM, maximum=DURATION_MAXIMUM),
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

    @property
    def passed(self) -> bool:
        return all(check["passed"] for check in self.checks)

    @property
    def duration_ms(self) -> int:
        return round(1000 * self.measured["duration"])


def _extract(service: VoiceService, recording: bytes) -> Extracted:
    reply, parts = service.engine.request({"op": "extract"}, [recording])
    measured = _measurements(reply)
    found = Extracted(measured, checks_for(measured))
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
    with _db(databases.biometric) as db:
        algorithm = db.get(Algorithm, ECAPA)
    return {"code": ECAPA, "threshold": algorithm.threshold, "threshold_provisional": algorithm.threshold_provisional,
            "threshold_origin": algorithm.threshold_origin, "available": service is not None,
            "recordings": RECORDINGS, "most_kept": MOST_KEPT, "embedding_length": EMBEDDING_LENGTH,
            "sample_rate": SAMPLE_RATE, "recording_seconds": RECORDING_SECONDS,
            "duration_minimum": DURATION_MINIMUM, "duration_maximum": DURATION_MAXIMUM,
            "speech_minimum": SPEECH_MINIMUM, "clipped_maximum": CLIPPED_MAXIMUM}


def current_enrolment(databases: Databases, subject: uuid.UUID) -> Enrolment | None:
    with _db(databases.biometric) as db:
        return db.scalar(select(Enrolment).where(Enrolment.subject_id == subject, Enrolment.modality == VOICE,
                                                 Enrolment.replaced_at.is_(None)))


def enrol(service: VoiceService, databases: Databases, keys: Keys, subject: uuid.UUID,
          recordings: list[tuple[bytes, datetime]]) -> dict:
    """The recordings made so far, in the order they were made: saved when three of them match each other,
    otherwise the client is asked for another recording, until six have passed the checks."""
    if not RECORDINGS <= len(recordings) <= MOST_KEPT:
        raise VoiceError("invalid_request")
    now = datetime.now(timezone.utc)
    times = [made for _, made in recordings]
    if any(made.tzinfo is None or not now - CAPTURE_AGE <= made <= now + CLOCK_SKEW for made in times) \
            or times != sorted(times):
        raise VoiceError("invalid_request")
    with _db(databases.biometric) as db:
        algorithm = db.get(Algorithm, ECAPA)
        version, threshold = algorithm.version, algorithm.threshold
    if service.engine.start().get("ecapa_sha256") != version:
        raise VoiceError("method_version_differs", 503)
    found = []
    for index, (recording, _) in enumerate(recordings):
        extracted = _extract(service, recording)
        if not extracted.passed:
            raise VoiceError("recording_rejected", index=index, checks=extracted.checks)
        found.append(extracted)
    scores: dict[tuple[int, int], float] = {}
    with _db(databases.biometric) as db:
        for a, b in itertools.combinations(range(len(found)), 2):
            scores[(a, b)] = similarity(db, found[b].embedding, found[a].embedding)
    pairs = [{"probe": b + 1, "reference": a + 1, "score": score, "accepted": score > threshold}
             for (a, b), score in scores.items()]
    trio = best_three(found, scores, threshold)
    if trio is None:
        status = "failed" if len(found) >= MOST_KEPT else "another"
        return {"status": status, **({"error": "recordings_do_not_match"} if status == "failed" else {}),
                "pairs": pairs, "threshold": threshold, "kept": len(found)}
    chosen = [(index + 1, found[index], times[index]) for index in trio]
    enrolment, replaced, samples, templates = _save(databases, keys, subject, chosen, version)
    return {
        "status": "saved",
        "enrolment": {"id": str(enrolment.id), "created_at": enrolment.created_at.isoformat(),
                      "replaced_previous": replaced},
        "samples": [{"id": str(sample.id), "placement": sample.placement, "captured_at": sample.captured_at.isoformat(),
                     "duration_ms": sample.duration_ms, "sealed_length": len(sample.data), "checks": sample.checks}
                    for sample in samples],
        "templates": [{"id": str(template.id), "sample_id": str(template.sample_id), "algorithm": ECAPA,
                       "version": version, "embedding_length": EMBEDDING_LENGTH} for template in templates],
        "pairs": [pair for pair in pairs if pair["reference"] - 1 in trio and pair["probe"] - 1 in trio],
        "threshold": threshold,
        "not_kept": [index + 1 for index in range(len(found)) if index not in trio],
    }


def _save(databases: Databases, keys: Keys, subject: uuid.UUID, chosen: list[tuple[int, Extracted, datetime]],
          version: str) -> tuple[Enrolment, bool, list[Sample], list[Template]]:
    now = datetime.now(timezone.utc)
    try:
        with _db(databases.biometric) as db, db.begin():
            result: CursorResult = db.execute(update(Enrolment).where(
                Enrolment.subject_id == subject, Enrolment.modality == VOICE, Enrolment.replaced_at.is_(None)
            ).values(replaced_at=now))
            enrolment = Enrolment(id=uuid.uuid4(), subject_id=subject, modality=VOICE, finger=None, created_at=now)
            db.add(enrolment)
            db.flush()
            samples, templates = [], []
            for placement, extracted, made in chosen:
                sample = Sample(id=uuid.uuid4(), enrolment_id=enrolment.id, placement=placement, captured_at=made,
                                media_type="audio/wav", duration_ms=extracted.duration_ms, checks=extracted.checks)
                sample.data = keyring.seal(keys, keyring.SAMPLE, sample.id.bytes + subject.bytes, extracted.wav)
                db.add(sample)
                db.flush()
                template = Template(id=uuid.uuid4(), sample_id=sample.id, algorithm=ECAPA, version=version,
                                    created_at=now, embedding=extracted.embedding)
                db.add(template)
                samples.append(sample)
                templates.append(template)
    except IntegrityError:
        raise VoiceError("enrolment_busy", 409) from None  # another voice enrolment of this person ended first
    return enrolment, result.rowcount > 0, samples, templates


def delete_voice(databases: Databases, subject: uuid.UUID) -> bool:
    """As H34 for a finger and H48 for the face: the voice enrolment and those it replaced are erased with their
    sealed recordings and embeddings; False when the voice is not enrolled."""
    with _db(databases.biometric) as db, db.begin():
        rows = db.execute(select(Enrolment.id, Enrolment.replaced_at).where(
            Enrolment.subject_id == subject, Enrolment.modality == VOICE
        ).order_by(Enrolment.id).with_for_update()).all()
        if not any(replaced_at is None for _, replaced_at in rows):
            return False
        enrolments = [enrolment_id for enrolment_id, _ in rows]
        samples = select(Sample.id).where(Sample.enrolment_id.in_(enrolments))
        db.execute(delete(Template).where(Template.sample_id.in_(samples)))
        db.execute(delete(Sample).where(Sample.enrolment_id.in_(enrolments)))
        db.execute(delete(Enrolment).where(Enrolment.id.in_(enrolments)))
    return True
