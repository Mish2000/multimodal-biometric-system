"""A local check with the real engines (H33), skipped unless MBS_LIVE_CAPTURES names the second capture set's
folder (captures/live002, git-ignored) and this machine has the NFIQ 2 build and the research environment
(server/README.md). Only the scanner is replaced: it hands over the stored captures of one finger.

    MBS_LIVE_CAPTURES=../captures/live002 python -m pytest tests/test_fingerprint_live.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mbs import config as settings
from mbs.api import create_app
from mbs.engines import Engine, Scanner, conda_environment
from mbs.fingerprint import FingerprintService

from test_fingerprint import FAKES, LIFT, PYTHON, enrol, plan, script, user  # noqa: F401 (script is a fixture)
from test_verification import verify

LIVE = Path(os.environ["MBS_LIVE_CAPTURES"]) if os.environ.get("MBS_LIVE_CAPTURES") else None


@pytest.mark.skipif(LIVE is None, reason="MBS_LIVE_CAPTURES is not set")
def test_the_real_engines_enrol_a_finger_of_the_second_set(databases, keys, outbox, script):
    config, python = settings.load(), settings.research_python()
    engines, env = settings.REPOSITORY / "engines", conda_environment(python)
    service = FingerprintService(
        scanner=Scanner([PYTHON, str(FAKES / "fake_scanner.py"), "--script", str(script)]),
        quality=Engine("nfiq2", [str(python), "-I", str(engines / "nfiq2_quality.py"), str(config.nfiq2_bin)], env),
        sift=Engine("opencv-sift", [str(python), "-I", str(engines / "opencv_sift.py")], env),
    )
    files = sorted(LIVE.glob("live002_f07_p*.png"))  # the left index: its three pairs all pass in H10
    steps = []
    for file in files:
        steps += [{"wait": "finger", "file": str(file)}, LIFT]
    plan(script, *steps[:-1])
    try:
        with TestClient(create_app(databases, keys, outbox, service)) as client:
            token = user(client)
            events = enrol(client, token)
            plan(script, {"wait": "finger", "file": str(files[2])})
            matched = verify(client, token)[-1]
            assert matched["type"] == "verified" and matched["accepted"] is True
            assert [p["score"] for p in matched["comparisons"][:2]] == [384, 562]
            assert matched["score"] == max(p["score"] for p in matched["comparisons"])
            other = sorted(LIVE.glob("live002_f02_p*.png"))[0]
            plan(script, {"wait": "finger", "file": str(other)})
            different = verify(client, token)[-1]
            assert different["type"] == "verified" and different["accepted"] is False
    finally:
        service.close()
    saved = events[-1]
    assert saved["type"] == "saved", events[-1]
    # NFIQ 2 as NIST's tool scored these captures (local/nfiq2/measure-live.json), OpenCV SIFT as in H10.
    measured = json.loads((settings.REPOSITORY / "local" / "nfiq2" / "measure-live.json").read_text(encoding="utf-8"))
    official = {row["image"]: row["score"] for row in measured["per_image"]}
    assert [s["quality"] for s in saved["samples"]] == [official[f"live002_f07_p{i}"] for i in (1, 2, 3)]
    assert [p["score"] for p in saved["pairs"]] == [601, 384, 562]
    assert all(t["keypoints"] > 4000 and t["sealed"]["ciphertext"] == t["template_length"] for t in saved["templates"])
