"""Tests of the face engine (H48), run with the research project environment's Python like the other engine
tests; the engine itself runs in the face environment (environments/face.yml).

The images here are synthetic, never of a person, so these tests cover the protocol, the model pins and the
cases without a face; faces are tried by hand on the researcher's camera. The face environment is found
next to this Python's environment or named by MBS_FACE_PYTHON, and the models in local/models/face or in
MBS_FACE_MODELS. Tests whose requirements are missing are skipped.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

ENGINES = Path(__file__).resolve().parent
SYSTEM_ROOT = ENGINES.parent
sys.path[:0] = [str(ENGINES), str(SYSTEM_ROOT / "methods")]

import face  # noqa: E402
import protocol  # noqa: E402
import research_link  # noqa: E402

FACE_PYTHON = Path(os.environ.get("MBS_FACE_PYTHON") or Path(sys.prefix).parent / "multimodal-face" / "python.exe")
MODELS = Path(os.environ.get("MBS_FACE_MODELS") or SYSTEM_ROOT / "local" / "models" / "face")
needs_face = pytest.mark.skipif(
    not (FACE_PYTHON.exists() and (MODELS / face.YUNET).exists() and (MODELS / face.SFACE).exists()),
    reason="the face environment or its models are missing")


def encoded(image: np.ndarray, kind: str = ".png") -> bytes:
    ok, data = cv2.imencode(kind, image)
    assert ok
    return data.tobytes()


def flat(width: int = 1280, height: int = 720, value: int = 128) -> np.ndarray:
    return np.full((height, width, 3), value, np.uint8)


@pytest.fixture
def engine():
    process = subprocess.Popen([str(FACE_PYTHON), "-I", str(ENGINES / "face.py"), str(MODELS)],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               env=research_link.environment(FACE_PYTHON))
    try:
        yield process
    finally:
        process.stdin.close()
        process.wait(30)


def ask(process: subprocess.Popen, header: dict, data: bytes | list[bytes] = b"") -> tuple[dict, list[bytes]]:
    protocol.write_message(process.stdin, header, data)
    return protocol.read_message(process.stdout)


@needs_face
def test_the_engine_names_its_pinned_models_and_reads_the_embedding_length(engine):
    ready, _ = protocol.read_message(engine.stdout)  # nothing but the protocol on standard output
    assert ready["ok"] and ready["engine"] == "face"
    assert ready["yunet_sha256"] == face.YUNET_SHA256 and ready["sface_sha256"] == face.SFACE_SHA256
    assert ready["opencv"] == "5.0.0" and ready["embedding_length"] == 128 and ready["score_threshold"] == 0.9


@needs_face
def test_an_image_without_a_face_has_no_faces_and_no_embedding(engine):
    protocol.read_message(engine.stdout)
    reply, _ = ask(engine, {"op": "detect"}, encoded(flat()))
    assert reply == {"ok": True, "width": 1280, "height": 720, "decoded": [1280, 720], "stored": [1280, 720],
                     "faces": [], "length": 0}
    noise = np.random.default_rng(4).integers(0, 256, (360, 640, 3), dtype=np.uint8)
    reply, parts = ask(engine, {"op": "extract"}, encoded(noise, ".jpg"))
    assert reply["ok"] and reply["width"] == 640 and reply["height"] == 360 and reply["faces"] == []
    assert reply["embedding_length"] == 128 and parts == [b""]


@needs_face
def test_data_that_is_not_an_image_is_refused_and_the_engine_keeps_serving(engine):
    protocol.read_message(engine.stdout)
    reply, _ = ask(engine, {"op": "extract"}, b"not an image")
    assert reply == {"ok": True, "invalid": "the data is not an image", "length": 0}
    reply, _ = ask(engine, {"op": "detect"}, encoded(flat(320, 180)))
    assert reply["ok"] and (reply["width"], reply["height"]) == (320, 180)


def test_a_model_file_that_differs_from_its_pin_is_refused(tmp_path):
    copy = tmp_path / face.YUNET
    copy.write_bytes(b"not the pinned model")
    with pytest.raises(RuntimeError, match="SHA-256"):
        face.check_model(copy, face.YUNET_SHA256)


def test_images_are_read_by_their_content_and_bounded_in_size(monkeypatch):
    image = flat(64, 48, 90)
    for kind in (".png", ".jpg", ".bmp"):
        decoded, copy = face.decode(encoded(image, kind))
        assert decoded.shape == (48, 64, 3) and copy is decoded
    monkeypatch.setattr(face, "MAX_PIXELS", 64 * 48 - 1)
    with pytest.raises(ValueError, match="too many pixels"):
        face.decode(encoded(image))


def with_orientation(jpeg: bytes, orientation: int) -> bytes:
    """The JPEG with an EXIF segment that holds only its orientation, as a phone writes it."""
    tiff = (b"MM\x00\x2a" + (8).to_bytes(4, "big") + (1).to_bytes(2, "big") + (0x0112).to_bytes(2, "big")
            + (3).to_bytes(2, "big") + (1).to_bytes(4, "big") + orientation.to_bytes(2, "big") + b"\x00\x00"
            + (0).to_bytes(4, "big"))
    payload = b"Exif\x00\x00" + tiff
    return jpeg[:2] + b"\xff\xe1" + (len(payload) + 2).to_bytes(2, "big") + payload + jpeg[2:]


@needs_face
def test_a_phone_photo_is_turned_upright_by_its_exif_orientation(engine):
    protocol.read_message(engine.stdout)
    image = flat(200, 100, 30)
    image[:, :100] = 230  # the left half is light
    reply, _ = ask(engine, {"op": "extract"}, with_orientation(encoded(image, ".jpg"), 6))
    assert (reply["width"], reply["height"], reply["decoded"]) == (100, 200, [100, 200])


@needs_face
def test_a_larger_image_is_scaled_down_to_1920_and_its_decoded_size_reported(engine):
    protocol.read_message(engine.stdout)
    reply, _ = ask(engine, {"op": "extract"}, encoded(flat(3840, 2160), ".jpg"))
    assert (reply["width"], reply["height"], reply["decoded"], reply["stored"]) == (3840, 2160, [3840, 2160], [1920, 1080])
    reply, _ = ask(engine, {"op": "extract"}, encoded(flat(1000, 2400), ".jpg"))
    assert (reply["width"], reply["height"], reply["decoded"], reply["stored"]) == (1000, 2400, [1000, 2400], [800, 1920])


class StandInDetector:
    """H52's tests without a face: a white rectangle on black stands for a face, found like YuNet only while it is
    10 to 300 pixels wide; its five landmarks sit at fixed places inside it."""

    def __init__(self):
        self.sizes = []

    def setInputSize(self, size):
        self.sizes.append(tuple(size))

    def detect(self, image):
        ys, xs = np.nonzero(image[..., 0] > 127)
        if not len(xs):
            return 1, None
        x, y, w, h = xs.min(), ys.min(), xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
        if not 10 <= w <= 300:
            return 1, None
        points = [(0.3, 0.4), (0.7, 0.4), (0.5, 0.6), (0.35, 0.8), (0.65, 0.8)]
        return 1, np.array([[x, y, w, h, *[v for px, py in points for v in (x + px * w, y + py * h)], 0.95]], np.float32)


def faces_with(detector: StandInDetector) -> face.Faces:
    found = object.__new__(face.Faces)  # no models: only the detector is used here
    found.detector = detector
    return found


def picture(width: int, height: int, box: tuple[int, int, int, int]) -> np.ndarray:
    image = np.zeros((height, width, 3), np.uint8)
    x, y, w, h = box
    image[y:y + h, x:x + w] = 255
    return image


def test_a_face_found_at_the_frames_own_size_is_read_as_before():
    detector = StandInDetector()
    image = picture(1280, 720, (500, 200, 230, 280))  # a camera frame
    rows = faces_with(detector).locate(*face.decode(encoded(image)))
    assert detector.sizes == [(1280, 720)]  # one detection, no copy and no second look
    assert rows[0][:4].tolist() == [500, 200, 230, 280]


def test_a_face_too_large_for_the_detector_is_found_on_a_smaller_copy_and_again_on_the_own_pixels():
    detector = StandInDetector()
    image = picture(1080, 1080, (320, 240, 430, 595))  # as the researcher's close photo
    rows = faces_with(detector).locate(*face.decode(encoded(image)))
    assert detector.sizes[:3] == [(1080, 1080), (960, 960), (640, 640)]  # 430 and 382 pixels wide: too large
    assert len(rows) == 1 and rows[0][:4] == pytest.approx([320, 240, 430, 595], abs=3)  # found again, mapped back
    assert len(detector.sizes) == 4 and max(detector.sizes[3]) < 1080  # the second look, scaled to about 200


def test_a_small_face_in_a_large_photo_is_measured_on_its_own_pixels():
    detector = StandInDetector()
    image = picture(6000, 4000, (2900, 1800, 234, 300))  # 75 pixels wide on the 1920 copy
    rows = faces_with(detector).locate(*face.decode(encoded(image, ".jpg")))
    assert detector.sizes[0] == (1920, 1280) and len(rows) == 1
    assert rows[0][:4] == pytest.approx([2900, 1800, 234, 300], abs=3)
    tiny = picture(6000, 4000, (2900, 1800, 90, 120))  # under 112 pixels even on its own pixels: never enlarged
    rows = faces_with(StandInDetector()).locate(*face.decode(encoded(tiny, ".jpg")))
    assert rows[0][2] == pytest.approx(90, abs=3)


@needs_face
def test_an_image_of_more_than_50_million_pixels_is_refused_before_it_is_decoded(engine):
    protocol.read_message(engine.stdout)
    reply, _ = ask(engine, {"op": "extract"}, encoded(np.zeros((7072, 7072), np.uint8)))  # 50.01 million
    assert reply == {"ok": True, "invalid": "the image has too many pixels", "length": 0}
    reply, _ = ask(engine, {"op": "detect"}, encoded(flat(320, 180)))
    assert reply["ok"] and (reply["width"], reply["height"]) == (320, 180)


def test_a_detected_face_is_reported_as_box_landmarks_and_score():
    row = np.arange(15, dtype=np.float32)
    assert face.face_json(row) == {"box": [0.0, 1.0, 2.0, 3.0],
                                   "landmarks": [[4.0, 5.0], [6.0, 7.0], [8.0, 9.0], [10.0, 11.0], [12.0, 13.0]],
                                   "score": 14.0}
