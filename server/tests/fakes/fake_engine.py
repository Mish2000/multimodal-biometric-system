"""Stand-ins for the NFIQ 2 and OpenCV SIFT engines in the tests, speaking the engines' real protocol
(engines/protocol.py). A fake capture is b"FAKEPNG:q<score>:<finger><n>": its quality is the score (255 for
"not computed"), and two captures match (score 90) when their labels start with the same finger letter,
otherwise score 5.

    python fake_engine.py quality|sift
"""

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engines"))
import protocol  # noqa: E402

KEYPOINTS = 3


def label(data: bytes) -> tuple[int, str]:
    text = data.decode()
    assert text.startswith("FAKEPNG:q"), text
    score, name = text[len("FAKEPNG:q"):].split(":", 1)
    return int(score), name


def quality(_header, parts):
    score, _ = label(parts[0])
    valid = 0 <= score <= 100
    return {"score": score if valid else None, "valid": valid, "code": score}, b""


def extract(_header, parts):
    _, name = label(parts[0])
    points = struct.pack("<6f", 10, 20, 30, 40, 50, 60)
    descriptors = bytes(range(KEYPOINTS * 128 % 256)) + bytes(KEYPOINTS * 128 - KEYPOINTS * 128 % 256)
    return {"keypoints": KEYPOINTS}, [b"TEMPLATE:" + name.encode(), points, descriptors]


def compare(_header, parts):
    probe, reference = (p.decode().split(":", 1)[1] for p in parts)
    return {"status": "ok", "reason": "", "score": 90 if probe[0] == reference[0] else 5, "good": 12}, b""


if sys.argv[1] == "quality":
    protocol.serve({"engine": "nfiq2", "version": "2.3.0", "model_hash": "fake"}, {"quality": quality})
else:
    protocol.serve({"algorithm": "opencv-sift", "version": "606c8d33a7a27570b5bb55cca8248259b9b6ba8a"},
                   {"extract": extract, "compare": compare})
