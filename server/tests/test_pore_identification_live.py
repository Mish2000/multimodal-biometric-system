"""H42: gallery backfill matches H10 native templates and search matches serial research scores."""

import io
import os
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mbs import config as settings, fingerprint, identification
from mbs.api import create_app
from mbs.engines import Scanner

from test_api import register, sign_in
from test_fingerprint import FAKES, LIFT, PYTHON, enrol, plan, script, subject_of, user  # noqa: F401
from test_identification import identify

LIVE = Path(os.environ["MBS_LIVE_CAPTURES"]) if os.environ.get("MBS_LIVE_CAPTURES") else None


@pytest.mark.skipif(LIVE is None, reason="MBS_LIVE_CAPTURES is not set")
def test_real_pore_gallery_templates_equal_h10_and_rank_like_serial_comparison(databases, keys, outbox, script):
    service, reason = fingerprint.from_config(settings.load())
    assert service is not None, reason
    service.scanner = Scanner([PYTHON, str(FAKES / "fake_scanner.py"), "--script", str(script)])
    pore, learned = service.pore, service.learned
    service.pore = service.learned = None

    def captures(position):
        return sorted(LIVE.glob(f"live002_f{position:02d}_p*.png"))

    def prepare(position):
        steps = []
        for file in captures(position):
            steps.extend([{"wait": "finger", "file": str(file)}, LIFT])
        plan(script, *steps[:-1])

    try:
        with TestClient(base_url="http://127.0.0.1", app=create_app(databases, keys, outbox, service)) as client:
            token = user(client)
            prepare(7)
            assert enrol(client, token, 7)[-1]["type"] == "saved"
            assert register(client, username="dana", email="dana@example.org", national_id="000000018", phone="0527654321").status_code == 201
            other = sign_in(client, "dana")
            prepare(2)
            assert enrol(client, other, 2)[-1]["type"] == "saved"
            subject = subject_of(client, databases, keys, token)
            service.pore, service.learned = pore, learned

            for algorithm, threshold in (("pore-sift", 37), ("learned-pore", 21)):
                plan(script, {"wait": "finger", "file": str(captures(7)[2])})
                first = identify(client, token, algorithm=algorithm)
                assert first[-1]["type"] == "identified" and first[-1]["accepted"] and first[-1]["candidates"][0]["own"]
                assert [event["completed"] for event in first if event["type"] == "preparing_templates"] == list(range(7))
                assert first[-1]["threshold"] == threshold and first[-1]["threshold_provisional"]
                gallery = identification._load_gallery(databases, keys, subject, algorithm)
                candidates = {candidate.id: candidate for candidate in gallery.candidates}
                templates = {}
                for reference in gallery.references:
                    candidate = candidates[reference.enrolment_id]
                    native = identification._open_reference(databases, keys, candidate, reference, algorithm)
                    image_id = f"live002_f{candidate.finger:02d}_p{reference.placement}"
                    features = LIVE / "evaluation" / "features"
                    if algorithm == "pore-sift":
                        with zipfile.ZipFile(io.BytesIO(native)) as actual, zipfile.ZipFile(features / algorithm / f"{image_id}.npz") as expected:
                            assert actual.namelist() == expected.namelist()
                            assert all(actual.read(name) == expected.read(name) for name in actual.namelist())
                    else:
                        assert native == (features / "learned-pore-repeat" / f"{image_id}.npy").read_bytes()
                    templates[reference.sample_id] = native
                engine = fingerprint.engine_for(service, algorithm)
                for position, own in ((7, True), (2, False)):
                    probe = fingerprint.extract_native(service, algorithm, captures(position)[2].read_bytes())
                    expected_scores = dict.fromkeys(candidates, 0)
                    for reference in gallery.references:
                        reply, _ = engine.request({"op": "compare"}, [probe, templates[reference.sample_id]])
                        expected_scores[reference.enrolment_id] = max(expected_scores[reference.enrolment_id], fingerprint.comparison_score(reply))
                    plan(script, {"wait": "finger", "file": str(captures(position)[2])})
                    events = identify(client, token, algorithm=algorithm)
                    result = events[-1]
                    assert result["type"] == "identified" and result["accepted"] and result["candidates"][0]["own"] is own
                    assert not any(event["type"] == "preparing_templates" for event in events)
                    assert [candidate["score"] for candidate in result["candidates"]] == sorted(expected_scores.values(), reverse=True)
                plan(script, {"wait": "finger", "file": str(captures(4)[0])})
                assert identify(client, token, algorithm=algorithm)[-1]["accepted"] is False
    finally:
        service.close()
