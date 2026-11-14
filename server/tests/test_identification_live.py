"""H41: local 1:N checks with real engines and existing captures, without operating the scanner."""

import os
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
def test_real_search_equals_serial_comparisons_of_the_same_native_templates(databases, keys, outbox, script):
    service, reason = fingerprint.from_config(settings.load())
    assert service is not None, reason
    service.scanner = Scanner([PYTHON, str(FAKES / "fake_scanner.py"), "--script", str(script)])
    # Old enrolments with OpenCV SIFT templates remain searchable without a backfill.
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
            gallery = identification._load_gallery(databases, keys, subject)
            candidates = {candidate.id: candidate for candidate in gallery.candidates}
            for position, own in ((7, True), (2, False)):
                png = captures(position)[2].read_bytes()
                probe = fingerprint.extract_native(service, fingerprint.OPENCV_SIFT, png)
                expected = dict.fromkeys(candidates, 0)
                for reference in gallery.references:
                    native = identification._open_reference(databases, keys, candidates[reference.enrolment_id], reference)
                    reply, _ = service.sift.request({"op": "compare"}, [probe, native])
                    expected[reference.enrolment_id] = max(expected[reference.enrolment_id], fingerprint.comparison_score(reply))
                plan(script, {"wait": "finger", "file": str(captures(position)[2])})
                result = identify(client, token)[-1]
                assert result["type"] == "identified" and result["accepted"] is True
                assert result["gallery_size"] == 6 and result["candidates"][0]["own"] is own
                assert [candidate["score"] for candidate in result["candidates"]] == sorted(expected.values(), reverse=True)
            plan(script, {"wait": "finger", "file": str(captures(4)[0])})
            assert identify(client, token)[-1]["accepted"] is False
    finally:
        service.close()
