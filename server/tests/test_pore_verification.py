"""H38: selected methods, new enrolments and safe preparation of existing encrypted findings."""

import json

import anyio
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from mbs import fingerprint, verification
from mbs import keys as keyring
from mbs.engines import Engine, EngineError
from mbs.models import Attempt, Enrolment, Template

from test_api import administrator, auth
from test_fingerprint import (FAKES, PYTHON, enrol, finger, fp_client, plan, placements, script, service,
                              subject_of, user)  # noqa: F401 (fixtures)
from test_verification import enrolled


def add_pore(service):
    service.pore = Engine("pore-sift", [PYTHON, str(FAKES / "fake_engine.py"), "pore"])
    return service.pore


def verify(client, token, algorithm="pore-sift"):
    response = client.post("/api/fingerprint/verifications", json={"finger": 7, "algorithm": algorithm}, headers=auth(token))
    assert response.status_code == 200
    return [json.loads(line) for line in response.iter_lines() if line]


def pore_rows(databases):
    with Session(databases.biometric) as db:
        return db.scalars(select(Template).where(Template.algorithm == "pore-sift")).all()


def test_method_catalog_uses_the_database_and_enforces_user_role(fp_client, databases, service):
    token = user(fp_client)
    assert fp_client.get("/api/fingerprint/methods").status_code == 401
    admin = administrator(fp_client, databases)
    assert fp_client.get("/api/fingerprint/methods", headers=auth(admin)).status_code == 403
    methods = fp_client.get("/api/fingerprint/methods", headers=auth(token)).json()["methods"]
    assert [(m["code"], m["threshold"], m["threshold_provisional"], m["available"]) for m in methods] == [
        ("opencv-sift", 57, False, True), ("learned-pore", 21, True, False), ("pore-sift", 37, True, False)]
    add_pore(service)
    assert fp_client.get("/api/fingerprint/methods", headers=auth(token)).json()["methods"][2]["available"] is True
    assert fp_client.post("/api/fingerprint/verifications", json={"finger": 7, "algorithm": "fusion"}, headers=auth(token)).status_code == 422


def test_new_enrolment_keeps_both_methods_and_the_sift_referee(fp_client, script, service, databases, keys):
    add_pore(service)
    token = enrolled(fp_client, script)
    subject = subject_of(fp_client, databases, keys, token)
    rows = pore_rows(databases)
    assert len(rows) == 3
    for row in rows:
        assert keyring.open_sealed(keys, keyring.TEMPLATE, row.id.bytes + subject.bytes + b"pore-sift", row.data).startswith(b"PORE:")
        with pytest.raises(keyring.KeysError):
            keyring.open_sealed(keys, keyring.TEMPLATE, row.id.bytes + subject.bytes + b"opencv-sift", row.data)
    plan(script, finger("q60:A4"))
    events = verify(fp_client, token)
    assert not any(e["type"] == "preparing_templates" for e in events)
    assert events[-1]["algorithm"] == "pore-sift" and events[-1]["score"] == 45
    assert events[-1]["threshold"] == 37 and events[-1]["threshold_provisional"] is True


def test_existing_enrolment_is_prepared_once_and_each_method_uses_its_own_templates(fp_client, script, service, databases):
    token = enrolled(fp_client, script)
    add_pore(service)
    plan(script, finger("q60:A4"))
    first = verify(fp_client, token)
    assert [e["completed"] for e in first if e["type"] == "preparing_templates"] == [0, 1, 2, 3]
    ids = {row.id for row in pore_rows(databases)}
    assert len(ids) == 3
    plan(script, finger("q60:A5"))
    second = verify(fp_client, token)
    assert not any(e["type"] == "preparing_templates" for e in second)
    assert {row.id for row in pore_rows(databases)} == ids
    plan(script, finger("q60:A6"))
    assert verify(fp_client, token, "opencv-sift")[-1]["score"] == 90
    with Session(databases.biometric) as db:
        assert sorted((row.algorithm, row.threshold) for row in db.scalars(select(Attempt))) == [
            ("opencv-sift", 57), ("pore-sift", 37), ("pore-sift", 37)]


def test_preparation_failure_saves_no_partial_templates_and_can_retry(fp_client, script, service, databases, monkeypatch):
    token = enrolled(fp_client, script)
    engine = add_pore(service)
    original, calls = engine.request, []

    def fail_second(header, parts):
        calls.append(header["op"])
        if len(calls) == 2:
            raise EngineError("test extraction failure")
        return original(header, parts)

    monkeypatch.setattr(engine, "request", fail_second)
    plan(script, finger("q60:A4"))
    assert verify(fp_client, token)[-1]["error"] == "engine_unavailable"
    assert pore_rows(databases) == []
    assert len(json.loads(script.read_text())) == 1  # no new capture until references are ready
    monkeypatch.setattr(engine, "request", original)
    assert verify(fp_client, token)[-1]["accepted"] is True


@pytest.mark.parametrize("action", ["delete", "cancel"])
def test_preparation_interruption_leaves_consistent_state(fp_client, script, service, databases, keys, action):
    token = enrolled(fp_client, script)
    add_pore(service)
    subject = subject_of(fp_client, databases, keys, token)

    async def prepare():
        flow = verification.verify(service, databases, keys, subject, 7, "pore-sift")
        events = []
        async for event in flow:
            events.append(event)
            if event["type"] == "preparing_templates" and event["completed"] == 1:
                if action == "delete":
                    fingerprint.delete_finger(databases, subject, 7)
                else:
                    await flow.aclose()
                    break
        return events

    events = anyio.run(prepare)
    if action == "delete":
        assert events[-1]["error"] == "enrolment_changed"
    assert pore_rows(databases) == [] and not service._busy.locked()
    with Session(databases.biometric) as db:
        assert db.scalars(select(Attempt)).all() == []


def test_a_failed_new_method_keeps_the_existing_enrolment(fp_client, script, service, databases, monkeypatch):
    token = enrolled(fp_client, script)
    engine = add_pore(service)
    with Session(databases.biometric) as db:
        previous = db.scalars(select(Enrolment)).one().id

    def fail(*args):
        raise EngineError("not available")

    monkeypatch.setattr(engine, "start", fail)
    plan(script, *placements("q60:A4", "q60:A5", "q60:A6"))
    assert enrol(fp_client, token)[-1]["error"] == "engine_unavailable"
    with Session(databases.biometric) as db:
        row = db.scalars(select(Enrolment)).one()
        assert row.id == previous and row.replaced_at is None


def test_pore_threshold_is_strict_and_comparison_uses_all_three_references(fp_client, script, service, monkeypatch):
    add_pore(service)
    token = enrolled(fp_client, script)
    engine, scores = service.pore, iter([5, 36, 37, 5, 37, 38])
    original = engine.request

    def compare(header, parts):
        if header["op"] == "compare":
            return {"status": "ok", "score": next(scores)}, []
        return original(header, parts)

    monkeypatch.setattr(engine, "request", compare)
    for accepted in (False, True):
        plan(script, finger("q60:A4"))
        assert verify(fp_client, token)[-1]["accepted"] is accepted
