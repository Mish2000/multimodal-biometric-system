"""The face engine (H48): YuNet finds faces and SFace describes one, with OpenCV in the face environment.

Both models come from OpenCV Zoo, pinned by SHA-256; the engine refuses other files. An image is read from
memory and decoded by its content, never by a name or a stated type, and no file is written. The engine
keeps nothing between requests (H13).

    python -I face.py MODELS_DIR        the folder with the two ONNX files (local/models/face)

Operations (protocol.py):
  detect   data: an image -> width, height and faces [{box: [x, y, w, h], landmarks: [[x, y] x 5], score}],
           the highest score first; for the camera's live view
  extract  data: an image -> as detect; for exactly one face, three parts: the image again as a PNG made
           from its pixels alone, the aligned 112 x 112 face as a PNG, and SFace's embedding as float32
           values, little-endian
Data that is not an image, or has too many pixels, is answered with `invalid` and its reason, so the server
can tell a refused image from a failed engine.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parents[1]
if str(SYSTEM_ROOT / "engines") not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT / "engines"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

import protocol  # noqa: E402

YUNET = "face_detection_yunet_2023mar.onnx"
YUNET_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
SFACE = "face_recognition_sface_2021dec.onnx"
SFACE_SHA256 = "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79"
SCORE_THRESHOLD = 0.9  # OpenCV Zoo's YuNet demo
NMS_THRESHOLD = 0.3
TOP_K = 5000
MAX_PIXELS = 50_000_000  # H27's largest image


def check_model(path: Path, expected: str) -> None:
    """The model file must be the pinned one."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != expected:
        raise RuntimeError(f"{path.name} has SHA-256 {digest}, {expected} expected")


def decode(data: bytes) -> np.ndarray:
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("the data is not an image")
    height, width = image.shape[:2]
    if width * height > MAX_PIXELS:
        raise ValueError("the image has too many pixels")
    return image


def face_json(row: np.ndarray) -> dict:
    values = [float(v) for v in row]
    return {"box": values[0:4], "landmarks": [values[4 + 2 * i:6 + 2 * i] for i in range(5)], "score": values[14]}


class Faces:
    def __init__(self, folder: Path):
        check_model(folder / YUNET, YUNET_SHA256)
        check_model(folder / SFACE, SFACE_SHA256)
        self.detector = cv2.FaceDetectorYN.create(str(folder / YUNET), "", (320, 320), SCORE_THRESHOLD,
                                                  NMS_THRESHOLD, TOP_K)
        self.recognizer = cv2.FaceRecognizerSF.create(str(folder / SFACE), "")
        # SFace's embedding length, read from the model rather than assumed (specification 5.2).
        self.length = int(self.recognizer.feature(np.zeros((112, 112, 3), np.uint8)).size)

    def find(self, image: np.ndarray) -> np.ndarray:
        height, width = image.shape[:2]
        self.detector.setInputSize((width, height))
        _, rows = self.detector.detect(image)
        if rows is None:
            return np.zeros((0, 15), np.float32)
        return rows[np.argsort(-rows[:, 14], kind="stable")]

    def detect(self, _header: dict, parts: list[bytes]):
        try:
            image = decode(parts[0])
        except ValueError as error:
            return {"invalid": str(error)}, b""
        rows = self.find(image)
        return {"width": image.shape[1], "height": image.shape[0], "faces": [face_json(r) for r in rows]}, b""

    def extract(self, _header: dict, parts: list[bytes]):
        try:
            image = decode(parts[0])
        except ValueError as error:
            return {"invalid": str(error)}, b""
        rows = self.find(image)
        reply = {"width": image.shape[1], "height": image.shape[0], "faces": [face_json(r) for r in rows],
                 "embedding_length": self.length}
        if len(rows) != 1:
            return reply, b""
        aligned = self.recognizer.alignCrop(image, rows[0])
        embedding = self.recognizer.feature(aligned).astype("<f4").reshape(-1)
        if embedding.size != self.length or not np.all(np.isfinite(embedding)):
            raise ValueError("SFace returned an invalid embedding")
        png = cv2.imencode(".png", image)[1].tobytes()
        face = cv2.imencode(".png", aligned)[1].tobytes()
        return reply, [png, face, embedding.tobytes()]


def main() -> None:
    # OpenCV's own messages must not reach standard output, which carries the protocol.
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
    faces = Faces(Path(sys.argv[1]).resolve())
    protocol.serve({"engine": "face", "opencv": cv2.__version__, "yunet_sha256": YUNET_SHA256,
                    "sface_sha256": SFACE_SHA256, "embedding_length": faces.length,
                    "score_threshold": SCORE_THRESHOLD},
                   {"detect": faces.detect, "extract": faces.extract})


if __name__ == "__main__":
    main()
