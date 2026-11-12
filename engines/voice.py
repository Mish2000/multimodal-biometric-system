"""The voice engine (H54): SpeechBrain's ECAPA-TDNN describes a voice, with PyTorch for the CPU in the voice
environment.

The model's five files come from Hugging Face at a pinned commit, each pinned by SHA-256; the engine refuses
other files and never uses the network. A recording is read from memory by its content with libsndfile,
never by a name or a stated type, and no file is written. The engine keeps nothing between requests (H13).

    python -I voice.py MODELS_DIR        the folder with the model's five files (local/models/voice)

Operations (protocol.py):
  extract  data: a WAV recording of 16 kHz, one channel, 16-bit PCM, as the page records it -> its duration,
           the seconds of speech, the levels of the speech and of the room's noise, and the share of clipped
           samples (`measure`); for a recording of at least a second, two parts: the recording again as a WAV
           made from its samples alone, and ECAPA's embedding as float32 values, little-endian
  extract with `"file": true` (H57)
           data: a recording file -> `file`, what libsndfile reads from its header before anything is decoded (its
           format and encoding, sample rate, channels and seconds), and `decoded`; only a file within FILE_FORMATS,
           FILE_RATES, FILE_CHANNELS and FILE_SECONDS is decoded, converted to 16 kHz, one channel and 16-bit PCM
           as SpeechBrain's own load_audio converts a file, and then answered as above, its WAV being the converted
           recording
Data that is not such a recording is answered with `invalid` and its reason, so the server can tell a refused
recording from a failed engine. The measurements need numpy alone, so the engine tests can run them in any
environment; PyTorch and SpeechBrain load only when the engine starts.
"""

from __future__ import annotations

import hashlib
import io
import os
import sys
import wave
from pathlib import Path

import numpy as np

SYSTEM_ROOT = Path(__file__).resolve().parents[1]
if str(SYSTEM_ROOT / "engines") not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT / "engines"))

import protocol  # noqa: E402

# speechbrain/spkrec-ecapa-voxceleb at Hugging Face commit 0f99f2d0ebe89ac095bcc5903c4dd8f72b367286 (Apache
# 2.0). SpeechBrain's Pretrainer loads all five files; the embedding model's SHA-256 is the algorithm's version.
MODEL_FILES = {
    "hyperparams.yaml": "6f78854fa04ba59e761437b76a2575d3aba5e5016de3e9b69f0c9a5077fb1a41",
    "embedding_model.ckpt": "0575cb64845e6b9a10db9bcb74d5ac32b326b8dc90352671d345e2ee3d0126a2",
    "mean_var_norm_emb.ckpt": "cd70225b05b37be64fc5a95e24395d804231d43f74b2e1e5a513db7b69b34c33",
    "classifier.ckpt": "fd9e3634fe68bd0a427c95e354c0c677374f62b3f434e45b78599950d860d535",
    "label_encoder.txt": "e13c3a167bb4112685670ee896d20e2b565af16b3a4ceeaa8689fa4d22adb8b9",
}
ECAPA_SHA256 = MODEL_FILES["embedding_model.ckpt"]
SAMPLE_RATE = 16000  # the rate the model was trained at (its model card)
# PyTorch splits ECAPA's sums by its number of threads, so the 192 values are exactly the same in every run and
# every process only with the same number (measured on 2026-11-11: 2, 4, 6, 16 and 24 threads gave one result,
# 1, 8 and 12 others). The engine therefore always uses this many.
THREADS = 8
EMBED_MINIMUM = SAMPLE_RATE  # ECAPA's convolutions need more than a fraction of a second; one second is asked
FRAME, HOP = 400, 160  # windows of 25 ms every 10 ms
FLOOR_PERCENTILE = 10  # the room's noise: the level of the recording's quietest tenth
SPEECH_MARGIN = 15.0  # speech stands this many dB above the room's noise
PAUSE_FRAMES = 20  # a pause of up to 0.2 s inside speech counts as speech
SILENCE = -100.0  # the level, in dB of full scale, given to digital silence
# H27, H57: the recording files read, as libsndfile names their formats and encodings (None: any encoding it reads;
# WAVEX is the extended WAV that many recorders write). Below 16 kHz a file lacks part of the model's band, which
# resampling cannot add (SpeechBrain's own note); the upper rate and the two channels keep a file's header from
# asking for an unbounded read. ECAPA-TDNN describes a recording whole, and its memory grows with the length
# (measured on 2026-11-12: about 0.9 GB at 30 s, 2.3 GB at two minutes, 9.9 GB at ten), so a file is compared
# whole up to two minutes. The server decides with the same limits (server/mbs/voice.py).
FILE_FORMATS = {"WAV": None, "WAVEX": None, "OGG": {"VORBIS", "OPUS"}, "MP3": {"MPEG_LAYER_III"}}
FILE_RATES = (16000, 192000)
FILE_CHANNELS = (1, 2)
FILE_SECONDS = (3.0, 120.0)
FILE_BLOCK = 65536  # frames read at a time


def check_models(folder: Path) -> None:
    """The model's files must be the pinned ones."""
    for name, expected in MODEL_FILES.items():
        path = folder / name
        if not path.is_file():
            raise RuntimeError(f"{name} is missing from {folder}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected:
            raise RuntimeError(f"{name} has SHA-256 {digest}, {expected} expected")


def levels(samples: np.ndarray) -> np.ndarray:
    """The level of each 25 ms window, every 10 ms, in dB of full scale."""
    x = samples.astype(np.float64) / 32768.0
    if len(x) < FRAME:
        return np.zeros(0)
    count = 1 + (len(x) - FRAME) // HOP
    windows = np.lib.stride_tricks.sliding_window_view(x, FRAME)[::HOP][:count]
    power = np.mean(windows * windows, axis=1)
    return np.maximum(10 * np.log10(np.maximum(power, 1e-30)), SILENCE)


def speech_windows(window_levels: np.ndarray) -> tuple[np.ndarray, float]:
    """The windows that count as speech, and the room's noise level: a window is speech when it stands
    SPEECH_MARGIN dB above the recording's quietest tenth, and so is a pause of up to PAUSE_FRAMES between two."""
    floor = float(np.percentile(window_levels, FLOOR_PERCENTILE))
    loud = window_levels >= floor + SPEECH_MARGIN
    speech = loud.copy()
    where = np.flatnonzero(loud)
    for start, end in zip(where[:-1], where[1:]):
        if end - start - 1 <= PAUSE_FRAMES:
            speech[start:end] = True
    return speech, floor


def measure(samples: np.ndarray) -> dict:
    """What the checks of a recording need (H54): its length, the seconds of speech that stand out of the room's
    noise, the level of that speech and of the noise, and the share of samples at the 16-bit limits."""
    duration = len(samples) / SAMPLE_RATE
    clipped = float(np.mean((samples >= 32767) | (samples <= -32768))) if len(samples) else 0.0
    window_levels = levels(samples)
    if not len(window_levels):
        return {"duration": round(duration, 3), "speech": 0.0, "speech_level": SILENCE, "noise_level": SILENCE,
                "clipped": round(clipped, 6)}
    speech, floor = speech_windows(window_levels)
    level = float(10 * np.log10(np.mean(10 ** (window_levels[speech] / 10)))) if speech.any() else SILENCE
    return {"duration": round(duration, 3), "speech": round(float(speech.sum()) * HOP / SAMPLE_RATE, 2),
            "speech_level": round(level, 1), "noise_level": round(floor, 1), "clipped": round(clipped, 6)}


def decode(data: bytes) -> np.ndarray:
    """The samples of a WAV of 16 kHz, one channel and 16-bit PCM, read by libsndfile from memory."""
    import soundfile
    try:
        info = soundfile.info(io.BytesIO(data))
        if info.format != "WAV" or info.subtype != "PCM_16":
            raise ValueError("a WAV of 16-bit PCM is needed")
        if info.samplerate != SAMPLE_RATE or info.channels != 1:
            raise ValueError(f"a recording of {SAMPLE_RATE} Hz and one channel is needed")
        samples, _ = soundfile.read(io.BytesIO(data), dtype="int16", always_2d=False)
    except (RuntimeError, TypeError):  # libsndfile cannot read it
        raise ValueError("the data is not a recording") from None
    return np.asarray(samples, dtype=np.int16).reshape(-1)


def file_facts(data: bytes) -> dict:
    """H57: what libsndfile reads from a recording file's header, from memory, before anything is decoded."""
    import soundfile
    try:
        info = soundfile.info(io.BytesIO(data))
    except (RuntimeError, TypeError):  # libsndfile cannot read it
        raise ValueError("the data is not a recording") from None
    seconds = info.frames / info.samplerate if info.samplerate > 0 else 0.0
    return {"format": info.format, "subtype": info.subtype, "sample_rate": info.samplerate,
            "channels": info.channels, "seconds": round(seconds, 3)}


def readable(facts: dict) -> bool:
    """Whether a file is decoded: its format and encoding, rate, channels and length within the limits."""
    encodings = FILE_FORMATS.get(facts["format"], set())
    return ((facts["format"] in FILE_FORMATS and (encodings is None or facts["subtype"] in encodings))
            and FILE_RATES[0] <= facts["sample_rate"] <= FILE_RATES[1]
            and FILE_CHANNELS[0] <= facts["channels"] <= FILE_CHANNELS[1]
            and FILE_SECONDS[0] <= facts["seconds"] <= FILE_SECONDS[1])


def wav(samples: np.ndarray) -> bytes:
    """A WAV of the samples alone: 16 kHz, one channel, 16-bit PCM, no other chunk."""
    out = io.BytesIO()
    with wave.open(out, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(SAMPLE_RATE)
        writer.writeframes(samples.astype("<i2").tobytes())
    return out.getvalue()


class Voices:
    def __init__(self, folder: Path):
        check_models(folder)
        os.environ["HF_HUB_OFFLINE"] = "1"  # before huggingface_hub loads: the model comes from the folder only
        import torch
        from speechbrain.dataio.preprocess import AudioNormalizer
        from speechbrain.inference.speaker import SpeakerRecognition
        from speechbrain.utils.fetching import LocalStrategy
        torch.set_num_threads(THREADS)
        self.torch = torch
        # H57: what SpeechBrain's load_audio applies to a file: every channel resampled to the model's rate by
        # torchaudio's sinc resampler, then the channels averaged.
        self.normalizer = AudioNormalizer(sample_rate=SAMPLE_RATE, mix="avg-to-mono")
        source = str(folder)
        # SpeechBrain's own interface for this model (its model card), loading the files where they are: with
        # NO_LINK it neither copies nor links them, so the folder stays as downloaded.
        self.model = SpeakerRecognition.from_hparams(
            source=source, savedir=source, overrides={"pretrained_path": source}, run_opts={"device": "cpu"},
            local_strategy=LocalStrategy.NO_LINK)
        self.model.eval()
        # ECAPA's embedding length, read from the model rather than assumed (specification 5.3).
        self.length = int(self.embed(np.zeros(EMBED_MINIMUM, np.int16)).size)

    def embed(self, samples: np.ndarray) -> np.ndarray:
        """ECAPA's embedding of the whole recording, as SpeechBrain's verify_batch computes it (normalize=False)."""
        signal = self.torch.from_numpy(samples.astype(np.float32) / 32768.0).unsqueeze(0)
        with self.torch.inference_mode():
            values = self.model.encode_batch(signal, normalize=False)
        return values.reshape(-1).numpy().astype("<f4")

    def convert(self, data: bytes) -> np.ndarray:
        """H57: a recording file as SpeechBrain's load_audio converts it (libsndfile's float samples, read in blocks,
        then the normalizer), then 16-bit PCM, as the page records; the checks and ECAPA then use these samples."""
        import soundfile
        with soundfile.SoundFile(io.BytesIO(data)) as file:
            blocks = list(file.blocks(blocksize=FILE_BLOCK, dtype="float32", always_2d=True))
            rate = file.samplerate
        signal = np.concatenate(blocks) if blocks else np.zeros((0, 1), np.float32)
        with self.torch.inference_mode():
            mono = self.normalizer(self.torch.from_numpy(signal), rate).numpy()
        return np.clip(np.round(mono.astype(np.float64) * 32768), -32768, 32767).astype(np.int16)

    def extract(self, header: dict, parts: list[bytes]):
        facts = None
        try:
            if header.get("file"):
                facts = file_facts(parts[0])
                if not readable(facts):
                    return {"file": facts, "decoded": False}, b""
                samples = self.convert(parts[0])
            else:
                samples = decode(parts[0])
        except ValueError as error:
            return {"invalid": str(error)}, b""
        except (RuntimeError, TypeError):  # a file whose header reads but whose data does not
            return {"invalid": "the data is not a recording"}, b""
        reply = {**({"file": facts, "decoded": True} if facts is not None else {}), "sample_rate": SAMPLE_RATE,
                 **measure(samples), "embedding_length": self.length}
        if len(samples) < EMBED_MINIMUM:
            return reply, b""
        embedding = self.embed(samples)
        if embedding.size != self.length or not np.all(np.isfinite(embedding)):
            raise ValueError("ECAPA returned an invalid embedding")
        return reply, [wav(samples), embedding.tobytes()]


def main() -> None:
    # Nothing but the protocol may reach standard output, also while the libraries load.
    stdout, sys.stdout = sys.stdout, sys.stderr
    try:
        voices = Voices(Path(sys.argv[1]).resolve())
        import speechbrain
    finally:
        sys.stdout = stdout
    protocol.serve({"engine": "voice", "speechbrain": speechbrain.__version__, "torch": voices.torch.__version__,
                    "ecapa_sha256": ECAPA_SHA256, "embedding_length": voices.length, "sample_rate": SAMPLE_RATE,
                    "threads": voices.torch.get_num_threads()},
                   {"extract": voices.extract})


if __name__ == "__main__":
    main()
