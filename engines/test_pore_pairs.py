"""H44: pore illustrations show exactly the pairs that the pinned pore comparisons count, at native pores."""

import io
import subprocess
import sys
import types
from pathlib import Path

import numpy as np
import pytest

from test_engines import ENGINES, SYSTEM_ROOT, ask, png, research_available, research_link, ridges
import pore_sift
import protocol


def pore_method(found, observed):
    """A Pore SIFT adapter around stand-ins with the upstream call shapes: basic counts find_correspondences."""
    def find_correspondences(descs1, descs2, thr=None):
        observed.append((len(descs1), len(descs2), thr))
        return found

    utils = types.SimpleNamespace(find_correspondences=find_correspondences)
    matching = types.SimpleNamespace(utils=utils)

    def basic(descs1, descs2, pts1=None, pts2=None, thr=None):
        if len(descs1) == 0 or len(descs2) == 0:
            return 0
        return len(matching.utils.find_correspondences(descs1, descs2, thr=thr))

    matching.basic = basic
    method = object.__new__(pore_sift.PoreSift)
    method.up = types.SimpleNamespace(matching=matching)
    method.worker = types.SimpleNamespace(RATIO=0.7)
    return method, utils


def template(points):
    return pore_sift.template_bytes(points, np.zeros((len(points), 128), np.float32))


def test_pore_sift_pairs_are_the_counted_correspondences_as_x_and_y():
    observed = []
    method, utils = pore_method([(1, 0, 0.5), (0, 2, 0.25)], observed)
    probe, reference = template([[10, 20], [30, 40]]), template([[50, 60], [70, 80], [90, 100]])
    score, data = method.compare_with_pairs(probe, reference)
    # Upstream tuples are (probe index, reference index, distance); stored points are (row, column).
    assert score == 2 and observed == [(2, 3, 0.7)] and method.up.matching.utils is utils
    assert np.frombuffer(data, "<f4").reshape(-1, 4).tolist() == [[40, 30, 60, 50], [20, 10, 100, 90]]
    assert method.compare(probe, reference) == 2


def test_pore_sift_capture_restores_the_module_and_refuses_disagreement():
    method, utils = pore_method([(0, 0, 0.1)], [])
    assert method.compare_with_pairs(template([]), template([[1, 2]])) == (0, b"")
    original_basic = method.up.matching.basic
    method.up.matching.basic = lambda *args, **kwargs: original_basic(*args, **kwargs) + 1
    with pytest.raises(ValueError, match="do not agree"):
        method.compare_with_pairs(template([[1, 2]]), template([[3, 4]]))
    assert method.up.matching.utils is utils

    def fail(*args, **kwargs):
        raise RuntimeError("test failure")

    method.up.matching.basic = fail
    with pytest.raises(RuntimeError, match="test failure"):
        method.compare_with_pairs(template([[1, 2]]), template([[3, 4]]))
    assert method.up.matching.utils is utils


@pytest.mark.skipif(not research_available(), reason="the pinned research checkout is unavailable")
def test_real_pore_sift_view_keeps_the_score_and_maps_each_pore_to_itself():
    settings = pore_sift.verified_settings()
    python = Path(settings["python"])
    if not python.exists():
        pytest.skip("the Pore SIFT research environment is unavailable")
    engine = subprocess.Popen([str(python), "-I", "-B", str(ENGINES / "pore_sift.py"), sys.executable],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=None,
                              env=research_link.environment(python), cwd=SYSTEM_ROOT)
    try:
        assert protocol.read_message(engine.stdout)[0]["ok"]
        templates = [ask(engine, {"op": "extract"}, png(ridges(seed=seed)))[1][0] for seed in (3, 4)]
        points, _ = pore_sift.from_template(templates[0])
        regular, _ = ask(engine, {"op": "compare"}, [templates[0], templates[0]])
        viewed, data = ask(engine, {"op": "compare", "view": True}, [templates[0], templates[0]])
        pairs = np.frombuffer(data[0], "<f4").reshape(-1, 4)
        assert viewed["score"] == regular["score"] == viewed["matches"] == len(pairs) > 0
        assert np.array_equal(pairs[:, :2], pairs[:, 2:])
        assert {tuple(row) for row in pairs[:, :2].tolist()} <= {(float(c), float(r)) for r, c in points.tolist()}
        other, _ = ask(engine, {"op": "compare"}, [templates[1], templates[0]])
        viewed, data = ask(engine, {"op": "compare", "view": True}, [templates[1], templates[0]])
        assert viewed["score"] == other["score"] == len(data[0]) // 16
    finally:
        engine.stdin.close()
        assert engine.wait(30) == 0


@pytest.mark.skipif(not research_available(), reason="the pinned research checkout is unavailable")
def test_real_learned_view_keeps_the_score_at_the_described_pores():
    link = research_link.load()
    if not link.gpu_python.exists():
        pytest.skip("Pore CNN runtime is unavailable")
    # Rows and columns differ, so a swapped axis cannot pass; the first and last two windows do not fit.
    coordinates = np.array([[0, 500], [120, 700], [300, 200], [640, 410], [983, 16], [999, 999]], np.int32)
    described = {(700.0, 120.0), (200.0, 300.0), (410.0, 640.0), (16.0, 983.0)}
    buffer = io.BytesIO()
    np.savez(buffer, points=coordinates)
    pores = buffer.getvalue()
    engine = subprocess.Popen([str(link.gpu_python), "-I", "-B", str(ENGINES / "learned_pore.py")],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=None,
                              env=research_link.environment(link.gpu_python))
    try:
        assert protocol.read_message(engine.stdout)[0]["ok"]
        templates = [ask(engine, {"op": "extract"}, [png(ridges(seed=seed)), pores])[1][0] for seed in (1, 2)]
        regular, _ = ask(engine, {"op": "compare"}, [templates[0], templates[0]])
        viewed, data = ask(engine, {"op": "compare", "view": True}, [templates[0], templates[0], pores, pores])
        pairs = np.frombuffer(data[0], "<f4").reshape(-1, 4)
        assert viewed["score"] == regular["score"] == viewed["matches"] == len(pairs) == 4
        assert np.array_equal(pairs[:, :2], pairs[:, 2:]) and {tuple(row) for row in pairs[:, :2].tolist()} == described
        other, _ = ask(engine, {"op": "compare"}, [templates[1], templates[0]])
        viewed, data = ask(engine, {"op": "compare", "view": True}, [templates[1], templates[0], pores, pores])
        assert viewed["score"] == other["score"] == len(data[0]) // 16
        fewer = io.BytesIO()
        np.savez(fewer, points=coordinates[1:3])
        assert ask(engine, {"op": "compare", "view": True}, [templates[0], templates[0], fewer.getvalue(), pores])[0]["ok"] is False
        assert ask(engine, {"op": "compare", "view": True}, [templates[0], templates[0]])[0]["ok"] is False
    finally:
        engine.stdin.close()
        assert engine.wait(30) == 0
