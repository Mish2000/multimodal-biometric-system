"""Fingerprint enrolment (H6, H15, H25, H33) against a real PostgreSQL, with the scanner and the engines replaced
by stand-ins that speak their real protocols (tests/fakes/). Captures here are labels, never images."""

from __future__ import annotations

import json
import sys
import threading
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from mbs import accounts
from mbs import keys as keyring
from mbs.api import create_app
from mbs.engines import Engine, Scanner, ScannerError, ScannerRun
from mbs.fingerprint import FingerprintService, Kept, best_three
from mbs.models import Algorithm, Enrolment, Sample, Template

from test_api import administrator, auth, error, register, sign_in

FAKES = Path(__file__).resolve().parent / "fakes"
PYTHON = sys.executable


def service_for(script: Path, sift: list[str] | None = None) -> FingerprintService:
    return FingerprintService(
        scanner=Scanner([PYTHON, str(FAKES / "fake_scanner.py"), "--script", str(script)]),
        quality=Engine("nfiq2", [PYTHON, str(FAKES / "fake_engine.py"), "quality"]),
        sift=Engine("opencv-sift", sift or [PYTHON, str(FAKES / "fake_engine.py"), "sift"]),
    )


@pytest.fixture
def script(tmp_path):
    path = tmp_path / "scanner.json"
    path.write_text("[]", encoding="utf-8")
    return path


@pytest.fixture
def service(script):
    service = service_for(script)
    yield service
    service.close()


@pytest.fixture
def fp_client(databases, keys, outbox, service):
    with TestClient(base_url="http://127.0.0.1", app=create_app(databases, keys, outbox, service)) as client:
        yield client


def plan(script: Path, *steps) -> None:
    script.write_text(json.dumps(list(steps)), encoding="utf-8")


def finger(label: str) -> dict:
    return {"wait": "finger", "image": label}


LIFT = {"wait": "lift"}


def placements(*labels: str) -> list[dict]:
    """A placement for every label, with the lift between them."""
    steps = []
    for label in labels:
        steps += [finger(label), LIFT]
    return steps[:-1]


def enrol(client, token, finger_position=7) -> list[dict]:
    with client.stream("POST", "/api/fingerprint/enrolments", json={"finger": finger_position}, headers=auth(token)) as r:
        assert r.status_code == 200, r.read()
        assert r.headers["content-type"].startswith("application/x-ndjson")
        return [json.loads(line) for line in r.iter_lines() if line]


def user(client) -> str:
    register(client)
    return sign_in(client)


def subject_of(client, databases, keys, token) -> uuid.UUID:
    account_id = uuid.UUID(client.get("/api/me", headers=auth(token)).json()["account"]["id"])
    return accounts.subject_of(databases, keys, account_id)


def kinds(events: list[dict]) -> list[str]:
    return [e["type"] for e in events]


def test_three_matching_placements_are_sealed_and_kept(fp_client, script, databases, keys):
    token = user(fp_client)
    plan(script, *placements("q64:A1", "q70:A2", "q58:A3"))
    events = enrol(fp_client, token)
    assert kinds(events) == ["started", "place", "kept", "lift", "place", "kept", "lift", "place", "kept", "saved"]
    started, saved = events[0], events[-1]
    assert started["finger"] == 7 and started["threshold"] == 57 and started["quality_minimum"] == 35
    assert [p["score"] for p in events[5]["pairs"]] == [90]
    assert [(p["probe"], p["reference"]) for p in saved["pairs"]] == [(2, 1), (3, 1), (3, 2)]
    assert saved["not_kept"] == [] and saved["pending_methods"] == ["pore-sift", "learned-pore"]
    assert [t["keypoints"] for t in saved["templates"]] == [3, 3, 3]
    assert saved["templates"][0]["sealed"]["ciphertext"] == len(b"TEMPLATE:A1")

    subject = subject_of(fp_client, databases, keys, token)
    with Session(databases.biometric) as db:
        enrolment = db.scalars(select(Enrolment)).one()
        samples = db.scalars(select(Sample).order_by(Sample.placement)).all()
        templates = db.scalars(select(Template)).all()
    assert (enrolment.subject_id, enrolment.modality, enrolment.finger, enrolment.replaced_at) == (subject, "fingerprint", 7, None)
    assert [s.placement for s in samples] == [1, 2, 3] and len(templates) == 3
    assert [c["name"] for c in samples[0].checks] == ["size", "resolution", "ridge texture", "fine detail", "quality"]
    assert samples[0].checks[-1]["score"] == 64
    for sample in samples:
        assert sample.data[:4] == b"MBS1" and b"FAKEPNG" not in sample.data
        assert keyring.open_sealed(keys, keyring.SAMPLE, sample.id.bytes + subject.bytes, sample.data).startswith(b"FAKEPNG:")
        with pytest.raises(keyring.KeysError):  # bound to its subject (H25): it does not open for another person
            keyring.open_sealed(keys, keyring.SAMPLE, sample.id.bytes + uuid.uuid4().bytes, sample.data)
    template = templates[0]
    assert template.algorithm == "opencv-sift" and template.version == "606c8d33a7a27570b5bb55cca8248259b9b6ba8a"
    row = template.id.bytes + subject.bytes + b"opencv-sift"
    assert keyring.open_sealed(keys, keyring.TEMPLATE, row, template.data).startswith(b"TEMPLATE:A")
    with pytest.raises(keyring.KeysError):  # and to its row
        keyring.open_sealed(keys, keyring.TEMPLATE, uuid.uuid4().bytes + subject.bytes + b"opencv-sift", template.data)
    me = fp_client.get("/api/me", headers=auth(token)).json()
    assert me["modalities"]["fingerprint"] == {"enrolled": True, "fingers": [7]}


def test_a_capture_below_the_quality_minimum_is_not_kept(fp_client, script, databases):
    token = user(fp_client)
    plan(script, finger("q20:A0"), LIFT, finger("q255:A9"), LIFT, *placements("q40:A1", "q35:A2", "q99:A3"))
    events = enrol(fp_client, token)
    rejected = [e for e in events if e["type"] == "rejected"]
    assert [(e["score"], e["minimum"]) for e in rejected] == [(20, 35), (None, 35)]
    assert rejected[0]["checks"][-1] == {"name": "quality", "passed": False, "detail": "NFIQ 2 score 20 (at least 35)", "score": 20}
    assert events[-1]["type"] == "saved"
    with Session(databases.biometric) as db:
        assert [s.placement for s in db.scalars(select(Sample).order_by(Sample.placement))] == [1, 2, 3]


def test_without_three_matching_placements_one_more_is_asked_for(fp_client, script, databases):
    token = user(fp_client)
    plan(script, *placements("q60:A1", "q60:A2", "q60:B1", "q60:A3"))
    events = enrol(fp_client, token)
    assert "another_placement" in kinds(events)
    saved = events[-1]
    assert saved["type"] == "saved" and saved["not_kept"] == [3]
    assert [s["placement"] for s in saved["samples"]] == [1, 2, 4]
    with Session(databases.biometric) as db:
        assert [s.placement for s in db.scalars(select(Sample).order_by(Sample.placement))] == [1, 2, 4]


def test_the_enrolment_stops_when_placements_never_match(fp_client, script, databases):
    token = user(fp_client)
    plan(script, *placements(*(f"q60:{letter}1" for letter in "ABCDEF")))
    events = enrol(fp_client, token)
    assert events[-1] == {"type": "failed", "error": "placements_do_not_match"}
    assert kinds(events).count("kept") == 6
    with Session(databases.biometric) as db:
        assert db.scalars(select(Enrolment)).all() == []


def test_a_new_enrolment_of_the_same_finger_replaces_the_old_one(fp_client, script, databases):
    token = user(fp_client)
    plan(script, *placements("q60:A1", "q60:A2", "q60:A3"))
    assert enrol(fp_client, token)[-1]["type"] == "saved"
    plan(script, *placements("q60:A4", "q60:A5", "q60:A6"))
    second = enrol(fp_client, token)[-1]
    assert second["enrolment"]["replaced_previous"] is True
    with Session(databases.biometric) as db:
        rows = db.scalars(select(Enrolment).order_by(Enrolment.created_at)).all()
        assert len(rows) == 2 and rows[0].replaced_at is not None and rows[1].replaced_at is None
        assert len(db.scalars(select(Sample)).all()) == 6  # the old findings stay
    assert fp_client.get("/api/me", headers=auth(token)).json()["modalities"]["fingerprint"]["fingers"] == [7]


def test_deleting_a_finger_erases_its_enrolments_and_nothing_else(fp_client, script, databases):
    """H34: the current enrolment and those it replaced go, with their captures and templates; other fingers
    and other people stay."""
    token = user(fp_client)
    for labels, position in ((("q60:A1", "q60:A2", "q60:A3"), 7), (("q60:A4", "q60:A5", "q60:A6"), 7),
                             (("q60:B1", "q60:B2", "q60:B3"), 2)):
        plan(script, *placements(*labels))
        assert enrol(fp_client, token, position)[-1]["type"] == "saved"
    register(fp_client, username="dana", email="dana@example.org", national_id="000000018", phone="052-765-4321")
    other = sign_in(fp_client, "dana")
    plan(script, *placements("q60:C1", "q60:C2", "q60:C3"))
    assert enrol(fp_client, other, 7)[-1]["type"] == "saved"

    assert fp_client.delete("/api/fingerprint/fingers/7", headers=auth(token)).status_code == 204
    assert fp_client.get("/api/me", headers=auth(token)).json()["modalities"]["fingerprint"] == {"enrolled": True, "fingers": [2]}
    assert fp_client.get("/api/me", headers=auth(other)).json()["modalities"]["fingerprint"]["fingers"] == [7]
    with Session(databases.biometric) as db:
        assert sorted(e.finger for e in db.scalars(select(Enrolment))) == [2, 7]  # the user's 2 and dana's 7
        assert len(db.scalars(select(Sample)).all()) == 6 and len(db.scalars(select(Template)).all()) == 6
    assert error(fp_client.delete("/api/fingerprint/fingers/7", headers=auth(token))) == (404, "not_enrolled")
    assert fp_client.delete("/api/fingerprint/fingers/11", headers=auth(token)).status_code == 422
    admin = administrator(fp_client, databases)
    assert error(fp_client.delete("/api/fingerprint/fingers/2", headers=auth(admin))) == (403, "forbidden")
    assert fp_client.delete("/api/fingerprint/fingers/2", headers=auth(token)).status_code == 204
    assert fp_client.get("/api/me", headers=auth(token)).json()["modalities"]["fingerprint"] == {"enrolled": False, "fingers": []}


def test_oem_status_110_is_retried_once(fp_client, script):
    token = user(fp_client)
    plan(script, {"exit": 2, "stderr": "FXOEM_CaptureImage failed with OEM status 110."}, *placements("q60:A1", "q60:A2", "q60:A3"))
    assert enrol(fp_client, token)[-1]["type"] == "saved"
    assert script.with_suffix(".log").read_text(encoding="utf-8").splitlines()[:2] == ["finger", "finger"]


def test_scanner_failures_end_the_enrolment(fp_client, script):
    token = user(fp_client)
    plan(script, {"exit": 3})
    assert enrol(fp_client, token)[-1] == {"type": "failed", "error": "no_finger"}
    plan(script, {"exit": 2, "stderr": "FXOEM_OpenChannel failed with OEM status 4."})
    assert enrol(fp_client, token)[-1] == {"type": "failed", "error": "scanner_failed"}
    plan(script, {"exit": 2, "stderr": "Another native scanner command is running."})
    assert enrol(fp_client, token)[-1] == {"type": "failed", "error": "scanner_busy"}


def test_an_engine_that_cannot_start_ends_the_enrolment(databases, keys, outbox, script):
    service = service_for(script, sift=[PYTHON, "-c", "import sys; sys.exit(1)"])
    try:
        with TestClient(base_url="http://127.0.0.1", app=create_app(databases, keys, outbox, service)) as client:
            token = user(client)
            assert enrol(client, token)[-1] == {"type": "failed", "error": "engine_unavailable"}
    finally:
        service.close()


def test_a_defined_comparison_failure_scores_zero_in_the_enrolment(fp_client, script, service, monkeypatch):
    """The referee counts the research's defined comparison failures as zero, as verification does (H10, H35)."""
    token = user(fp_client)
    original = service.sift.request

    def fail_one_pair(header, parts):
        if header["op"] == "compare" and parts == [b"TEMPLATE:A2", b"TEMPLATE:A1"]:
            return {"status": "failure", "reason": "insufficient_features", "score": None}, []
        return original(header, parts)

    monkeypatch.setattr(service.sift, "request", fail_one_pair)
    plan(script, *placements("q64:A1", "q64:A2", "q64:A3", "q64:A4"))
    events = enrol(fp_client, token)
    kept = [event for event in events if event["type"] == "kept"]
    assert kept[1]["pairs"] == [{"probe": 2, "reference": 1, "score": 0, "accepted": False}]
    saved = events[-1]
    assert saved["type"] == "saved" and saved["not_kept"] == [2]
    assert [(p["probe"], p["reference"], p["score"]) for p in saved["pairs"]] == [(3, 1, 90), (4, 1, 90), (4, 3, 90)]


def test_a_reply_that_is_not_a_comparison_ends_the_enrolment(fp_client, script, service, databases, monkeypatch):
    """An engine reply without a valid status and score is the engine's failure, never a non-match (H10, H35)."""
    token = user(fp_client)
    original = service.sift.request

    def garbled(header, parts):
        if header["op"] == "compare":
            return {"status": "ok", "score": -3}, []
        return original(header, parts)

    monkeypatch.setattr(service.sift, "request", garbled)
    plan(script, *placements("q64:A1", "q64:A2", "q64:A3"))
    events = enrol(fp_client, token)
    assert kinds(events) == ["started", "place", "kept", "lift", "place", "failed"]
    assert events[-1] == {"type": "failed", "error": "engine_unavailable"}
    with Session(databases.biometric) as db:
        assert db.scalars(select(Enrolment)).all() == []


def test_only_users_enrol_and_only_when_the_service_is_set_up(fp_client, client, databases):
    assert error(fp_client.post("/api/fingerprint/enrolments", json={"finger": 7})) == (401, "not_signed_in")
    admin = administrator(fp_client, databases)
    assert error(fp_client.post("/api/fingerprint/enrolments", json={"finger": 7}, headers=auth(admin))) == (403, "forbidden")
    token = user(fp_client)
    for position in (0, 11):
        assert fp_client.post("/api/fingerprint/enrolments", json={"finger": position}, headers=auth(token)).status_code == 422
    register(client, username="dana", email="dana@example.org", national_id="000000018", phone="052-765-4321")
    other = sign_in(client, "dana")
    assert error(client.post("/api/fingerprint/enrolments", json={"finger": 7}, headers=auth(other))) == (503, "fingerprint_unavailable")


def test_a_cancelled_run_stops_the_scanner_at_once(script):
    plan(script, {"hang": True})
    scanner, run, outcome = Scanner([PYTHON, str(FAKES / "fake_scanner.py"), "--script", str(script)]), ScannerRun(), []

    def acquire():
        try:
            scanner.acquire("finger", 60, lambda header: outcome.append(header["event"]), run)
        except ScannerError as e:
            outcome.append(e.code)

    worker = threading.Thread(target=acquire)
    started = time.monotonic()
    worker.start()
    while "ready" not in outcome and time.monotonic() - started < 20:
        time.sleep(0.05)
    run.cancel()
    worker.join(20)
    assert outcome == ["ready", "cancelled"] and time.monotonic() - started < 20
    assert script.with_suffix(".closed").read_text(encoding="utf-8") == "native cleanup"
    assert run.process is None and run._stop_timer is None


def test_a_scanner_ignoring_cancellation_is_stopped_after_the_grace_period(script, monkeypatch):
    from mbs import engines
    monkeypatch.setattr(engines, "SCANNER_STOP_GRACE_S", 0.2)
    plan(script, {"hang": True, "ignore_cancel": True})
    scanner = Scanner([PYTHON, str(FAKES / "fake_scanner.py"), "--script", str(script)])
    run = ScannerRun()
    ready = threading.Event()
    outcome = []

    def acquire():
        try:
            scanner.acquire("finger", 60, lambda header: ready.set(), run)
        except ScannerError as e:
            outcome.append(e.code)

    worker = threading.Thread(target=acquire)
    worker.start()
    assert ready.wait(10)
    run.cancel()
    run.cancel()  # repeated cancellation must not create another timer
    worker.join(10)
    assert not worker.is_alive() and outcome == ["cancelled"]
    assert not script.with_suffix(".closed").exists()
    assert run.process is None and run._stop_timer is None


def test_a_stuck_oem_connection_is_reported_after_one_retry(script):
    from mbs.engines import ScannerError
    failure = {"exit": 2, "stderr": "FXOEM_OpenChannel failed with OEM status 110."}
    plan(script, failure, failure)
    scanner = Scanner([PYTHON, str(FAKES / "fake_scanner.py"), "--script", str(script)])
    with pytest.raises(ScannerError) as error:
        scanner.acquire("finger", 60, lambda header: None, ScannerRun())
    assert error.value.code == "scanner_connection_failed"
    assert script.with_suffix(".log").read_text(encoding="utf-8").splitlines() == ["finger", "finger"]


def test_the_algorithms_hold_h16s_thresholds(databases):
    with Session(databases.biometric) as db:
        rows = {a.code: (a.modality, a.threshold, a.threshold_provisional) for a in db.scalars(select(Algorithm))}
    assert rows == {"opencv-sift": ("fingerprint", 57, False), "pore-sift": ("fingerprint", 37, True),
                    "learned-pore": ("fingerprint", 21, True), "fusion": ("fingerprint", None, True),
                    "sface": ("face", 0.363, False), "ecapa-voxceleb": ("voice", 0.25, False)}  # H48, H54


def test_three_are_chosen_by_their_lowest_pair_score():
    kept = [Kept(i + 1, None, b"", [], 60, b"", 3, b"", b"") for i in range(4)]
    scores = {(0, 1): 80, (0, 2): 58, (1, 2): 70, (0, 3): 90, (1, 3): 88, (2, 3): 10}
    assert best_three(kept, scores, 57) == (0, 1, 3)
    assert best_three(kept[:3], {(0, 1): 80, (0, 2): 57, (1, 2): 70}, 57) is None  # "above" the threshold (H16)
