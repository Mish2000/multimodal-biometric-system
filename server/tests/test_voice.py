"""Voice enrolment (H17, H25, H54) against a real PostgreSQL, with the voice engine replaced by a stand-in that
speaks its real protocol (tests/fakes/fake_voice_engine.py). Recordings here are labels, never a person's
voice; the real engine's measurements are tested in engines/test_voice.py."""

from __future__ import annotations

import base64
import json
import math
import random
import struct
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from mbs import accounts
from mbs import keys as keyring
from mbs.api import create_app
from mbs.engines import Engine
from mbs.models import Algorithm, Enrolment, Sample, Template
from mbs.voice import VoiceService

from test_api import administrator, auth, error, register, sign_in

FAKES = Path(__file__).resolve().parent / "fakes"
PYTHON = sys.executable
ECAPA_SHA256 = "0575cb64845e6b9a10db9bcb74d5ac32b326b8dc90352671d345e2ee3d0126a2"
CHECKS = ["length", "speech", "clipping"]


def service_with(*options: str) -> VoiceService:
    return VoiceService(Engine("voice", [PYTHON, str(FAKES / "fake_voice_engine.py"), *options]))


@pytest.fixture
def voices():
    service = service_with()
    yield service
    service.close()


@pytest.fixture
def voice_client(databases, keys, outbox, voices):
    with TestClient(create_app(databases, keys, outbox, voices=voices)) as client:
        yield client


def raw(person="a", variant=0, **measured) -> bytes:
    return b"FAKEVOICE" + json.dumps({"person": person, "variant": variant, **measured}).encode()


def recording(*args, **kwargs) -> str:
    return base64.b64encode(raw(*args, **kwargs)).decode()


def made(*recordings: str, start: datetime | None = None, step_s: int = 15) -> dict:
    start = start or datetime.now(timezone.utc) - timedelta(minutes=2)
    return {"recordings": [{"recording": item, "captured_at": (start + timedelta(seconds=step_s * i)).isoformat()}
                           for i, item in enumerate(recordings)]}


def user(client) -> str:
    assert register(client).status_code == 201
    return sign_in(client)


def fake_embedding(person: str, variant: int) -> list[float]:
    """The stand-in's embedding, as float32 values."""
    base, change = random.Random(f"voice:{person}"), random.Random(f"voice:{person}:{variant}")
    values = [base.gauss(0, 1) + 0.15 * change.gauss(0, 1) for _ in range(192)]
    return list(struct.unpack("<192f", struct.pack("<192f", *values)))


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return dot / math.sqrt(sum(x * x for x in a) * sum(y * y for y in b))


def subject_of(client, databases, keys, token):
    account_id = client.get("/api/me", headers=auth(token)).json()["account"]["id"]
    return accounts.subject_of(databases, keys, uuid.UUID(account_id))


def test_the_voice_joins_the_algorithm_table_with_its_pinned_model(databases):
    with Session(databases.biometric) as db:
        row = db.get(Algorithm, "ecapa-voxceleb")
        assert (row.modality, row.version, row.threshold, row.threshold_provisional, row.threshold_origin) == (
            "voice", ECAPA_SHA256, 0.25, False, "SpeechBrain's verification threshold")


def test_the_method_card_comes_from_the_algorithm_table(voice_client, client):
    token = user(voice_client)
    card = voice_client.get("/api/voice/method", headers=auth(token)).json()
    assert card == {"code": "ecapa-voxceleb", "threshold": 0.25, "threshold_provisional": False,
                    "threshold_origin": "SpeechBrain's verification threshold", "available": True,
                    "recordings": 3, "most_kept": 6, "embedding_length": 192, "sample_rate": 16000,
                    "recording_seconds": 5, "duration_minimum": 3.0, "duration_maximum": 30.0,
                    "speech_minimum": 2.0, "clipped_maximum": 0.001}
    assert client.get("/api/voice/method", headers=auth(sign_in(client))).json()["available"] is False


def test_the_voice_routes_are_only_for_signed_in_users(voice_client, databases):
    routes = [("GET", "/api/voice/method", None), ("POST", "/api/voice/checks", {"recording": recording()}),
              ("POST", "/api/voice/enrolments", made(recording(), recording(variant=1), recording(variant=2))),
              ("DELETE", "/api/voice/enrolment", None)]
    admin = administrator(voice_client, databases)
    for method, path, body in routes:
        assert error(voice_client.request(method, path, json=body)) == (401, "not_signed_in")
        assert error(voice_client.request(method, path, json=body, headers=auth(admin))) == (403, "forbidden")


def test_without_the_voice_environment_the_voice_is_unavailable(client):
    token = user(client)
    for path, body in (("/api/voice/checks", {"recording": recording()}),
                       ("/api/voice/enrolments", made(recording(), recording(variant=1), recording(variant=2)))):
        assert error(client.post(path, json=body, headers=auth(token))) == (503, "voice_unavailable")


def test_a_recording_that_passes_names_its_measured_values(voice_client, databases):
    token = user(voice_client)
    answer = voice_client.post("/api/voice/checks", json={"recording": recording()}, headers=auth(token)).json()
    assert answer["passed"] is True and [c["name"] for c in answer["checks"]] == CHECKS
    length, speech, clipping = answer["checks"]
    assert (length["seconds"], length["minimum"], length["maximum"]) == (5.0, 3.0, 30.0)
    assert (speech["seconds"], speech["minimum"], speech["above_noise"]) == (3.6, 2.0, 34.0)
    assert (clipping["share"], clipping["maximum"]) == (0.0, 0.001)
    assert (answer["duration"], answer["speech"]) == (5.0, 3.6)
    with Session(databases.biometric) as db:
        assert db.scalars(select(Sample)).all() == []  # a check keeps nothing


@pytest.mark.parametrize("measured, failed", [
    ({"duration": 2.5, "speech": 2.2}, ["length"]),
    ({"duration": 31.0}, ["length"]),
    ({"speech": 1.9}, ["speech"]),
    ({"speech": 0.0, "speech_level": -100.0}, ["speech"]),
    ({"clipped": 0.002}, ["clipping"]),
    ({"duration": 0.5, "speech": 0.4}, ["length", "speech"]),
])
def test_a_recording_that_fails_a_check_names_it(voice_client, measured, failed):
    token = user(voice_client)
    answer = voice_client.post("/api/voice/checks", json={"recording": recording(**measured)}, headers=auth(token)).json()
    assert answer["passed"] is False
    assert [c["name"] for c in answer["checks"] if not c["passed"]] == failed


def test_data_that_is_not_a_recording_is_refused(voice_client):
    token = user(voice_client)
    for body in ({"recording": base64.b64encode(b"not a recording").decode()}, {"recording": "not base64!"},
                 {"recording": ""}):
        assert error(voice_client.post("/api/voice/checks", json=body, headers=auth(token))) == (422, "invalid_recording")
    too_large = base64.b64encode(b"FAKEVOICE{}" + b" " * (1 << 20)).decode()
    assert voice_client.post("/api/voice/checks", json={"recording": too_large}, headers=auth(token)).status_code == 422
    assert voice_client.post("/api/voice/checks", json={"recording": recording(), "source": "file"},
                             headers=auth(token)).status_code == 422  # enrolment's checks take no files (H27)


def test_three_matching_recordings_enrol_the_voice(voice_client, databases, keys):
    token = user(voice_client)
    recordings = [raw(variant=v) for v in range(3)]
    answer = voice_client.post("/api/voice/enrolments", headers=auth(token),
                               json=made(*(base64.b64encode(r).decode() for r in recordings)))
    assert answer.status_code == 201, answer.text
    saved = answer.json()
    assert saved["status"] == "saved" and saved["enrolment"]["replaced_previous"] is False and saved["not_kept"] == []
    assert [s["placement"] for s in saved["samples"]] == [1, 2, 3]
    assert all(s["duration_ms"] == 5000 and [c["name"] for c in s["checks"]] == CHECKS for s in saved["samples"])
    expected = [fake_embedding("a", v) for v in range(3)]
    assert len(saved["pairs"]) == 3 and all(pair["accepted"] for pair in saved["pairs"])
    for pair in saved["pairs"]:  # pgvector's cosine similarity, as for every face score
        assert pair["score"] == pytest.approx(cosine(expected[pair["probe"] - 1], expected[pair["reference"] - 1]), abs=1e-6)
    assert {(t["algorithm"], t["version"], t["embedding_length"]) for t in saved["templates"]} == {
        ("ecapa-voxceleb", ECAPA_SHA256, 192)}
    subject = subject_of(voice_client, databases, keys, token)
    with Session(databases.biometric) as db:
        enrolment = db.scalars(select(Enrolment)).one()
        assert (enrolment.subject_id, enrolment.modality, enrolment.finger, enrolment.replaced_at) == (subject, "voice", None, None)
        samples = db.scalars(select(Sample).order_by(Sample.placement)).all()
        assert [(s.media_type, s.width, s.height, s.ppi, s.duration_ms) for s in samples] == [
            ("audio/wav", None, None, None, 5000)] * 3
        assert [c["name"] for c in samples[0].checks] == CHECKS
        for sample, original in zip(samples, recordings):  # the engine's WAV, sealed to its row and subject
            assert keyring.open_sealed(keys, keyring.SAMPLE, sample.id.bytes + subject.bytes, sample.data) == b"RIFFWAV:" + original
        templates = db.scalars(select(Template)).all()
        assert {(t.algorithm, t.version, t.data) for t in templates} == {("ecapa-voxceleb", ECAPA_SHA256, None)}
        by_sample = {t.sample_id: t.embedding for t in templates}
        assert [by_sample[s.id] for s in samples] == expected
    modalities = voice_client.get("/api/me", headers=auth(token)).json()["modalities"]
    assert modalities["voice"]["enrolled"] is True and modalities["voice"]["enrolled_at"] == saved["enrolment"]["created_at"]
    assert modalities["face"] == {"enrolled": False}


def test_another_recording_is_asked_for_until_three_match(voice_client, databases):
    token = user(voice_client)
    first = [recording(variant=0), recording(variant=1), recording(person="b")]
    answer = voice_client.post("/api/voice/enrolments", json=made(*first), headers=auth(token))
    assert answer.status_code == 200
    another = answer.json()
    assert another["status"] == "another" and another["kept"] == 3 and another["threshold"] == 0.25
    assert {(p["probe"], p["reference"]): p["accepted"] for p in another["pairs"]} == {(2, 1): True, (3, 1): False, (3, 2): False}
    with Session(databases.biometric) as db:
        assert db.scalars(select(Enrolment)).all() == []
    saved = voice_client.post("/api/voice/enrolments", json=made(*first, recording(variant=2)), headers=auth(token)).json()
    assert saved["status"] == "saved" and saved["not_kept"] == [3]
    assert [s["placement"] for s in saved["samples"]] == [1, 2, 4]
    assert sorted((p["probe"], p["reference"]) for p in saved["pairs"]) == [(2, 1), (4, 1), (4, 2)]


def test_six_recordings_without_three_that_match_end_unsaved(voice_client, databases):
    token = user(voice_client)
    answer = voice_client.post("/api/voice/enrolments", headers=auth(token),
                               json=made(*(recording(person=p) for p in "abcdef"))).json()
    assert answer["status"] == "failed" and answer["error"] == "recordings_do_not_match" and len(answer["pairs"]) == 15
    with Session(databases.biometric) as db:
        assert db.scalars(select(Enrolment)).all() == []


def test_a_recording_that_fails_its_checks_refuses_the_enrolment(voice_client, databases):
    token = user(voice_client)
    quiet = recording(speech=0.8)
    answer = voice_client.post("/api/voice/enrolments", json=made(recording(), quiet, recording(variant=2)), headers=auth(token))
    assert error(answer) == (422, "recording_rejected") and answer.json()["index"] == 1
    assert [c["name"] for c in answer.json()["checks"] if not c["passed"]] == ["speech"]
    with Session(databases.biometric) as db:
        assert db.scalars(select(Sample)).all() == []


def test_enrolling_again_replaces_the_voice_and_deleting_erases_every_enrolment(voice_client, databases):
    token = user(voice_client)
    three = made(recording(variant=0), recording(variant=1), recording(variant=2))
    assert voice_client.post("/api/voice/enrolments", json=three, headers=auth(token)).status_code == 201
    again = voice_client.post("/api/voice/enrolments", json=three, headers=auth(token)).json()
    assert again["enrolment"]["replaced_previous"] is True
    with Session(databases.biometric) as db:
        enrolments = db.scalars(select(Enrolment).order_by(Enrolment.created_at)).all()
        assert len(enrolments) == 2 and enrolments[0].replaced_at is not None and enrolments[1].replaced_at is None
        assert len(db.scalars(select(Template)).all()) == 6
    assert voice_client.delete("/api/voice/enrolment", headers=auth(token)).status_code == 204
    with Session(databases.biometric) as db:
        assert db.scalars(select(Enrolment)).all() == [] and db.scalars(select(Sample)).all() == []
        assert db.scalars(select(Template)).all() == []
    assert error(voice_client.delete("/api/voice/enrolment", headers=auth(token))) == (404, "not_enrolled")
    assert voice_client.get("/api/me", headers=auth(token)).json()["modalities"]["voice"] == {"enrolled": False}


def test_an_enrolment_needs_three_to_six_recordings_made_in_order_in_the_last_half_hour(voice_client):
    token = user(voice_client)
    three = [recording(variant=v) for v in range(3)]
    now = datetime.now(timezone.utc)
    for body in (made(*three[:2]), made(*(three * 3)[:7]), made(*three, start=now + timedelta(minutes=5)),
                 made(*three, start=now - timedelta(hours=2)), made(*three, step_s=-10)):
        assert voice_client.post("/api/voice/enrolments", json=body, headers=auth(token)).status_code == 422
    naive = made(*three)
    for item in naive["recordings"]:
        item["captured_at"] = item["captured_at"].replace("+00:00", "")
    assert voice_client.post("/api/voice/enrolments", json=naive, headers=auth(token)).status_code == 422


def test_a_model_other_than_the_pinned_one_is_refused(databases, keys, outbox):
    service = service_with("--ecapa-sha256", "0" * 64)
    try:
        with TestClient(create_app(databases, keys, outbox, voices=service)) as client:
            token = user(client)
            body = made(recording(variant=0), recording(variant=1), recording(variant=2))
            assert error(client.post("/api/voice/enrolments", json=body, headers=auth(token))) == (503, "method_version_differs")
    finally:
        service.close()


@pytest.mark.parametrize("option", ["--broken", "--bad-rate"])
def test_an_engine_answer_that_breaks_the_rules_is_a_server_failure(databases, keys, outbox, option):
    service = service_with(option)
    try:
        with TestClient(create_app(databases, keys, outbox, voices=service)) as client:
            token = user(client)
            assert error(client.post("/api/voice/checks", json={"recording": recording()}, headers=auth(token))) == (
                503, "engine_unavailable")
    finally:
        service.close()
