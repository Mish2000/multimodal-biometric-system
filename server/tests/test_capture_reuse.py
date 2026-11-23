"""H59: an earlier capture compared again with another method, without the scanner."""

import json
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from mbs import fingerprint
from mbs import keys as keyring
from mbs.models import Attempt
from test_api import auth, register, sign_in
from test_fingerprint import enrol, finger, fp_client, placements, plan, script, service, subject_of, user
from test_identification import other_enrolled
from test_pore_verification import add_pore
from test_verification import enrolled


def post(client, token, path, body):
    response = client.post(path, json=body, headers=auth(token))
    assert response.status_code == 200, response.text
    return [json.loads(line) for line in response.iter_lines() if line]


def verify(client, token, algorithm, capture_from=None):
    body = {"finger": 7, "algorithm": algorithm}
    if capture_from is not None:
        body["capture_from"] = capture_from
    return post(client, token, "/api/fingerprint/verifications", body)


def identify(client, token, algorithm, capture_from=None):
    body = {"algorithm": algorithm}
    if capture_from is not None:
        body["capture_from"] = capture_from
    return post(client, token, "/api/fingerprint/identifications", body)


def attempts(databases):
    with Session(databases.biometric) as db:
        return {attempt.id: attempt for attempt in db.scalars(select(Attempt))}


def test_verification_compares_the_same_capture_with_another_method_without_the_scanner(
        fp_client, script, service, databases, keys):
    add_pore(service)
    token = enrolled(fp_client, script)
    subject = subject_of(fp_client, databases, keys, token)
    plan(script, finger("q60:A4"))
    first = verify(fp_client, token, "opencv-sift")[-1]
    assert first["capture"] == {"attempt_id": first["attempt_id"], "at": first["at"], "reused": False}

    # No scanner step is planned: a new scan would fail, and none is made.
    events = verify(fp_client, token, "pore-sift", first["attempt_id"])
    assert [e["type"] for e in events] == ["started", "captured", "comparing", "comparing", "comparing", "comparing",
                                            "saving", "verified"]
    assert events[0]["reused"] is True
    captured, second = events[1], events[-1]
    assert captured["checks"] == [] and captured["reused"] == {"attempt_id": first["attempt_id"], "at": first["at"]}
    assert (second["algorithm"], second["score"], second["accepted"]) == ("pore-sift", 45, True)
    assert second["capture"] == {"attempt_id": first["attempt_id"], "at": first["at"], "reused": True}

    # A capture compared again leads back to the attempt that took it.
    third = verify(fp_client, token, "opencv-sift", second["attempt_id"])[-1]
    assert (third["score"], third["capture"]["attempt_id"]) == (90, first["attempt_id"])

    rows = attempts(databases)
    taken = uuid.UUID(first["attempt_id"])
    assert rows[taken].capture_attempt_id is None
    for result in (second, third):
        row = rows[uuid.UUID(result["attempt_id"])]
        assert (row.capture_attempt_id, row.source, row.mode) == (taken, "device", "verify")
        # Each attempt keeps its own sealed copy of the capture.
        assert keyring.open_sealed(keys, keyring.PROBE, row.id.bytes + subject.bytes, row.probe) == b"FAKEPNG:q60:A4"
        with pytest.raises(keyring.KeysError):
            keyring.open_sealed(keys, keyring.PROBE, taken.bytes + subject.bytes, row.probe)


def test_a_capture_is_compared_again_only_by_its_owner_in_the_same_mode_and_within_ten_minutes(
        fp_client, script, service, databases, monkeypatch):
    add_pore(service)
    token = enrolled(fp_client, script)
    plan(script, finger("q60:A4"))
    first = verify(fp_client, token, "opencv-sift")[-1]
    saved = len(attempts(databases))

    def refused(events):
        assert [e["type"] for e in events] == ["failed"]
        return events[0]["error"]

    assert refused(verify(fp_client, token, "opencv-sift", first["attempt_id"])) == "same_method"
    assert refused(verify(fp_client, token, "pore-sift", str(uuid.uuid4()))) == "capture_unavailable"
    assert refused(identify(fp_client, token, "pore-sift", first["attempt_id"])) == "capture_unavailable"
    monkeypatch.setattr(fingerprint, "CAPTURE_REUSE", timedelta(seconds=-1))
    assert refused(verify(fp_client, token, "pore-sift", first["attempt_id"])) == "capture_expired"
    monkeypatch.undo()

    # Another person's capture is not theirs to compare.
    assert register(fp_client, username="dana", email="dana@example.org", national_id="000000018",
                    phone="0527654321").status_code == 201
    other = sign_in(fp_client, "dana")
    plan(script, *placements("q60:B1", "q60:B2", "q60:B3"))
    assert enrol(fp_client, other, 7)[-1]["type"] == "saved"
    assert refused(verify(fp_client, other, "pore-sift", first["attempt_id"])) == "capture_unavailable"

    # A new enrolment of the finger ends the capture's comparisons with the old one.
    plan(script, *placements("q60:A5", "q60:A6", "q60:A7"))
    assert enrol(fp_client, token, 7)[-1]["type"] == "saved"
    assert refused(verify(fp_client, token, "pore-sift", first["attempt_id"])) == "capture_unavailable"
    assert len(attempts(databases)) == saved


def test_identification_searches_the_same_capture_again_with_another_method(fp_client, script, service, databases, keys):
    add_pore(service)
    token = enrolled(fp_client, script)
    other_enrolled(fp_client, script)
    subject = subject_of(fp_client, databases, keys, token)
    plan(script, finger("q60:A4"))
    first = identify(fp_client, token, "opencv-sift")[-1]
    assert first["type"] == "identified" and first["capture"]["reused"] is False

    events = identify(fp_client, token, "pore-sift", first["attempt_id"])
    assert not any(e["type"] in ("place", "checking", "lift", "rejected") for e in events)
    second = events[-1]
    assert second["type"] == "identified" and second["algorithm"] == "pore-sift"
    assert second["capture"] == {"attempt_id": first["attempt_id"], "at": first["at"], "reused": True}
    row = attempts(databases)[uuid.UUID(second["attempt_id"])]
    assert (row.mode, row.capture_attempt_id) == ("identify", uuid.UUID(first["attempt_id"]))
    assert keyring.open_sealed(keys, keyring.PROBE, row.id.bytes + subject.bytes, row.probe) == b"FAKEPNG:q60:A4"
    # A verification's capture is not a search's, nor the other way round.
    assert [e["type"] for e in verify(fp_client, token, "pore-sift", first["attempt_id"])] == ["failed"]


def test_deleting_the_attempt_that_took_a_capture_keeps_the_later_one_with_its_own_copy(
        fp_client, script, service, databases, keys):
    add_pore(service)
    token = enrolled(fp_client, script)
    other_enrolled(fp_client, script)
    subject = subject_of(fp_client, databases, keys, token)
    plan(script, finger("q60:A4"))
    first = identify(fp_client, token, "opencv-sift")[-1]
    second = identify(fp_client, token, "pore-sift", first["attempt_id"])[-1]
    with Session(databases.biometric) as db, db.begin():
        db.execute(delete(Attempt).where(Attempt.id == uuid.UUID(first["attempt_id"])))
    row = attempts(databases)[uuid.UUID(second["attempt_id"])]
    assert row.capture_attempt_id is None
    assert keyring.open_sealed(keys, keyring.PROBE, row.id.bytes + subject.bytes, row.probe) == b"FAKEPNG:q60:A4"


def test_the_earlier_attempt_must_be_named_by_its_identifier(fp_client, script, service):
    token = user(fp_client)
    for path, body in (("/api/fingerprint/verifications", {"finger": 7, "capture_from": "the last one"}),
                       ("/api/fingerprint/identifications", {"capture_from": 7})):
        assert fp_client.post(path, json=body, headers=auth(token)).status_code == 422
