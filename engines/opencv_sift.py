"""The OpenCV SIFT engine (H10, H13, H33), run by the server in the research project environment.

It uses the research's method through the pinned link (methods/research_link.py): the link is checked
before anything runs, the comparison is the research's `compare` with its seeded matcher and one OpenCV
thread (`init_worker`), unchanged. The research's `extract` reads an image file, and a capture never
reaches the disk unsealed (H13), so this engine decodes the PNG in memory and runs the same OpenCV call;
`engines/test_engines.py` shows that the result equals the research function's on the same image.

Operations (protocol.py):
  extract  data: a PNG       -> keypoints, the template (the research's .npz layout) and, for the
                                template screen, the points (float32 x, y) and the descriptors (uint8)
  compare  parts: probe, reference templates -> status, score (RANSAC inliers), good matches
"""

from __future__ import annotations

import io
import sys
import tomllib
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parents[1]
for folder in (SYSTEM_ROOT / "engines", SYSTEM_ROOT / "methods"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

import protocol  # noqa: E402
import research_link  # noqa: E402

ALGORITHM = "opencv-sift"


def extract_png(png: bytes) -> tuple[np.ndarray, np.ndarray]:
    """The research's `extract` (fpl3.algorithms.opencv_sift) on a PNG held in memory."""
    image = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError("the data is not an image")
    keypoints, descriptors = cv2.SIFT_create().detectAndCompute(image, None)
    points = np.float32([kp.pt for kp in keypoints]).reshape(-1, 2)
    if descriptors is None:
        descriptors = np.zeros((0, 128), np.float32)
    return points, descriptors


def template_bytes(points: np.ndarray, descriptors: np.ndarray) -> bytes:
    """The template as the research stores its features (np.savez: `points`, `descriptors`)."""
    buffer = io.BytesIO()
    np.savez(buffer, points=points, descriptors=descriptors)
    return buffer.getvalue()


def from_template(data: bytes) -> tuple[np.ndarray, np.ndarray]:
    with np.load(io.BytesIO(data), allow_pickle=False) as arrays:
        return arrays["points"], arrays["descriptors"]


def view_bytes(points: np.ndarray, descriptors: np.ndarray) -> tuple[bytes, bytes]:
    """What the template screen draws: SIFT's descriptor values are whole numbers from 0 to 255 (OpenCV
    rounds them to bytes before storing them as float32), so they travel as one byte each, unchanged."""
    if descriptors.size and (descriptors.min() < 0 or descriptors.max() > 255
                             or not np.array_equal(descriptors, np.rint(descriptors))):
        raise ValueError("descriptor values are not whole numbers from 0 to 255")
    return points.astype("<f4").tobytes(), descriptors.astype(np.uint8).tobytes()


def main() -> None:
    link = research_link.load()
    research_link.verify(link)
    import fpl3
    from fpl3.algorithms import opencv_sift

    research_link.verify_package(link, fpl3.__file__)
    with open(link.repository / "configs" / "protocol.toml", "rb") as f:
        master_seed = tomllib.load(f)["randomness"]["master_seed"]
    seed = opencv_sift.rng_seed(master_seed)
    opencv_sift.init_worker(seed)  # one OpenCV thread, FLANN seeded before every comparison, as in H10

    def extract(_header: dict, parts: list[bytes]):
        points, descriptors = extract_png(parts[0])
        view_points, view_descriptors = view_bytes(points, descriptors)
        return {"keypoints": len(points)}, [template_bytes(points, descriptors), view_points, view_descriptors]

    def compare(_header: dict, parts: list[bytes]):
        if len(parts) != 2:
            raise ValueError("compare needs a probe and a reference template")
        result = opencv_sift.compare(from_template(parts[0]), from_template(parts[1]), seed)
        return {"status": result["status"], "reason": result["reason"], "score": result["score"],
                "good": result["good"]}, b""

    protocol.serve({"algorithm": ALGORITHM, "version": link.commit, "opencv": cv2.__version__},
                   {"extract": extract, "compare": compare})


if __name__ == "__main__":
    main()
