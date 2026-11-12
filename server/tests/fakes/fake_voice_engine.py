"""A stand-in for the voice engine in the tests (H54), speaking its real protocol (engines/protocol.py). A fake
recording is b"FAKEVOICE" followed by JSON: its measurements ("duration", "speech", "speech_level",
"noise_level", "clipped"; each has a default that passes the checks) and whose voice it is ("person",
"variant"). The embedding is a fixed random direction per person with a small change per variant, so
recordings of one person match and recordings of two people do not.

    python fake_voice_engine.py [--ecapa-sha256 HEX] [--broken] [--bad-rate] [--drift]

--broken gives an embedding with a value that is not a number; --bad-rate answers for another sample rate;
--drift changes the embedding slightly on every extraction, so a repeated extraction differs (H55).
"""

import json
import random
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engines"))
import protocol  # noqa: E402

ECAPA_SHA256 = "0575cb64845e6b9a10db9bcb74d5ac32b326b8dc90352671d345e2ee3d0126a2"
LENGTH = 192
PASSING = {"duration": 5.0, "speech": 3.6, "speech_level": -24.0, "noise_level": -58.0, "clipped": 0.0}
EXTRACTIONS: list[int] = []


def option(name: str, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def read(data: bytes) -> dict | None:
    while data.startswith(b"RIFFWAV:"):  # a recording this engine made again from its samples (a stored one, H55)
        data = data[len(b"RIFFWAV:"):]
    if not data.startswith(b"FAKEVOICE"):
        return None
    return json.loads(data[len(b"FAKEVOICE"):])


def embedding(person: str, variant: int) -> list[float]:
    base = random.Random(f"voice:{person}")
    change = random.Random(f"voice:{person}:{variant}")
    return [base.gauss(0, 1) + 0.15 * change.gauss(0, 1) for _ in range(LENGTH)]


def extract(_header, parts):
    spec = read(parts[0])
    if spec is None:
        return {"invalid": "the data is not a recording"}, b""
    reply = {"sample_rate": 8000 if "--bad-rate" in sys.argv else 16000,
             **{name: spec.get(name, value) for name, value in PASSING.items()}, "embedding_length": LENGTH}
    if reply["duration"] < 1:
        return reply, b""
    values = embedding(spec.get("person", "a"), spec.get("variant", 0))
    if "--broken" in sys.argv:
        values[0] = float("nan")
    if "--drift" in sys.argv:
        EXTRACTIONS.append(1)
        values[0] += 0.01 * len(EXTRACTIONS)
    return reply, [b"RIFF" + b"WAV:" + parts[0], struct.pack(f"<{LENGTH}f", *values)]


protocol.serve({"engine": "voice", "speechbrain": "fake", "torch": "fake",
                "ecapa_sha256": option("--ecapa-sha256", ECAPA_SHA256), "embedding_length": LENGTH,
                "sample_rate": 16000, "threads": 8},
               {"extract": extract})
