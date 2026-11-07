"""Stand-ins for the NFIQ 2 and OpenCV SIFT engines in the tests, speaking the engines' real protocol
(engines/protocol.py). A fake capture is b"FAKEPNG:q<score>:<finger><n>": its quality is the score (255 for
"not computed"), and two captures match (score 90) when their labels start with the same finger letter,
otherwise score 5.

    python fake_engine.py quality|sift
"""

import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engines"))
import protocol  # noqa: E402

KEYPOINTS = 3
PORE = sys.argv[1] == "pore"
LEARNED = sys.argv[1] == "learned"


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
    if PORE:
        return {"keypoints": KEYPOINTS}, b"PORE:" + name.encode()
    if LEARNED:
        assert parts[1] == b"PORE:" + name.encode(), "must use this capture's shared pores"
        return {}, b"LEARNED:" + name.encode()
    points = struct.pack("<6f", 10, 20, 30, 40, 50, 60)
    descriptors = bytes(range(KEYPOINTS * 128 % 256)) + bytes(KEYPOINTS * 128 - KEYPOINTS * 128 % 256)
    return {"keypoints": KEYPOINTS}, [b"TEMPLATE:" + name.encode(), points, descriptors]


def compare(_header, parts):
    if "--hang-compare" in sys.argv:
        Path(sys.argv[sys.argv.index("--hang-compare") + 1]).write_text("comparing", encoding="utf-8")
        time.sleep(120)
    if PORE:
        assert all(part.startswith(b"PORE:") for part in parts)
    if LEARNED:
        assert all(part.startswith(b"LEARNED:") for part in parts)
    probe, reference = (p.decode().split(":", 1)[1] for p in parts)
    same, other = (30, 2) if LEARNED else (45, 3) if PORE else (90, 5)
    return {"status": "ok", "reason": "", "score": same if probe[0] == reference[0] else other, "good": 12}, b""


if sys.argv[1] == "quality":
    protocol.serve({"engine": "nfiq2", "version": "2.3.0", "model_hash": "fake"}, {"quality": quality})
else:
    protocol.serve({"algorithm": "learned-pore" if LEARNED else "pore-sift" if PORE else "opencv-sift",
                    "version": "606c8d33a7a27570b5bb55cca8248259b9b6ba8a"},
                   {"extract": extract, "detect": extract, "compare": compare})
