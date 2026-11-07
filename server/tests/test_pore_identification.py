"""H42: selected-method gallery templates, atomic preparation and cancellation before capture."""

import json
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Event

import anyio
import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from mbs import fingerprint, identification
from mbs import keys as keyring
from mbs.engines import EngineError
from mbs.models import Attempt, Enrolment, Sample, Template

from test_api import auth
from test_fingerprint import finger, fp_client, plan, script, service, subject_of  # noqa: F401
from test_identification import identify, other_enrolled
from test_learned_verification import add_learned
from test_pore_verification import add_pore
from test_verification import enrolled

METHODS = ["pore-sift", "learned-pore"]


def enable(service, algorithm):
    return add_pore(service) if algorithm == "pore-sift" else add_learned(service)


def method_rows(databases, algorithm):
    with Session(databases.biometric) as db:
        return db.execute(select(Template, Sample.enrolment_id, Enrolment.subject_id).select_from(Template).join(Sample).join(Enrolment).where(
            Template.algorithm == algorithm)).all()


@pytest.mark.parametrize("algorithm", METHODS)
@pytest.mark.parametrize("probe,accepted,own", [("A4", True, True), ("B4", True, False), ("C4", False, None)])
def test_selected_method_prepares_the_whole_gallery_and_records_its_own_result(
        fp_client, script, service, databases, keys, algorithm, probe, accepted, own):
    token = enrolled(fp_client, script)
    other_enrolled(fp_client, script)
    enable(service, algorithm)
    plan(script, finger(f"q60:{probe}"))
    events = identify(fp_client, token, algorithm=algorithm)
    result = events[-1]
    assert [event["completed"] for event in events if event["type"] == "preparing_templates"] == list(range(7))
    assert result["type"] == "identified" and result["algorithm"] == algorithm and result["accepted"] is accepted
    assert result["threshold"] == (37 if algorithm == "pore-sift" else 21) and result["threshold_provisional"]
    assert result["gallery_size"] == 6 and result["enrolments"] == 2
    if own is not None:
        assert result["candidates"][0]["own"] is own
    assert all(candidate["finger"] is None for candidate in result["candidates"] if not candidate["own"])
    rows = method_rows(databases, algorithm)
    assert len(rows) == 6
    for row, _, owner in rows:
        native = keyring.open_sealed(keys, keyring.TEMPLATE, row.id.bytes + owner.bytes + algorithm.encode(), row.data)
        assert native.startswith(b"PORE:" if algorithm == "pore-sift" else b"LEARNED:")
        with pytest.raises(keyring.KeysError):
            keyring.open_sealed(keys, keyring.TEMPLATE, row.id.bytes + owner.bytes + b"opencv-sift", row.data)
    with Session(databases.biometric) as db:
        attempt = db.scalars(select(Attempt)).one()
        assert attempt.algorithm == algorithm and attempt.threshold == result["threshold"]
        assert attempt.accepted is accepted and attempt.enrolment_id is None and attempt.top_enrolment_id
    ids = {row.id for row, _, _ in rows}
    plan(script, finger("q60:A5"))
    again = identify(fp_client, token, algorithm=algorithm)
    assert again[-1]["type"] == "identified" and not any(e["type"] == "preparing_templates" for e in again)
    assert {row.id for row, _, _ in method_rows(databases, algorithm)} == ids


def test_learned_gallery_preparation_reuses_stored_pore_coordinates(fp_client, script, service, databases, monkeypatch):
    add_pore(service)
    token = enrolled(fp_client, script)
    other_enrolled(fp_client, script)
    pore_ids = {row.id for row, _, _ in method_rows(databases, "pore-sift")}
    add_learned(service)
    calls, original = [], service.pore.request
    def observe(header, parts):
        calls.append(header["op"])
        return original(header, parts)
    monkeypatch.setattr(service.pore, "request", observe)
    plan(script, finger("q60:A4"))
    result = identify(fp_client, token, algorithm="learned-pore")[-1]
    assert result["type"] == "identified" and result["accepted"] is True
    assert calls == ["detect"]  # only the new probe needs detection
    assert {row.id for row, _, _ in method_rows(databases, "pore-sift")} == pore_ids
    assert len(service.search_engines("learned-pore")) == 1


@pytest.mark.parametrize("algorithm", METHODS)
@pytest.mark.parametrize("interruption", ["failure", "cancel"])
def test_retry_reuses_complete_enrolments_without_partial_trios(
        fp_client, script, service, databases, keys, monkeypatch, algorithm, interruption):
    token = enrolled(fp_client, script)
    other_enrolled(fp_client, script)
    engine = enable(service, algorithm)
    subject = subject_of(fp_client, databases, keys, token)
    calls, original = [], engine.request
    def fail_fourth(header, parts):
        if header["op"] == "extract":
            calls.append(header["op"])
            if len(calls) == 4:
                raise EngineError("test extraction failure")
        return original(header, parts)
    plan(script, finger("q60:A4"))
    if interruption == "failure":
        monkeypatch.setattr(engine, "request", fail_fourth)
        assert identify(fp_client, token, algorithm=algorithm)[-1]["error"] == "engine_unavailable"
        monkeypatch.setattr(engine, "request", original)
    else:
        async def cancel():
            flow = identification.identify(service, databases, keys, subject, algorithm)
            async for event in flow:
                if event["type"] == "preparing_templates" and event["completed"] == 4:
                    await flow.aclose()
                    break
        anyio.run(cancel)
    prepared = method_rows(databases, algorithm)
    assert list(Counter(enrolment for _, enrolment, _ in prepared).values()) == [3]
    ids = {row.id for row, _, _ in prepared}
    assert len(json.loads(script.read_text())) == 1 and not service._busy.locked()
    with Session(databases.biometric) as db:
        assert db.scalars(select(Attempt)).all() == []
    events = identify(fp_client, token, algorithm=algorithm)
    assert events[-1]["accepted"] is True
    assert [e["total"] for e in events if e["type"] == "preparing_templates"] == [3, 3, 3, 3]
    assert ids.issubset({row.id for row, _, _ in method_rows(databases, algorithm)})
    assert len(method_rows(databases, algorithm)) == 6


@pytest.mark.parametrize("algorithm", METHODS)
@pytest.mark.parametrize("change", ["delete", "replace"])
def test_enrolment_change_during_preparation_invalidates_it(fp_client, script, service, databases, keys, algorithm, change):
    token = enrolled(fp_client, script)
    enable(service, algorithm)
    subject = subject_of(fp_client, databases, keys, token)
    async def run():
        events = []
        async for event in identification.identify(service, databases, keys, subject, algorithm):
            events.append(event)
            if event["type"] == "preparing_templates" and event["completed"] == 1:
                if change == "delete":
                    fingerprint.delete_finger(databases, subject, 7)
                else:
                    with Session(databases.biometric) as db, db.begin():
                        db.scalars(select(Enrolment)).one().replaced_at = datetime.now(timezone.utc)
        return events
    assert anyio.run(run)[-1] == {"type": "failed", "error": "gallery_changed"}
    assert method_rows(databases, algorithm) == [] and not service._busy.locked()


def test_deletion_waits_for_preparation_commit_and_removes_the_new_templates(
        fp_client, script, service, databases, monkeypatch):
    token = enrolled(fp_client, script)
    add_pore(service)
    plan(script, finger("q60:A4"))
    writing = Event()
    resume = Event()
    seal = keyring.seal

    def pause_preparation(keys, label, row, plaintext):
        if label == keyring.TEMPLATE and row.endswith(b"pore-sift") and not writing.is_set():
            writing.set()
            assert resume.wait(15), "the test did not resume template storage"
        return seal(keys, label, row, plaintext)

    monkeypatch.setattr(keyring, "seal", pause_preparation)
    with ThreadPoolExecutor(max_workers=2) as pool:
        search = pool.submit(identify, fp_client, token, algorithm="pore-sift")
        try:
            assert writing.wait(15), "identification did not reach template storage"
            deletion = pool.submit(fp_client.delete, "/api/fingerprint/fingers/7", headers=auth(token))
            # Release preparation only after the overlapping delete reaches a database lock.
            with databases.biometric.connect().execution_options(isolation_level="AUTOCOMMIT") as db:
                waiting = text("SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                               "WHERE datname = current_database() AND wait_event_type = 'Lock')")
                deadline = time.monotonic() + 10
                while not db.scalar(waiting):
                    assert time.monotonic() < deadline, "deletion did not wait for preparation"
                    time.sleep(0.02)
        finally:
            resume.set()
        assert deletion.result(timeout=15).status_code == 204
        assert search.result(timeout=15)[-1] == {"type": "failed", "error": "gallery_changed"}

    with Session(databases.biometric) as db:
        assert db.scalars(select(Enrolment)).all() == []
        assert db.scalars(select(Template)).all() == []
        assert db.scalars(select(Attempt)).all() == []


@pytest.mark.parametrize("algorithm", METHODS)
@pytest.mark.parametrize("accepted", [False, True])
def test_each_method_uses_its_strict_threshold(fp_client, script, service, monkeypatch, algorithm, accepted):
    token = enrolled(fp_client, script)
    enable(service, algorithm)
    threshold = 37 if algorithm == "pore-sift" else 21
    score = threshold + int(accepted)
    for engine in service.search_engines(algorithm):
        original = engine.request
        def boundary(header, parts, request=original):
            if header["op"] == "compare":
                return {"status": "ok", "score": score if parts[1].endswith(b"A2") else 0}, []
            return request(header, parts)
        monkeypatch.setattr(engine, "request", boundary)
    plan(script, finger("q60:A4"))
    result = identify(fp_client, token, algorithm=algorithm)[-1]
    assert result["type"] == "identified" and result["score"] == score
    assert result["accepted"] is accepted and result["threshold"] == threshold and result["threshold_provisional"]


@pytest.mark.parametrize("algorithm,operation", [("pore-sift", "extract"), ("learned-pore", "detect"), ("learned-pore", "extract")])
def test_cancel_interrupts_the_correct_preparation_process_and_allows_retry(
        fp_client, script, service, databases, keys, tmp_path, algorithm, operation):
    token = enrolled(fp_client, script)
    engine = enable(service, algorithm)
    subject = subject_of(fp_client, databases, keys, token)
    affected = service.pore if operation == "detect" else engine
    marker = tmp_path / "preparation.txt"
    flag = f"--hang-{operation}"
    affected.command += [flag, str(marker)]
    plan(script, finger("q60:A4"))
    async def consume():
        async for _ in identification.identify(service, databases, keys, subject, algorithm):
            pass
    async def cancel():
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(consume)
            with anyio.fail_after(10):
                while not marker.exists():
                    await anyio.sleep(0.02)
            tasks.cancel_scope.cancel()
    started = time.monotonic()
    anyio.run(cancel)
    assert time.monotonic() - started < 10 and not service._busy.locked()
    assert method_rows(databases, algorithm) == [] and len(json.loads(script.read_text())) == 1
    for worker in {*service.search_engines(algorithm), service.pore}:
        if flag in worker.command:
            worker.close()
            offset = worker.command.index(flag)
            del worker.command[offset:offset + 2]
    assert identify(fp_client, token, algorithm=algorithm)[-1]["accepted"] is True


@pytest.mark.parametrize("algorithm", METHODS)
def test_concurrent_preparation_reuses_existing_rows(fp_client, script, service, databases, monkeypatch, algorithm):
    token = enrolled(fp_client, script)
    enable(service, algorithm)
    original = identification._store_prepared
    def concurrent(*args):
        original(*args)  # another preparation commits after the initial snapshot
        return original(*args)
    monkeypatch.setattr(identification, "_store_prepared", concurrent)
    plan(script, finger("q60:A4"))
    assert identify(fp_client, token, algorithm=algorithm)[-1]["accepted"] is True
    assert len(method_rows(databases, algorithm)) == 3


@pytest.mark.parametrize("algorithm", METHODS)
def test_missing_runtime_is_refused_without_capture(fp_client, script, algorithm):
    token = enrolled(fp_client, script)
    plan(script, finger("q60:A4"))
    assert identify(fp_client, token, algorithm=algorithm)[-1]["error"] == "method_unavailable"
    assert len(json.loads(script.read_text())) == 1


@pytest.mark.parametrize("algorithm", METHODS)
def test_unreadable_source_does_not_create_templates_or_a_result(fp_client, script, service, databases, algorithm):
    token = enrolled(fp_client, script)
    enable(service, algorithm)
    with Session(databases.biometric) as db, db.begin():
        for sample in db.scalars(select(Sample)):
            sample.data = b"damaged"
    plan(script, finger("q60:A4"))
    assert identify(fp_client, token, algorithm=algorithm)[-1]["error"] == "stored_template_unreadable"
    assert method_rows(databases, algorithm) == []
