"""Tests of the engines, run with the research project environment's Python (engines/README.md).

The images here are synthetic ridge patterns, never captures. The OpenCV SIFT tests need the pinned
research checkout (local/research.toml); the NFIQ 2 test needs the built library, named by MBS_NFIQ2_BIN
or by nfiq2_bin in local/server.toml. Tests whose requirements are missing are skipped.
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
import tomllib
import types
import weakref
from pathlib import Path

import cv2
import numpy as np
import pytest

ENGINES = Path(__file__).resolve().parent
SYSTEM_ROOT = ENGINES.parent
sys.path[:0] = [str(ENGINES), str(SYSTEM_ROOT / "methods")]

import nfiq2_quality  # noqa: E402
import opencv_sift  # noqa: E402
import protocol  # noqa: E402
import research_link  # noqa: E402


def ridges(size: int = 1000, seed: int = 1, shift: tuple[int, int] = (0, 0)) -> np.ndarray:
    """A fingerprint-like synthetic image: curved ridges of about 9 pixels with noise."""
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:size, 0:size].astype(np.float32)
    x, y = x + shift[0], y + shift[1]
    angle = 0.002 * (x - size / 2) * (y - size / 3) / size
    phase = (x * np.cos(angle) + y * np.sin(angle)) * 2 * np.pi / 9 + 3 * np.sin(x / 70) + 2 * np.cos(y / 55)
    image = 128 + 90 * np.sin(phase) + rng.normal(0, 12, (size, size))
    return np.clip(image, 0, 255).astype(np.uint8)


def png(image: np.ndarray) -> bytes:
    ok, data = cv2.imencode(".png", image)
    assert ok
    return data.tobytes()


def research_available() -> bool:
    try:
        research_link.verify(research_link.load())
        import fpl3  # noqa: F401
    except Exception:
        return False
    return True


def nfiq2_folder() -> Path | None:
    if os.environ.get("MBS_NFIQ2_BIN"):
        return Path(os.environ["MBS_NFIQ2_BIN"])
    local = SYSTEM_ROOT / "local" / "server.toml"
    if local.exists():
        with open(local, "rb") as f:
            value = tomllib.load(f).get("nfiq2_bin")
        if value:
            return Path(value)
    return None


needs_research = pytest.mark.skipif(not research_available(), reason="the pinned research checkout is not available")


def test_messages_keep_their_parts():
    stream = io.BytesIO()
    protocol.write_message(stream, {"op": "compare"}, [b"ab\n", b"", b"\x00\xff"])
    protocol.write_message(stream, {"op": "extract"}, b"png")
    stream.seek(0)
    header, parts = protocol.read_message(stream)
    assert header == {"op": "compare", "length": 5, "parts": [3, 0, 2]} and parts == [b"ab\n", b"", b"\x00\xff"]
    header, parts = protocol.read_message(stream)
    assert header == {"op": "extract", "length": 3} and parts == [b"png"]
    assert protocol.read_message(stream) is None


def test_a_cut_message_is_refused():
    stream = io.BytesIO(b'{"op":"extract","length":9}\nabc')
    with pytest.raises(protocol.ProtocolError):
        protocol.read_message(stream)


def test_completed_request_releases_its_result_before_waiting(monkeypatch):
    """H13, H39: a loaded engine must release a derived result while idle."""
    class Binary(bytearray):
        pass
    references = []
    incoming = iter([({"op": "extract"}, [b"synthetic"]), None])
    output = io.BytesIO()
    def read(_source):
        if references:
            assert references[0]() is None
        return next(incoming)
    def extract(_header, _parts):
        data = Binary(b"derived data")
        references.append(weakref.ref(data))
        return {}, data
    monkeypatch.setattr(protocol, "read_message", read)
    monkeypatch.setattr(sys, "stdin", types.SimpleNamespace(buffer=io.BytesIO()))
    monkeypatch.setattr(sys, "stdout", types.SimpleNamespace(buffer=output))
    protocol.serve({"engine": "synthetic"}, {"extract": extract})
    assert b"derived data" in output.getvalue()


def test_the_500_ppi_copy_is_the_mean_of_each_block():
    image = np.arange(16, dtype=np.uint8).reshape(4, 4) * 10
    expected = [[round((0 + 10 + 40 + 50) / 4), round((20 + 30 + 60 + 70) / 4)],
                [round((80 + 90 + 120 + 130) / 4), round((100 + 110 + 140 + 150) / 4)]]
    assert nfiq2_quality.to_500(image).tolist() == expected
    assert nfiq2_quality.to_500(np.zeros((1000, 1000), np.uint8)).shape == (500, 500)


@needs_research
def test_extraction_from_memory_equals_the_research_function(tmp_path):
    from fpl3.algorithms import opencv_sift as research

    image = ridges()
    path = tmp_path / "ridges.png"
    path.write_bytes(png(image))
    cv2.setNumThreads(1)
    expected_points, expected_descriptors = research.extract(path)
    points, descriptors = opencv_sift.extract_png(path.read_bytes())
    assert len(points) > 500
    assert np.array_equal(points, expected_points) and np.array_equal(descriptors, expected_descriptors)
    view_points, view_descriptors = opencv_sift.view_bytes(points, descriptors)
    assert np.array_equal(np.frombuffer(view_points, "<f4").reshape(-1, 2), points)
    assert np.array_equal(np.frombuffer(view_descriptors, np.uint8).reshape(-1, 128), descriptors)


def run_engine(script: str, *args: str) -> subprocess.Popen:
    python = Path(sys.executable)
    return subprocess.Popen([str(python), "-I", str(ENGINES / script), *args], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=research_link.environment(python))


def ask(engine: subprocess.Popen, header: dict, data: bytes | list[bytes] = b"") -> tuple[dict, list[bytes]]:
    protocol.write_message(engine.stdin, header, data)
    return protocol.read_message(engine.stdout)


@needs_research
def test_the_engine_scores_as_the_research_compare():
    from fpl3.algorithms import opencv_sift as research

    engine = run_engine("opencv_sift.py")
    try:
        ready, _ = protocol.read_message(engine.stdout)
        link = research_link.load()
        assert ready["ok"] and ready["algorithm"] == "opencv-sift" and ready["version"] == link.commit
        templates, features = [], []
        for image in (ridges(seed=2), ridges(seed=3, shift=(25, -15))):
            reply, parts = ask(engine, {"op": "extract"}, png(image))
            assert reply["ok"] and reply["keypoints"] == len(np.frombuffer(parts[1], "<f4")) // 2
            templates.append(parts[0])
            features.append(opencv_sift.from_template(parts[0]))
        reply, _ = ask(engine, {"op": "compare"}, [templates[1], templates[0]])
        with open(link.repository / "configs" / "protocol.toml", "rb") as f:
            seed = research.rng_seed(tomllib.load(f)["randomness"]["master_seed"])
        cv2.setNumThreads(1)
        expected = research.compare(features[1], features[0], seed)
        assert reply["ok"] and reply["status"] == expected["status"] and reply["score"] == expected["score"]
        assert ask(engine, {"op": "unknown"})[0] == {"ok": False, "error": "unknown_operation", "length": 0}
    finally:
        engine.stdin.close()
        assert engine.wait(30) == 0


@pytest.mark.skipif(nfiq2_folder() is None, reason="the NFIQ 2 build is not configured")
def test_the_quality_engine_loads_the_model_and_scores():
    engine = run_engine("nfiq2_quality.py", str(nfiq2_folder()))
    try:
        ready, _ = protocol.read_message(engine.stdout)
        assert ready["ok"] and ready["version"] == "2.3.0" and ready["model_hash"] == nfiq2_quality.MODEL_HASH
        reply, _ = ask(engine, {"op": "quality"}, png(ridges(seed=4)))
        assert reply["ok"] and (reply["valid"] is False or 0 <= reply["score"] <= 100)
        blank, _ = ask(engine, {"op": "quality"}, png(np.full((1000, 1000), 255, np.uint8)))
        assert blank["ok"] and (blank["valid"] is False or blank["score"] < 35)
    finally:
        engine.stdin.close()
        assert engine.wait(30) == 0
