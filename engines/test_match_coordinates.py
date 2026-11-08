"""H43: the illustration observes the exact inliers counted by the pinned comparison."""

import types

import numpy as np
import pytest

from test_engines import ask, needs_research, opencv_sift, png, protocol, ridges, run_engine


def test_capture_keeps_only_the_returned_inliers_and_restores_the_module():
    source = np.array([[[11, 12]], [[21, 22]], [[31, 32]]], np.float32)
    destination = np.array([[[111, 112]], [[121, 122]], [[131, 132]]], np.float32)
    mask = np.array([[1], [0], [1]], np.uint8)
    calls = []
    def homography(left, right, method, threshold):
        calls.append((left is source, right is destination, method, threshold))
        return np.eye(3), mask
    original = types.SimpleNamespace(findHomography=homography)
    research = types.SimpleNamespace(cv2=original)
    def compare(_probe, _reference, seed):
        assert seed == 42
        _, actual_mask = research.cv2.findHomography(source, destination, 8, 5.0)
        assert actual_mask is mask
        return {"status": "ok", "score": int(actual_mask.sum()), "good": 3}
    research.compare = compare
    result, data = opencv_sift.compare_with_matches(research, None, None, 42)
    assert result["score"] == 2 and calls == [(True, True, 8, 5.0)]
    assert np.frombuffer(data, "<f4").reshape(-1, 4).tolist() == [[11, 12, 111, 112], [31, 32, 131, 132]]
    assert research.cv2 is original
    def fail(*args):
        raise ValueError("test failure")
    research.compare = fail
    with pytest.raises(ValueError, match="test failure"):
        opencv_sift.compare_with_matches(research, None, None, 42)
    assert research.cv2 is original


@needs_research
def test_real_engine_view_preserves_scores_and_has_one_native_pair_per_inlier():
    engine = run_engine("opencv_sift.py")
    try:
        assert protocol.read_message(engine.stdout)[0]["ok"]
        _, parts = ask(engine, {"op": "extract"}, png(ridges(seed=5)))
        native = parts[0]
        regular, _ = ask(engine, {"op": "compare"}, [native, native])
        viewed, data = ask(engine, {"op": "compare", "view": True}, [native, native])
        assert viewed["score"] == regular["score"] > 0
        assert all(viewed[name] == regular[name] for name in ("status", "reason", "good"))
        points = np.frombuffer(data[0], "<f4").reshape(-1, 4)
        assert len(points) == viewed["matches"] == viewed["score"]
        assert np.isfinite(points).all() and (points >= 0).all() and (points < 1000).all()
        assert np.array_equal(points[:, :2], points[:, 2:])
        assert ask(engine, {"op": "compare"}, [native, native])[0]["score"] == regular["score"]
        empty = opencv_sift.template_bytes(np.empty((0, 2), np.float32), np.empty((0, 128), np.float32))
        failure, data = ask(engine, {"op": "compare", "view": True}, [empty, native])
        assert failure["status"] == "failure" and failure["matches"] == 0 and data == [b""]
    finally:
        engine.stdin.close()
        assert engine.wait(30) == 0
