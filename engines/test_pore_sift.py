"""H38: the memory-only Pore SIFT engine must equal the unchanged file-based research worker."""

import io
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from test_engines import ENGINES, SYSTEM_ROOT, ask, png, research_available, research_link, ridges
import pore_sift
import protocol


@pytest.mark.skipif(not research_available(), reason="the pinned research checkout is unavailable")
def test_pore_templates_and_scores_equal_the_research_worker(tmp_path):
    settings = pore_sift.verified_settings()
    python = Path(settings["python"])
    if not python.exists():
        pytest.skip("the Pore SIFT research environment is unavailable")
    images, templates = [], []
    features = tmp_path / "features"
    features.mkdir()
    for index in (1, 2):
        path = tmp_path / f"synthetic-{index}.png"
        path.write_bytes(png(ridges(seed=index)))
        images.append({"image_id": str(index), "path": str(path)})
    job = tmp_path / "job.json"
    job.write_text(json.dumps({**settings, "images": images, "threads": 1, "features_dir": str(features),
                               "out_path": str(tmp_path / "result.json")}), encoding="utf-8")
    worker = Path(settings["repository"]) / "src" / "fpl3" / "algorithms" / "pore_sift_worker.py"
    env = research_link.environment(python)
    subprocess.run([str(python), "-B", str(worker), "extract", "--job", str(job)], env=env, check=True,
                   capture_output=True, timeout=90)
    engine = subprocess.Popen([str(python), "-I", "-B", str(ENGINES / "pore_sift.py"), sys.executable],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=None, env=env, cwd=SYSTEM_ROOT)
    try:
        ready, _ = protocol.read_message(engine.stdout)
        assert ready["ok"] and ready["algorithm"] == "pore-sift" and ready["version"] == settings["version"]
        for image in images:
            result, parts = ask(engine, {"op": "extract"}, Path(image["path"]).read_bytes())
            assert result["ok"]
            actual_points, actual_descriptors = pore_sift.from_template(parts[0])
            with np.load(features / f"{image['image_id']}.npz") as expected:
                assert np.array_equal(actual_points, expected["points"])
                assert np.array_equal(actual_descriptors, expected["descriptors"])
            # H39: detection alone returns the exact same points for Pore CNN.
            detected, coordinate_parts = ask(engine, {"op": "detect"}, Path(image["path"]).read_bytes())
            with np.load(io.BytesIO(coordinate_parts[0]), allow_pickle=False) as coordinates:
                assert detected["ok"] and np.array_equal(coordinates["points"], actual_points)
            templates.append(parts[0])
        # The comparison worker reads the same features and calls the pinned basic matcher.
        compare_job = {**settings, "pairs": [{"pair_id": "pair", "probe_image_id": "2", "reference_image_id": "1"}],
                       "threads": 1, "features_dir": str(features), "out_path": str(tmp_path / "scores.json")}
        job.write_text(json.dumps(compare_job), encoding="utf-8")
        subprocess.run([str(python), "-B", str(worker), "compare", "--job", str(job)], env=env, check=True,
                       capture_output=True, timeout=90)
        expected = json.loads((tmp_path / "scores.json").read_text())[0]["score"]
        assert ask(engine, {"op": "compare"}, [templates[1], templates[0]])[0]["score"] == expected
        assert not (SYSTEM_ROOT / "memory").exists()
    finally:
        engine.stdin.close()
        assert engine.wait(30) == 0
