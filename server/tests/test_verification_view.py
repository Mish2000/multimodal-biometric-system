"""H18, H43: the caller's winning stored image and the pairs counted in its actual comparison."""

import base64
import struct

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from mbs import verification
from mbs.engines import EngineError
from mbs.models import Attempt, Enrolment, Sample

from test_fingerprint import finger, fp_client, plan, script, service, subject_of  # noqa: F401
from test_identification import other_enrolled
from test_verification import enrolled, verify


@pytest.mark.parametrize("scores,placement", [([80, 150, 100], 2), ([88, 88, 70], 1), ([0, 0, 0], 1)])
def test_view_uses_the_highest_comparison_and_the_earliest_tie(fp_client, script, service, databases, monkeypatch, scores, placement):
    token = enrolled(fp_client, script)
    original = service.sift.request
    def compare(header, parts):
        if header["op"] != "compare":
            return original(header, parts)
        assert header["view"] is True
        index = int(parts[1][-1:]) - 1
        value = scores[index]
        return {"status": "ok", "score": value, "matches": value}, [struct.pack("<4f", 10, 20, 30 + index, 40) * value]
    monkeypatch.setattr(service.sift, "request", compare)
    plan(script, finger("q60:A4"))
    result = verify(fp_client, token)[-1]
    assert result["type"] == "verified"
    view = result["match_view"]
    assert view["placement"] == placement and view["count"] == result["score"] == max(scores)
    assert base64.b64decode(view["reference_image"]) == f"FAKEPNG:q60:A{placement}".encode()
    pairs = base64.b64decode(view["pairs"])
    assert len(pairs) == max(scores) * 16
    assert all(pair == (10, 20, 29 + placement, 40) for pair in struct.iter_unpack("<4f", pairs))
    with Session(databases.biometric) as db:
        attempt = db.scalars(select(Attempt)).one()
        assert attempt.score == view["count"] and attempt.accepted == (view["count"] > 57)


def test_reference_image_cannot_be_opened_for_another_subject(fp_client, script, databases, keys):
    token = enrolled(fp_client, script)
    subject = subject_of(fp_client, databases, keys, token)
    other = other_enrolled(fp_client, script)
    other_subject = subject_of(fp_client, databases, keys, other)
    with Session(databases.biometric) as db:
        other_enrolment = db.scalar(select(Enrolment.id).where(Enrolment.subject_id == other_subject))
    with pytest.raises(verification.VerificationError, match="enrolment_changed"):
        verification._reference_image(databases, keys, subject, other_enrolment, 1)


def test_a_damaged_winning_capture_prevents_sending_an_illustration_or_saved_result(fp_client, script, databases):
    token = enrolled(fp_client, script)
    with Session(databases.biometric) as db, db.begin():
        db.scalar(select(Sample).where(Sample.placement == 1)).data = b"damaged"
    plan(script, finger("q60:A4"))
    result = verify(fp_client, token)[-1]
    assert result == {"type": "failed", "error": "stored_template_unreadable"}
    with Session(databases.biometric) as db:
        assert db.scalars(select(Attempt)).all() == []


@pytest.mark.parametrize("reply,parts", [
    ({"matches": 2}, [struct.pack("<4f", 10, 20, 30, 40)]),
    ({"matches": 1}, [struct.pack("<4f", 10, 20, float("nan"), 40)]),
    ({"matches": 1}, [struct.pack("<4f", 10, 20, 1000, 40)]),
])
def test_inconsistent_match_coordinates_are_refused(reply, parts):
    with pytest.raises(EngineError):
        verification._match_bytes(reply, parts, 1)
