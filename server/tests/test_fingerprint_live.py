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
@pytest.mark.parametrize("pore_at_enrolment", [False, True])
def test_the_real_engines_enrol_a_finger_of_the_second_set(databases, keys, outbox, script, pore_at_enrolment):
    config, python = settings.load(), settings.research_python()
    engines, env = settings.REPOSITORY / "engines", conda_environment(python)
    service = FingerprintService(
        scanner=Scanner([PYTHON, str(FAKES / "fake_scanner.py"), "--script", str(script)]),
        quality=Engine("nfiq2", [str(python), "-I", str(engines / "nfiq2_quality.py"), str(config.nfiq2_bin)], env),
        sift=Engine("opencv-sift", [str(python), "-I", str(engines / "opencv_sift.py")], env),
    )
    pore_python = settings.pore_python()
    pore = Engine("pore-sift", [str(pore_python), "-I", "-B", str(engines / "pore_sift.py"), str(python)],
                  conda_environment(pore_python))
    learned_python = settings.learned_python()
    learned = Engine("learned-pore", [str(learned_python), "-I", "-B", str(engines / "learned_pore.py")],
                     conda_environment(learned_python))
    if pore_at_enrolment:
        service.pore = pore
        service.learned = learned
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
            service.pore = pore
            plan(script, {"wait": "finger", "file": str(files[2])})
            pore_events = verify(client, token, algorithm="pore-sift")
            pore_result = pore_events[-1]
            assert pore_result["type"] == "verified" and pore_result["accepted"] is True
            prepared = [event for event in pore_events if event["type"] == "preparing_templates"]
            assert bool(prepared) is not pore_at_enrolment
            expected = json.loads((LIVE / "evaluation" / "pore-sift.json").read_text())
            expected_scores = {row["pair_id"]: row["score"] for row in expected["comparisons"]}
            assert [pair["score"] for pair in pore_result["comparisons"][:2]] == [
                expected_scores[f"A:live002_f07_p3|live002_f07_p{i}"] for i in (1, 2)]
            plan(script, {"wait": "finger", "file": str(other)})
            assert verify(client, token, algorithm="pore-sift")[-1]["accepted"] is False
            service.learned = learned
            plan(script, {"wait": "finger", "file": str(files[2])})
            learned_events = verify(client, token, algorithm="learned-pore")
            learned_result = learned_events[-1]
            assert learned_result["type"] == "verified" and learned_result["accepted"] is True
            assert learned_result["threshold"] == 21 and learned_result["threshold_provisional"]
            assert bool([e for e in learned_events if e["type"] == "preparing_templates"]) is not pore_at_enrolment
            learned_expected = json.loads((LIVE / "evaluation" / "learned-pore-repeat.json").read_text())
            learned_scores = {row["pair_id"]: row["score"] for row in learned_expected["comparisons"]}
            assert [pair["score"] for pair in learned_result["comparisons"][:2]] == [
                learned_scores[f"A:live002_f07_p3|live002_f07_p{i}"] for i in (1, 2)]
            plan(script, {"wait": "finger", "file": str(other)})
            assert verify(client, token, algorithm="learned-pore")[-1]["accepted"] is False
    finally:
        service.close()
    saved = events[-1]
    assert saved["type"] == "saved", events[-1]
    # NFIQ 2 as NIST's tool scored these captures (local/nfiq2/measure-live.json), OpenCV SIFT as in H10.
    measured = json.loads((settings.REPOSITORY / "local" / "nfiq2" / "measure-live.json").read_text(encoding="utf-8"))
    official = {row["image"]: row["score"] for row in measured["per_image"]}
    assert [s["quality"] for s in saved["samples"]] == [official[f"live002_f07_p{i}"] for i in (1, 2, 3)]
    assert [p["score"] for p in saved["pairs"]] == [601, 384, 562]
    if pore_at_enrolment:
        assert {m["algorithm"] for m in saved["method_comparisons"]} == {"opencv-sift", "pore-sift", "learned-pore"}
        for method in saved["method_comparisons"]:
            if method["algorithm"] == "opencv-sift":
                continue
            expected = expected_scores if method["algorithm"] == "pore-sift" else learned_scores
            assert [p["score"] for p in method["pairs"]] == [
                expected[f"A:live002_f07_p{b}|live002_f07_p{a}"] for a, b in ((1, 2), (1, 3), (2, 3))]
        assert saved["pending_methods"] == []
    assert all(t["keypoints"] > 4000 and t["sealed"]["ciphertext"] == t["template_length"] for t in saved["templates"])
