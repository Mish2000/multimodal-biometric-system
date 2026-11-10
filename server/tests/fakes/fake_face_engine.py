"""A stand-in for the face engine in the tests (H48), speaking its real protocol (engines/protocol.py). A fake
image is b"FAKEFACE" followed by JSON: the image's size, its faces ({"box": [x, y, w, h], "score": s}) and
whose face it is ("person", "variant"). The embedding is a fixed random direction per person with a small
change per variant, so images of one person match and images of two people do not.

    python fake_face_engine.py [--sface-sha256 HEX] [--broken] [--drift]

--drift changes the embedding slightly on every extraction, so a repeated extraction differs (H49).
"""

import json
import random
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engines"))
import protocol  # noqa: E402

SFACE_SHA256 = "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79"
LENGTH = 128
EXTRACTIONS: list[int] = []


def option(name: str, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def read(data: bytes) -> dict | None:
    while data.startswith(b"PNG:"):  # an image this engine made again from its pixels (a stored one, H49)
        data = data[len(b"PNG:"):]
    index = data.find(b"FAKEFACE")  # a file's real JPEG or PNG header may come first (H51)
    if index < 0:
        return None
    return json.loads(data[index + len(b"FAKEFACE"):])


def size_of(spec: dict) -> dict:
    """H51, H52: the image's own size and the stored copy's, when the label names them."""
    return {key: spec[key] for key in ("decoded", "stored") if key in spec}


def embedding(person: str, variant: int) -> list[float]:
    base = random.Random(f"person:{person}")
    change = random.Random(f"variant:{person}:{variant}")
    return [base.gauss(0, 1) + 0.15 * change.gauss(0, 1) for _ in range(LENGTH)]


def faces_of(spec: dict) -> list[dict]:
    return [{"box": face["box"], "landmarks": [[face["box"][0] + 10 * i, face["box"][1] + 10] for i in range(5)],
             "score": face.get("score", 0.95)} for face in spec.get("faces", [])]


def detect(_header, parts):
    spec = read(parts[0])
    if spec is None:
        return {"invalid": "the data is not an image"}, b""
    return {"width": spec["width"], "height": spec["height"], "faces": faces_of(spec)}, b""


def extract(_header, parts):
    spec = read(parts[0])
    if spec is None:
        return {"invalid": "the data is not an image"}, b""
    faces = faces_of(spec)
    reply = {"width": spec["width"], "height": spec["height"], "faces": faces, "embedding_length": LENGTH,
             **size_of(spec)}
    if len(faces) != 1:
        return reply, b""
    values = embedding(spec.get("person", "a"), spec.get("variant", 0))
    if "--broken" in sys.argv:
        values[0] = float("nan")
    if "--drift" in sys.argv:
        EXTRACTIONS.append(1)
        values[0] += 0.01 * len(EXTRACTIONS)
    return reply, [b"PNG:" + parts[0], b"ALIGNED:" + spec.get("person", "a").encode(), struct.pack(f"<{LENGTH}f", *values)]


protocol.serve({"engine": "face", "opencv": "fake", "yunet_sha256": "fake",
                "sface_sha256": option("--sface-sha256", SFACE_SHA256), "embedding_length": LENGTH,
                "score_threshold": 0.9}, {"detect": detect, "extract": extract})
