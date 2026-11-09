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
    assert reply == {"ok": True, "width": 1280, "height": 720, "faces": [], "length": 0}
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
        assert face.decode(encoded(image, kind)).shape == (48, 64, 3)
    monkeypatch.setattr(face, "MAX_PIXELS", 64 * 48 - 1)
    with pytest.raises(ValueError, match="too many pixels"):
        face.decode(encoded(image))


def test_a_detected_face_is_reported_as_box_landmarks_and_score():
    row = np.arange(15, dtype=np.float32)
    assert face.face_json(row) == {"box": [0.0, 1.0, 2.0, 3.0],
                                   "landmarks": [[4.0, 5.0], [6.0, 7.0], [8.0, 9.0], [10.0, 11.0], [12.0, 13.0]],
                                   "score": 14.0}
