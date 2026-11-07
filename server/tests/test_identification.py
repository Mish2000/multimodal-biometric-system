"""H41: 1:N gallery membership, privacy, cancellation and persistence through the real API and database."""

import json
import threading
import time
import uuid
from datetime import datetime, timezone

import anyio
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from mbs import fingerprint, identification, verification
from mbs import keys as keyring
from mbs.engines import EngineError
from mbs.models import Account, Algorithm, Attempt, Enrolment, IdentityLink, Sample, Template

from test_api import administrator, auth, error, register, sign_in
from test_fingerprint import (LIFT, enrol, finger, fp_client, plan, placements, script, service,
                              subject_of, user)  # noqa: F401
from test_verification import enrolled


def identify(client, token, **body):
    response = client.post("/api/fingerprint/identifications", json=body, headers=auth(token))
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return [json.loads(line) for line in response.iter_lines() if line]


def other_enrolled(client, script, label="B", position=2):
    assert register(client, username="dana", email="dana@example.org", national_id="000000018", phone="0527654321").status_code == 201
    token = sign_in(client, "dana")
    plan(script, *placements(*(f"q60:{label}{n}" for n in (1, 2, 3))))
    assert enrol(client, token, position)[-1]["type"] == "saved"
    return token


@pytest.mark.parametrize("probe,accepted,own", [("A4", True, True), ("B4", True, False), ("C4", False, None)])
def test_identification_ranks_fingers_and_seals_the_probe_without_disclosing_other_people(
        fp_client, script, service, databases, keys, probe, accepted, own):
    token = enrolled(fp_client, script)
    other_enrolled(fp_client, script)
    subject = subject_of(fp_client, databases, keys, token)
    plan(script, finger(f"q60:{probe}"))
    events = identify(fp_client, token)
    result = events[-1]
    assert result["type"] == "identified" and result["accepted"] is accepted
    assert result["gallery_size"] == 6 and result["enrolments"] == 2
    assert [c["score"] for c in result["candidates"]] == ([90, 5] if accepted else [5, 5])
    if own is not None:
        assert result["candidates"][0]["own"] is own
    assert all(c["finger"] is None for c in result["candidates"] if not c["own"])
    assert all(set(c) == {"rank", "own", "finger", "score", "accepted"} for c in result["candidates"])
    assert [e["completed"] for e in events if e["type"] == "searching"] == [0, 4, 6]
    with Session(databases.biometric) as db:
        attempt = db.scalars(select(Attempt)).one()
        assert (attempt.mode, attempt.algorithm, attempt.subject_id, attempt.gallery_size) == ("identify", "opencv-sift", subject, 6)
        assert attempt.enrolment_id is None and attempt.top_enrolment_id is not None
        assert attempt.score == result["score"] and attempt.threshold == 57 and attempt.duration_ms >= 0
        assert keyring.open_sealed(keys, keyring.PROBE, attempt.id.bytes + subject.bytes, attempt.probe) == f"FAKEPNG:q60:{probe}".encode()
        with pytest.raises(keyring.KeysError):
            keyring.open_sealed(keys, keyring.PROBE, attempt.id.bytes + uuid.uuid4().bytes, attempt.probe)
        wire = json.dumps(events)
        assert "dana" not in wire and "example.org" not in wire
        for row in db.scalars(select(Enrolment)):
            assert str(row.id) not in wire and str(row.subject_id) not in wire


def test_role_input_and_own_enrolment_are_enforced_before_capture(fp_client, client, script, databases):
    route = "/api/fingerprint/identifications"
    assert error(fp_client.post(route, json={})) == (401, "not_signed_in")
    admin = administrator(fp_client, databases)
    assert error(fp_client.post(route, json={}, headers=auth(admin))) == (403, "forbidden")
    token = user(fp_client)
    other_enrolled(fp_client, script)
    plan(script, finger("q60:A4"))
    assert identify(fp_client, token)[-1]["error"] == "not_enrolled"
    assert len(json.loads(script.read_text())) == 1
    for body in ({"algorithm": "pore-sift"}, {"algorithm": "learned-pore"}, {"finger": 7}, {"subject": str(uuid.uuid4())}):
        assert fp_client.post(route, json=body, headers=auth(token)).status_code == 422
    assert error(client.post(route, json={}, headers=auth(token))) == (503, "fingerprint_unavailable")


def test_gallery_uses_only_current_enrolments_of_active_accounts(fp_client, script, databases):
    token = enrolled(fp_client, script)
    other_enrolled(fp_client, script)
    plan(script, *placements("q60:C1", "q60:C2", "q60:C3"))
    enrol(fp_client, token, 7)
    with Session(databases.accounts) as db, db.begin():
        db.scalar(select(Account).where(Account.username == "dana")).status = "disabled"
    plan(script, finger("q60:B4"))
    result = identify(fp_client, token)[-1]
    assert result["gallery_size"] == 3 and result["enrolments"] == 1 and result["score"] == 5
    plan(script, finger("q60:A4"))
    assert identify(fp_client, token)[-1]["accepted"] is False


def test_probe_is_extracted_once_and_reference_comparisons_run_in_parallel(fp_client, script, service, databases, monkeypatch):
    token = enrolled(fp_client, script)
    other_enrolled(fp_client, script)
    with Session(databases.biometric) as db, db.begin():
        for sample in db.scalars(select(Sample)):
            sample.data = b"unavailable raw capture"  # identification needs only the stored templates
    state = {"active": 0, "peak": 0, "extract": 0, "compared": 0}
    guard = threading.Lock()
    for engine in service.search_engines():
        original = engine.request
        def observe(header, parts, request=original):
            with guard:
                if header["op"] == "extract":
                    state["extract"] += 1
                else:
                    state["active"] += 1
                    state["peak"] = max(state["peak"], state["active"])
            try:
                if header["op"] == "compare":
                    time.sleep(0.07)
                    with guard:
                        state["compared"] += 1
                return request(header, parts)
            finally:
                if header["op"] == "compare":
                    with guard:
                        state["active"] -= 1
        monkeypatch.setattr(engine, "request", observe)
    plan(script, finger("q60:A4"))
    assert identify(fp_client, token)[-1]["accepted"] is True
    assert state["extract"] == 1 and state["compared"] == 6 and 1 < state["peak"] <= 4


@pytest.mark.parametrize("highest,accepted", [(57, False), (58, True)])
def test_highest_score_and_strict_threshold(fp_client, script, service, monkeypatch, highest, accepted):
    token = enrolled(fp_client, script)
    for engine in service.search_engines():
        original = engine.request
        def scores(header, parts, request=original):
            if header["op"] == "compare":
                return {"status": "ok", "score": highest if parts[1].endswith(b"A2") else 1}, []
            return request(header, parts)
        monkeypatch.setattr(engine, "request", scores)
    plan(script, finger("q60:A4"))
    result = identify(fp_client, token)[-1]
    assert result["score"] == highest and result["accepted"] is accepted and result["threshold"] == 57


def test_equal_leaders_are_reported_with_deterministic_ranks(fp_client, script, databases):
    token = enrolled(fp_client, script)
    other_enrolled(fp_client, script, label="A")
    results = []
    for _ in range(2):
        plan(script, finger("q60:A4"))
        results.append(identify(fp_client, token)[-1])
    assert results[0]["tied_leaders"] == 2 and results[0]["accepted"] is True
    assert results[0]["candidates"] == results[1]["candidates"]
    with Session(databases.biometric) as db:
        assert len(set(db.scalars(select(Attempt.top_enrolment_id)))) == 1


@pytest.mark.parametrize("change", ["delete", "replace", "disable", "template"])
def test_gallery_changes_before_save_invalidate_the_whole_result(fp_client, script, service, databases, keys, change):
    token = enrolled(fp_client, script)
    other_token = other_enrolled(fp_client, script)
    subject = subject_of(fp_client, databases, keys, token)
    other_subject = subject_of(fp_client, databases, keys, other_token)
    plan(script, finger("q60:A4"))
    async def run():
        events = []
        async for event in identification.identify(service, databases, keys, subject):
            events.append(event)
            if event["type"] == "saving":
                if change == "delete":
                    fingerprint.delete_finger(databases, other_subject, 2)
                elif change == "disable":
                    with Session(databases.accounts) as db, db.begin():
                        db.scalar(select(Account).where(Account.username == "dana")).status = "disabled"
                else:
                    with Session(databases.biometric) as db, db.begin():
                        row = db.scalar(select(Enrolment).where(Enrolment.subject_id == other_subject))
                        if change == "replace":
                            row.replaced_at = datetime.now(timezone.utc)
                        else:
                            db.scalars(select(Template).join(Sample).where(Sample.enrolment_id == row.id)).first().version = "changed"
        return events
    assert anyio.run(run)[-1] == {"type": "failed", "error": "gallery_changed"}
    with Session(databases.biometric) as db:
        assert db.scalars(select(Attempt)).all() == []


def test_a_new_enrolment_and_threshold_change_do_not_change_the_snapshot(fp_client, script, service, databases, keys):
    token = enrolled(fp_client, script)
    subject = subject_of(fp_client, databases, keys, token)
    plan(script, finger("q60:A4"))
    async def run():
        events = []
        async for event in identification.identify(service, databases, keys, subject):
            events.append(event)
            if event["type"] == "captured":
                with Session(databases.biometric) as db, db.begin():
                    db.get(Algorithm, "opencv-sift").threshold = 1000
                    db.add(Enrolment(id=uuid.uuid4(), subject_id=subject, modality="fingerprint", finger=2,
                                     created_at=datetime.now(timezone.utc)))
        return events
    result = anyio.run(run)[-1]
    assert result["type"] == "identified" and result["accepted"] is True and result["threshold"] == 57
    assert result["gallery_size"] == 3


@pytest.mark.parametrize("fault,code", [("missing", "gallery_templates_unavailable"), ("version", "template_version_mismatch"), ("sealed", "stored_template_unreadable")])
def test_broken_gallery_is_reported_without_a_saved_non_match(fp_client, script, databases, fault, code):
    token = enrolled(fp_client, script)
    with Session(databases.biometric) as db, db.begin():
        template = db.scalars(select(Template)).first()
        if fault == "missing":
            db.delete(template)
        elif fault == "version":
            template.version = "old"
        else:
            template.data = b"x" * len(template.data)
    plan(script, finger("q60:A4"))
    assert identify(fp_client, token)[-1]["error"] == code
    with Session(databases.biometric) as db:
        assert db.scalars(select(Attempt)).all() == []


def test_deleting_leader_preserves_identification_and_its_probe(fp_client, script, databases, keys):
    token = enrolled(fp_client, script)
    other_token = other_enrolled(fp_client, script)
    subject = subject_of(fp_client, databases, keys, token)
    plan(script, finger("q60:B4"))
    result = identify(fp_client, token)[-1]
    with Session(databases.biometric) as db:
        stored = db.get(Attempt, uuid.UUID(result["attempt_id"]))
        before = stored.probe
        assert db.get(Enrolment, stored.top_enrolment_id).subject_id != subject
    assert fp_client.delete("/api/fingerprint/fingers/2", headers=auth(other_token)).status_code == 204
    with Session(databases.biometric) as db:
        attempt = db.get(Attempt, uuid.UUID(result["attempt_id"]))
        assert attempt is not None and attempt.top_enrolment_id is None and attempt.probe == before
        assert attempt.accepted and attempt.gallery_size == 6
        assert keyring.open_sealed(keys, keyring.PROBE, attempt.id.bytes + subject.bytes, attempt.probe) == b"FAKEPNG:q60:B4"


def test_quality_retry_and_defined_comparison_failures(fp_client, script, service, databases, monkeypatch):
    token = enrolled(fp_client, script)
    for engine in service.search_engines():
        original = engine.request
        def fail_comparison(header, parts, request=original):
            return ({"status": "failure", "score": None}, []) if header["op"] == "compare" else request(header, parts)
        monkeypatch.setattr(engine, "request", fail_comparison)
    plan(script, finger("q20:A4"), LIFT, finger("q255:A5"), LIFT, finger("q35:A6"))
    events = identify(fp_client, token)
    assert [e["score"] for e in events if e["type"] == "rejected"] == [20, None]
    assert events[-1]["type"] == "identified" and events[-1]["score"] == 0 and not events[-1]["accepted"]
    with Session(databases.biometric) as db:
        assert len(db.scalars(select(Attempt)).all()) == 1


@pytest.mark.parametrize("stage", ["scanner", "engine"])
def test_cancel_stops_inflight_work_releases_lock_and_allows_retry(fp_client, script, service, databases, keys, tmp_path, stage):
    token = enrolled(fp_client, script)
    subject = subject_of(fp_client, databases, keys, token)
    marker = tmp_path / "comparing.txt"
    if stage == "engine":
        service.sift.close()
        service.sift.command += ["--hang-compare", str(marker)]
        plan(script, finger("q60:A4"))
    else:
        plan(script, {"hang": True})
    async def consume():
        async for _ in identification.identify(service, databases, keys, subject):
            pass
    async def cancel():
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(consume)
            with anyio.fail_after(10):
                while not (marker.exists() if stage == "engine" else not json.loads(script.read_text())):
                    await anyio.sleep(0.02)
            tasks.cancel_scope.cancel()
    started = time.monotonic()
    anyio.run(cancel)
    assert time.monotonic() - started < 10 and not service._busy.locked()
    with Session(databases.biometric) as db:
        assert db.scalars(select(Attempt)).all() == []
    if stage == "engine":
        for engine in service.search_engines():
            engine.close()
            engine.command = engine.command[:-2]
    plan(script, finger("q60:A4"))
    assert identify(fp_client, token)[-1]["accepted"] is True


def test_failure_to_save_never_becomes_a_completed_result(fp_client, script, databases, monkeypatch):
    token = enrolled(fp_client, script)
    def fail(*args):
        raise RuntimeError("test storage error")
    monkeypatch.setattr(identification, "_save", fail)
    plan(script, finger("q60:A4"))
    assert identify(fp_client, token)[-1]["error"] == "unexpected"
    with Session(databases.biometric) as db:
        assert db.scalars(select(Attempt)).all() == []


def test_engine_failure_in_parallel_search_is_not_a_non_match(fp_client, script, service, databases, monkeypatch):
    token = enrolled(fp_client, script)
    original = service.search_engines()[1].request
    def fail_compare(header, parts):
        if header["op"] == "compare":
            raise EngineError("test comparison failure")
        return original(header, parts)
    monkeypatch.setattr(service.search_engines()[1], "request", fail_compare)
    plan(script, finger("q60:A4"))
    assert identify(fp_client, token)[-1]["error"] == "engine_unavailable"
    assert not service._busy.locked()
    with Session(databases.biometric) as db:
        assert db.scalars(select(Attempt)).all() == []


def test_maximum_quality_retries_and_shared_scanner_are_enforced(fp_client, script, service, databases):
    token = enrolled(fp_client, script)
    service._busy.acquire()
    try:
        assert identify(fp_client, token)[-1]["error"] == "scanner_busy"
    finally:
        service._busy.release()
    plan(script, *placements(*["q20:A4"] * fingerprint.MOST_CAPTURES))
    events = identify(fp_client, token)
    assert events[-1]["error"] == "too_many_captures"
    assert len([event for event in events if event["type"] == "rejected"]) == fingerprint.MOST_CAPTURES
    with Session(databases.biometric) as db:
        assert db.scalars(select(Attempt)).all() == []


def test_disconnect_while_sending_progress_releases_the_flow(fp_client, script, service, databases, keys):
    from mbs.api import FingerprintResponse
    token = enrolled(fp_client, script)
    subject = subject_of(fp_client, databases, keys, token)
    async def fail_send(message):
        if message["type"] == "http.response.body":
            raise OSError("disconnected")
    async def run():
        response = FingerprintResponse(identification.identify(service, databases, keys, subject))
        with pytest.raises(OSError):
            await response.stream_response(fail_send)
    anyio.run(run)
    assert not service._busy.locked()


def test_upgrade_retains_existing_attempts_and_applies_the_new_deletion_rule(fp_client, script, databases, keys):
    from alembic import command
    from alembic.config import Config
    from mbs.db import MIGRATIONS, migrate
    from test_verification import verify

    migration = Config()
    migration.set_main_option("script_location", str(MIGRATIONS / "biometric"))
    migration.attributes["engine"] = databases.biometric
    command.downgrade(migration, "biometric_0003")
    token = enrolled(fp_client, script)
    plan(script, finger("q60:A4"))
    verify(fp_client, token)
    plan(script, finger("q60:A4"))
    result = identify(fp_client, token)[-1]
    with Session(databases.biometric) as db:
        before = db.get(Attempt, uuid.UUID(result["attempt_id"])).probe
    migrate(databases)
    assert fp_client.delete("/api/fingerprint/fingers/7", headers=auth(token)).status_code == 204
    with Session(databases.biometric) as db:
        remaining = db.scalars(select(Attempt)).one()
        assert remaining.mode == "identify" and remaining.top_enrolment_id is None and remaining.probe == before
