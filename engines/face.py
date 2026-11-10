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
can tell a refused image from a failed engine. H51 (images from files): OpenCV refuses an image of more than
50 million pixels before it decodes it, an image is turned upright by its EXIF orientation, and one whose
longer side is above 1920 pixels is detected on, and stored as, a copy scaled down to 1920 (`stored`). H52:
a face too large for YuNet is found on smaller copies, and a face found on any copy is found again on the
image's own pixels; boxes, landmarks, the alignment and the checks are in the image's own pixels (`width`,
`height`, also given as `decoded`).
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parents[1]
if str(SYSTEM_ROOT / "engines") not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT / "engines"))

MAX_PIXELS = 50_000_000  # H27's largest image
LONGEST_SIDE = 1920  # H51: a larger image is scaled down to this, never up
# OpenCV reads its limit from the environment, so it is set before OpenCV loads (H51): a small file that
# would decode to more pixels is refused before any memory is taken for it.
os.environ["OPENCV_IO_MAX_IMAGE_PIXELS"] = str(MAX_PIXELS)

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


def check_model(path: Path, expected: str) -> None:
    """The model file must be the pinned one."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != expected:
        raise RuntimeError(f"{path.name} has SHA-256 {digest}, {expected} expected")


SMALLER_SIDES = (960, 640, 480, 320)  # H52: YuNet finds faces of about 10 to 300 pixels (OpenCV Zoo)
REFINED_FACE = 200  # H52: a face found on a copy is found again on the image's own pixels at about this width


def scaled(image: np.ndarray, longest: int) -> np.ndarray:
    """A copy whose longer side is `longest`, made smaller with INTER_AREA."""
    height, width = image.shape[:2]
    scale = longest / max(width, height)
    return cv2.resize(image, (max(1, round(width * scale)), max(1, round(height * scale))), interpolation=cv2.INTER_AREA)


def decode(data: bytes) -> tuple[np.ndarray, np.ndarray]:
    """The image's own pixels as 8-bit colour, upright by its EXIF orientation (OpenCV's imdecode does both), and
    the copy that is detected on and stored: the image itself, or for a longer side above LONGEST_SIDE, a copy
    scaled down to it (H51)."""
    try:
        image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    except cv2.error:  # OpenCV's own pixel limit, checked before decoding
        raise ValueError("the image has too many pixels") from None
    if image is None:
        raise ValueError("the data is not an image")
    height, width = image.shape[:2]
    if width * height > MAX_PIXELS:
        raise ValueError("the image has too many pixels")
    return image, (scaled(image, LONGEST_SIDE) if max(width, height) > LONGEST_SIDE else image)


def moved(rows: np.ndarray, sx: float, sy: float, dx: float = 0.0, dy: float = 0.0) -> np.ndarray:
    """Detections in another frame's pixels: every x times sx plus dx, every y times sy plus dy; widths and
    heights are only scaled, and the score stays."""
    rows = rows.astype(np.float32, copy=True)
    rows[:, [0, 2, 4, 6, 8, 10, 12]] *= sx
    rows[:, [1, 3, 5, 7, 9, 11, 13]] *= sy
    rows[:, [0, 4, 6, 8, 10, 12]] += dx
    rows[:, [1, 5, 7, 9, 11, 13]] += dy
    return rows


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
        """One detection at the image's own size, the highest score first."""
        height, width = image.shape[:2]
        self.detector.setInputSize((width, height))
        _, rows = self.detector.detect(image)
        if rows is None:
            return np.zeros((0, 15), np.float32)
        return rows[np.argsort(-rows[:, 14], kind="stable")]

    def locate(self, image: np.ndarray, copy: np.ndarray) -> np.ndarray:
        """The faces of an image, in its own pixels (H52). They are detected on the copy at its own size, as before
        H52, and only when none is found there, on smaller copies of it. A face found on a smaller copy, or on a
        copy smaller than the image, is then found again on the image's own pixels around it, so its landmarks
        are as precise as a camera frame's. A camera frame whose face is found at once is read as before."""
        rows, smaller = self.find(copy), False
        if not len(rows):
            for longest in SMALLER_SIDES:
                if longest >= max(copy.shape[:2]):
                    continue
                small = scaled(copy, longest)
                rows = self.find(small)
                if len(rows):
                    rows, smaller = moved(rows, copy.shape[1] / small.shape[1], copy.shape[0] / small.shape[0]), True
                    break
        if copy is not image and len(rows):
            rows = moved(rows, image.shape[1] / copy.shape[1], image.shape[0] / copy.shape[0])
        if len(rows) == 1 and (smaller or copy is not image):
            again = self.again(image, rows[0])
            if again is not None:
                rows = again[None, :]
        return rows

    def again(self, image: np.ndarray, row: np.ndarray) -> np.ndarray | None:
        """H52: the face found again in the region around it, cut from the image's own pixels and scaled so that the
        face is about REFINED_FACE wide, never enlarged; its row in the image's pixels, or None."""
        x, y, w, h = (float(v) for v in row[:4])
        cx, cy, side = x + w / 2, y + h / 2, 2 * max(w, h)
        x0, y0 = int(max(0, cx - side / 2)), int(max(0, cy - side / 2))
        x1, y1 = int(min(image.shape[1], cx + side / 2)), int(min(image.shape[0], cy + side / 2))
        if x1 - x0 < 2 or y1 - y0 < 2:
            return None
        region = image[y0:y1, x0:x1]
        scale = min(1.0, REFINED_FACE / max(w, 1.0))
        small = region if scale >= 1 else cv2.resize(
            region, (max(1, round(region.shape[1] * scale)), max(1, round(region.shape[0] * scale))),
            interpolation=cv2.INTER_AREA)
        found = self.find(small)
        if not len(found):
            return None
        sx, sy = region.shape[1] / small.shape[1], region.shape[0] / small.shape[0]
        centres = ((found[:, 0] + found[:, 2] / 2) * sx + x0 - cx) ** 2 + ((found[:, 1] + found[:, 3] / 2) * sy + y0 - cy) ** 2
        return moved(found[[int(np.argmin(centres))]], sx, sy, x0, y0)[0]

    def detect(self, _header: dict, parts: list[bytes]):
        try:
            image, copy = decode(parts[0])
        except ValueError as error:
            return {"invalid": str(error)}, b""
        rows = self.locate(image, copy)
        return {"width": image.shape[1], "height": image.shape[0], "decoded": [image.shape[1], image.shape[0]],
                "stored": [copy.shape[1], copy.shape[0]], "faces": [face_json(r) for r in rows]}, b""

    def extract(self, _header: dict, parts: list[bytes]):
        try:
            image, copy = decode(parts[0])
        except ValueError as error:
            return {"invalid": str(error)}, b""
        rows = self.locate(image, copy)
        reply = {"width": image.shape[1], "height": image.shape[0], "decoded": [image.shape[1], image.shape[0]],
                 "stored": [copy.shape[1], copy.shape[0]], "faces": [face_json(r) for r in rows],
                 "embedding_length": self.length}
        if len(rows) != 1:
            return reply, b""
        aligned = self.recognizer.alignCrop(image, rows[0])  # the image's own pixels (H52)
        embedding = self.recognizer.feature(aligned).astype("<f4").reshape(-1)
        if embedding.size != self.length or not np.all(np.isfinite(embedding)):
            raise ValueError("SFace returned an invalid embedding")
        png = cv2.imencode(".png", copy)[1].tobytes()  # the copy is what is stored (H51)
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
