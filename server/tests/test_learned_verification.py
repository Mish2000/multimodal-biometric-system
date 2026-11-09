"""H39: shared detection, native method separation and atomic preparation of Pore CNN."""

import json
import struct
from datetime import datetime, timezone

import anyio
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from mbs import fingerprint, verification
from mbs import keys as keyring
from mbs.engines import Engine, EngineError
from mbs.models import Attempt, Enrolment, Template

from test_api import auth
from test_fingerprint import (FAKES, PYTHON, enrol, finger, fp_client, plan, placements, script, service,
                              subject_of, user)  # noqa: F401
from test_pore_verification import add_pore, verify
from test_verification import enrolled


def add_learned(service):
    if service.pore is None:
        add_pore(service)
    service.learned = Engine("learned-pore", [PYTHON, str(FAKES / "fake_engine.py"), "learned"])
    return service.learned


def learned_rows(databases):
    with Session(databases.biometric) as db:
        return db.scalars(select(Template).where(Template.algorithm == "learned-pore")).all()


def test_new_enrolment_shares_pores_and_seals_all_nine_templates(fp_client, script, service, databases, keys, monkeypatch):
    add_learned(service)
    calls, request = [], service.pore.request

    def observe(header, parts):
        calls.append(header["op"])
        return request(header, parts)

    monkeypatch.setattr(service.pore, "request", observe)
    token = user(fp_client)
    plan(script, *placements("q60:A1", "q60:A2", "q60:A3"))
    result = enrol(fp_client, token)[-1]
    assert result["type"] == "saved" and result["referee"] == "opencv-sift"
    assert calls.count("extract") == 3 and "detect" not in calls
    assert result["pending_methods"] == []
    assert {m["algorithm"]: m["threshold"] for m in result["method_comparisons"]} == {
        "opencv-sift": 57, "pore-sift": 37, "learned-pore": 21}
    subject = subject_of(fp_client, databases, keys, token)
    with Session(databases.biometric) as db:
        assert len(db.scalars(select(Template)).all()) == 9
    for row in learned_rows(databases):
        assert keyring.open_sealed(keys, keyring.TEMPLATE, row.id.bytes + subject.bytes + b"learned-pore", row.data).startswith(b"LEARNED:")
        with pytest.raises(keyring.KeysError):
            keyring.open_sealed(keys, keyring.TEMPLATE, row.id.bytes + subject.bytes + b"pore-sift", row.data)


def test_other_methods_pair_scores_do_not_override_the_enrolment_referee(fp_client, script, service, monkeypatch):
    add_learned(service)
    for engine in (service.pore, service.learned):
        original = engine.request
        def low_scores(header, parts, request=original):
            return ({"status": "ok", "score": 0}, []) if header["op"] == "compare" else request(header, parts)
        monkeypatch.setattr(engine, "request", low_scores)
    token = user(fp_client)
    plan(script, *placements("q60:A1", "q60:A2", "q60:A3"))
    result = enrol(fp_client, token)[-1]
    assert result["type"] == "saved" and all(p["accepted"] for p in result["pairs"])
    assert all(not p["accepted"] for method in result["method_comparisons"][1:] for p in method["pairs"])


@pytest.mark.parametrize("stored_pores", [False, True])
def test_existing_enrolment_prepares_once_and_reuses_stored_pores(fp_client, script, service, databases, keys, monkeypatch, stored_pores):
    if stored_pores:
        add_pore(service)
    token = enrolled(fp_client, script)
    add_learned(service)
    calls, request = [], service.pore.request
    def observe(header, parts):
        calls.append(header["op"])
        return request(header, parts)
    monkeypatch.setattr(service.pore, "request", observe)
    plan(script, finger("q60:A4"))
    first = verify(fp_client, token, "learned-pore")
    assert [e["completed"] for e in first if e["type"] == "preparing_templates"] == [0, 1, 2, 3]
    assert calls.count("detect") == (1 if stored_pores else 4)
    assert first[-1]["score"] == 30 and first[-1]["accepted"] is True
    ids = {row.id for row in learned_rows(databases)}
    plan(script, finger("q60:B1"))
    second = verify(fp_client, token, "learned-pore")
    assert not any(e["type"] == "preparing_templates" for e in second)
    assert {row.id for row in learned_rows(databases)} == ids and len(ids) == 3
    assert second[-1]["score"] == 2 and second[-1]["accepted"] is False
    subject = subject_of(fp_client, databases, keys, token)
    with Session(databases.biometric) as db:
        attempts = db.scalars(select(Attempt).order_by(Attempt.at)).all()
        assert [(a.algorithm, a.threshold, a.accepted) for a in attempts] == [("learned-pore", 21, True), ("learned-pore", 21, False)]
        assert all(keyring.open_sealed(keys, keyring.PROBE, a.id.bytes + subject.bytes, a.probe).startswith(b"FAKEPNG:") for a in attempts)


@pytest.mark.parametrize("action", ["delete", "replace", "cancel"])
def test_preparation_interruption_does_not_commit_partial_templates(fp_client, script, service, databases, keys, action):
    token = enrolled(fp_client, script)
    add_learned(service)
    subject = subject_of(fp_client, databases, keys, token)
    async def prepare():
        flow = verification.verify(service, databases, keys, subject, 7, "learned-pore")
        events = []
        async for event in flow:
            events.append(event)
            if event["type"] == "preparing_templates" and event["completed"] == 1:
                if action == "delete":
                    fingerprint.delete_finger(databases, subject, 7)
                elif action == "replace":
                    with Session(databases.biometric) as db, db.begin():
                        db.scalars(select(Enrolment)).one().replaced_at = datetime.now(timezone.utc)
                else:
                    await flow.aclose()
                    break
        return events
    events = anyio.run(prepare)
    if action != "cancel":
        assert events[-1]["error"] == "enrolment_changed"
    assert learned_rows(databases) == [] and not service._busy.locked()
    with Session(databases.biometric) as db:
        assert db.scalars(select(Attempt)).all() == []


def test_failed_preparation_retries_without_partial_rows_or_a_new_scan(fp_client, script, service, databases, monkeypatch):
    token = enrolled(fp_client, script)
    engine = add_learned(service)
    original, calls = engine.request, []
    def fail_second(header, parts):
        calls.append(header["op"])
        if len(calls) == 2:
            raise EngineError("test failure")
        return original(header, parts)
    monkeypatch.setattr(engine, "request", fail_second)
    plan(script, finger("q60:A4"))
    assert verify(fp_client, token, "learned-pore")[-1]["error"] == "engine_unavailable"
    assert learned_rows(databases) == [] and len(json.loads(script.read_text())) == 1
    monkeypatch.setattr(engine, "request", original)
    assert verify(fp_client, token, "learned-pore")[-1]["accepted"] is True


def test_learned_threshold_is_strict_and_uses_the_highest_of_three(fp_client, script, service, monkeypatch):
    add_learned(service)
    token = enrolled(fp_client, script)
    engine, scores, seen = service.learned, iter([20, 21, 21, 20, 21, 22]), []
    original = engine.request
    def boundary(header, parts):
        if header["op"] != "compare":
            return original(header, parts)
        if header.get("view") is True:  # H44: the winning comparison, repeated once with its pores
            best = max(seen[-3:])
            return {"status": "ok", "score": best, "matches": best}, [struct.pack("<4f", 10, 20, 30, 40) * best]
        seen.append(next(scores))
        return {"status": "ok", "score": seen[-1]}, []
    monkeypatch.setattr(engine, "request", boundary)
    for accepted in (False, True):
        plan(script, finger("q60:A4"))
        result = verify(fp_client, token, "learned-pore")[-1]
        assert result["accepted"] is accepted and result["threshold"] == 21 and result["threshold_provisional"]


def test_failed_new_method_preserves_the_previous_enrolment(fp_client, script, service, databases, monkeypatch):
    token = enrolled(fp_client, script)
    engine = add_learned(service)
    with Session(databases.biometric) as db:
        previous = db.scalars(select(Enrolment)).one().id
    def fail(*args):
        raise EngineError("test failure")
    monkeypatch.setattr(engine, "start", fail)
    plan(script, *placements("q60:A4", "q60:A5", "q60:A6"))
    assert enrol(fp_client, token)[-1]["error"] == "engine_unavailable"
    with Session(databases.biometric) as db:
        current = db.scalars(select(Enrolment)).one()
        assert current.id == previous and current.replaced_at is None


def test_unavailable_learned_method_is_refused_before_capture(fp_client, script, service):
    token = enrolled(fp_client, script)
    add_pore(service)
    plan(script, finger("q60:A4"))
    assert verify(fp_client, token, "learned-pore")[-1]["error"] == "method_unavailable"
    assert len(json.loads(script.read_text())) == 1
    methods = fp_client.get("/api/fingerprint/methods", headers=auth(token)).json()["methods"]
    assert next(m for m in methods if m["code"] == "learned-pore")["available"] is False
