"""H35: verification from the authenticated API to the migrated database and child-process protocols."""

import json
import struct
import time
import uuid

import anyio
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from mbs import fingerprint, verification
from mbs import keys as keyring
from mbs.models import Algorithm, Attempt, Enrolment, Template

from test_api import administrator, auth, error, register, sign_in
from test_fingerprint import (LIFT, enrol, finger, fp_client, plan, placements, script, service,
                              subject_of, user)  # noqa: F401 (shared fixtures)


def verify(client, token, position=7, algorithm=None):
    body = {"finger": position}
    if algorithm is not None:
        body["algorithm"] = algorithm
    response = client.post("/api/fingerprint/verifications", json=body, headers=auth(token))
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    return [json.loads(line) for line in response.iter_lines() if line]


def enrolled(client, script):
    token = user(client)
    plan(script, *placements("q60:A1", "q60:A2", "q60:A3"))
    assert enrol(client, token)[-1]["type"] == "saved"
    return token


@pytest.mark.parametrize("probe,accepted,score", [("q60:A4", True, 90), ("q60:B1", False, 5)])
def test_verification_saves_the_decision_and_a_sealed_probe(fp_client, script, databases, keys, probe, accepted, score):
    token = enrolled(fp_client, script)
    subject = subject_of(fp_client, databases, keys, token)
    plan(script, finger(probe))
    events = verify(fp_client, token)
    result = events[-1]
    assert [e["type"] for e in events] == ["started", "place", "checking", "captured", "comparing",
                                            "comparing", "comparing", "comparing", "saving", "verified"]
    assert (result["score"], result["accepted"], result["threshold"]) == (score, accepted, 57)
    assert [p["placement"] for p in result["comparisons"]] == [1, 2, 3]
    with Session(databases.biometric) as db:
        attempt = db.scalars(select(Attempt)).one()
        assert (attempt.mode, attempt.algorithm, attempt.source, attempt.subject_id) == ("verify", "opencv-sift", "device", subject)
        assert str(attempt.id) == result["attempt_id"] and attempt.score == score and attempt.accepted == accepted
        assert attempt.duration_ms >= 0 and attempt.threshold == 57
        assert keyring.open_sealed(keys, keyring.PROBE, attempt.id.bytes + subject.bytes, attempt.probe) == b"FAKEPNG:" + probe.encode()
        for row in (uuid.uuid4().bytes + subject.bytes, attempt.id.bytes + uuid.uuid4().bytes):
            with pytest.raises(keyring.KeysError):
                keyring.open_sealed(keys, keyring.PROBE, row, attempt.probe)


def test_highest_of_three_decides_and_equality_does_not_pass(fp_client, script, service, databases, monkeypatch):
    token = enrolled(fp_client, script)
    original = service.sift.request
    scores = iter([12, 57, 58, 12, 57, 57])

    def compare(header, parts):
        if header["op"] == "compare":
            score = next(scores)
            return {"status": "ok", "score": score, "matches": score}, [struct.pack("<4f", 10, 20, 30, 40) * score]
        return original(header, parts)

    monkeypatch.setattr(service.sift, "request", compare)
    for expected in (True, False):
        plan(script, finger("q60:A4"))
        assert verify(fp_client, token)[-1]["accepted"] is expected
    with Session(databases.biometric) as db:
        assert sorted(db.scalars(select(Attempt.score))) == [57, 58]


def test_quality_rejections_require_a_lift_and_never_create_attempts(fp_client, script, databases):
    token = enrolled(fp_client, script)
    plan(script, finger("q20:A4"), LIFT, finger("q255:A5"), LIFT, finger("q35:A6"))
    events = verify(fp_client, token)
    assert [e["score"] for e in events if e["type"] == "rejected"] == [20, None]
    assert [e["type"] for e in events].count("lift") == 2
    assert events[-1]["type"] == "verified"
    with Session(databases.biometric) as db:
        assert len(db.scalars(select(Attempt)).all()) == 1


def test_only_the_users_selected_current_finger_is_compared(fp_client, script, databases):
    token = enrolled(fp_client, script)
    assert verify(fp_client, token, 2)[-1] == {"type": "failed", "error": "not_enrolled"}
    register(fp_client, username="dana", email="dana@example.org", national_id="000000018", phone="052-765-4321")
    other = sign_in(fp_client, "dana")
    assert verify(fp_client, other)[-1]["error"] == "not_enrolled"
    plan(script, *placements("q60:B1", "q60:B2", "q60:B3"))
    enrol(fp_client, token)
    plan(script, finger("q60:A4"))
    assert verify(fp_client, token)[-1]["accepted"] is False


def test_verification_requires_a_user_session_and_valid_finger(fp_client, client, script, databases):
    assert error(fp_client.post("/api/fingerprint/verifications", json={"finger": 7})) == (401, "not_signed_in")
    admin = administrator(fp_client, databases)
    assert error(fp_client.post("/api/fingerprint/verifications", json={"finger": 7}, headers=auth(admin))) == (403, "forbidden")
    token = user(fp_client)
    for position in (0, 11, 1.5, "seven"):
        assert fp_client.post("/api/fingerprint/verifications", json={"finger": position}, headers=auth(token)).status_code == 422
    assert error(client.post("/api/fingerprint/verifications", json={"finger": 7}, headers=auth(token))) == (503, "fingerprint_unavailable")


def test_a_failed_scan_or_engine_never_creates_a_non_match(fp_client, script, databases, service, monkeypatch):
    token = enrolled(fp_client, script)
    plan(script, {"exit": 3})
    assert verify(fp_client, token)[-1]["error"] == "no_finger"
    from mbs.engines import EngineError

    def failed(*args):
        raise EngineError("test failure")

    monkeypatch.setattr(service.sift, "request", failed)
    plan(script, finger("q60:A4"))
    assert verify(fp_client, token)[-1]["error"] == "engine_unavailable"
    with Session(databases.biometric) as db:
        assert db.scalars(select(Attempt)).all() == []


def test_version_and_encryption_failures_are_reported_before_capture(fp_client, script, databases):
    token = enrolled(fp_client, script)
    with Session(databases.biometric) as db, db.begin():
        template = db.scalars(select(Template)).first()
        old = template.version
        template.version = "older"
    assert verify(fp_client, token)[-1]["error"] == "template_version_mismatch"
    with Session(databases.biometric) as db, db.begin():
        template = db.scalars(select(Template).where(Template.version == "older")).one()
        template.version, template.data = old, b"damaged"
    assert verify(fp_client, token)[-1]["error"] == "stored_template_unreadable"


@pytest.mark.parametrize("change", ["delete", "replace"])
def test_enrolment_changed_during_capture_prevents_saving(fp_client, script, service, databases, keys, change):
    token = enrolled(fp_client, script)
    subject = subject_of(fp_client, databases, keys, token)
    plan(script, finger("q60:A4"))

    async def run():
        events = []
        async for event in verification.verify(service, databases, keys, subject, 7):
            events.append(event)
            if event["type"] == "captured":
                if change == "delete":
                    fingerprint.delete_finger(databases, subject, 7)
                else:
                    from datetime import datetime, timezone
                    with Session(databases.biometric) as db, db.begin():
                        db.scalars(select(Enrolment)).one().replaced_at = datetime.now(timezone.utc)
        return events

    assert anyio.run(run)[-1] == {"type": "failed", "error": "enrolment_changed"}
    with Session(databases.biometric) as db:
        assert db.scalars(select(Attempt)).all() == []


def test_threshold_is_snapshotted_for_the_attempt(fp_client, script, service, databases, keys):
    token = enrolled(fp_client, script)
    subject = subject_of(fp_client, databases, keys, token)
    plan(script, finger("q60:A4"))

    async def run():
        events = []
        async for event in verification.verify(service, databases, keys, subject, 7):
            events.append(event)
            if event["type"] == "started":
                with Session(databases.biometric) as db, db.begin():
                    db.get(Algorithm, "opencv-sift").threshold = 100
        return events

    result = anyio.run(run)[-1]
    assert result["threshold"] == 57 and result["accepted"] is True


def test_deletion_erases_old_and_current_attempts_only_of_that_finger(fp_client, script, databases):
    token = enrolled(fp_client, script)
    for position in (7, 2, 7):
        plan(script, *placements("q60:A1", "q60:A2", "q60:A3"))
        enrol(fp_client, token, position)
        plan(script, finger("q60:A4"))
        verify(fp_client, token, position)
    assert fp_client.delete("/api/fingerprint/fingers/7", headers=auth(token)).status_code == 204
    with Session(databases.biometric) as db:
        remaining = db.scalars(select(Attempt)).one()
        assert db.get(Enrolment, remaining.enrolment_id).finger == 2


def test_cancelled_scanner_wait_stops_immediately_and_releases_the_lock(fp_client, script, databases, keys, service):
    token = enrolled(fp_client, script)
    subject = subject_of(fp_client, databases, keys, token)
    plan(script, {"hang": True})

    async def consume():
        async for _ in verification.verify(service, databases, keys, subject, 7):
            pass

    async def cancel_wait():
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(consume)
            with anyio.fail_after(10):
                while json.loads(script.read_text(encoding="utf-8")):
                    await anyio.sleep(0.02)
            tasks.cancel_scope.cancel()

    started = time.monotonic()
    anyio.run(cancel_wait)
    assert time.monotonic() - started < 10
    assert not service.scanner_lock.locked()
    with Session(databases.biometric) as db:
        assert db.scalars(select(Attempt)).all() == []
    plan(script, finger("q60:A4"))
    assert verify(fp_client, token)[-1]["type"] == "verified"


def test_a_research_comparison_failure_scores_zero(fp_client, script, databases, service, monkeypatch):
    token = enrolled(fp_client, script)
    original = service.sift.request

    def insufficient(header, parts):
        if header["op"] == "compare":
            return {"status": "failure", "reason": "insufficient_features", "score": None, "matches": 0}, [b""]
        return original(header, parts)

    monkeypatch.setattr(service.sift, "request", insufficient)
    plan(script, finger("q60:A4"))
    result = verify(fp_client, token)[-1]
    assert result["type"] == "verified" and result["score"] == 0 and result["accepted"] is False
    assert all(not pair["computed"] for pair in result["comparisons"])


def test_storage_failure_is_not_reported_as_a_completed_result(fp_client, script, databases, monkeypatch):
    token = enrolled(fp_client, script)

    def unavailable(*args):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(verification, "_save", unavailable)
    plan(script, finger("q60:A4"))
    assert verify(fp_client, token)[-1] == {"type": "failed", "error": "unexpected"}
    with Session(databases.biometric) as db:
        assert db.scalars(select(Attempt)).all() == []


def test_rejected_captures_are_bounded_and_enrolment_shares_the_scanner(fp_client, script, service, databases):
    token = enrolled(fp_client, script)
    with service.scanner_lock:
        assert verify(fp_client, token)[-1]["error"] == "scanner_busy"
        assert enrol(fp_client, token)[-1]["error"] == "scanner_busy"
    plan(script, *placements(*["q20:A4"] * fingerprint.MOST_CAPTURES))
    events = verify(fp_client, token)
    assert events[-1]["error"] == "too_many_captures"
    assert len([event for event in events if event["type"] == "rejected"]) == fingerprint.MOST_CAPTURES
    with Session(databases.biometric) as db:
        assert db.scalars(select(Attempt)).all() == []


def test_upgrade_preserves_existing_enrolments_and_their_placement_numbers(fp_client, script, databases):
    from alembic import command
    from alembic.config import Config
    from mbs.db import MIGRATIONS, migrate

    migration = Config()
    migration.set_main_option("script_location", str(MIGRATIONS / "biometric"))
    migration.attributes["engine"] = databases.biometric
    command.downgrade(migration, "biometric_0002")
    token = user(fp_client)
    plan(script, *placements("q60:A1", "q60:A2", "q60:B1", "q60:A3"))
    saved = enrol(fp_client, token)[-1]
    migrate(databases)
    plan(script, finger("q60:A4"))
    result = verify(fp_client, token)[-1]
    assert result["accepted"] is True
    assert [comparison["placement"] for comparison in result["comparisons"]] == [1, 2, 4]
    with Session(databases.biometric) as db:
        assert str(db.scalars(select(Attempt)).one().enrolment_id) == saved["enrolment"]["id"]


def test_disconnect_while_sending_progress_closes_the_flow(fp_client, script, databases, keys, service):
    from mbs.routes.fingerprints import FingerprintResponse

    token = enrolled(fp_client, script)
    subject = subject_of(fp_client, databases, keys, token)

    async def disconnected_send(message):
        if message["type"] == "http.response.body":
            raise OSError("client disconnected")

    async def run():
        response = FingerprintResponse(verification.verify(service, databases, keys, subject, 7))
        with pytest.raises(OSError):
            await response.stream_response(disconnected_send)

    anyio.run(run)
    assert not service.scanner_lock.locked()
