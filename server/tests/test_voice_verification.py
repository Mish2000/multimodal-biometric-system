"""Voice verification (H55) against a real PostgreSQL, with the voice engine replaced by a stand-in that speaks its
real protocol (tests/fakes/fake_voice_engine.py). Recordings here are labels, never a person's voice."""

from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from mbs import keys as keyring
from mbs import voice
from mbs.api import create_app
from mbs.models import Attempt, Enrolment, Sample

from test_api import administrator, auth, error
from test_voice import cosine, fake_embedding, made, raw, recording, service_with, subject_of, user, voice_client, voices  # noqa: F401


def enrol(client, token, *recordings: str) -> dict:
    answer = client.post("/api/voice/enrolments", json=made(*(recordings or (recording(variant=0), recording(variant=1),
                                                                              recording(variant=2)))), headers=auth(token))
    assert answer.status_code == 201, answer.text
    return answer.json()


def test_the_route_is_only_for_signed_in_users_and_needs_the_engine(voice_client, client, databases):
    body = {"recording": recording()}
    assert error(voice_client.post("/api/voice/verifications", json=body)) == (401, "not_signed_in")
    admin = administrator(voice_client, databases)
    assert error(voice_client.post("/api/voice/verifications", json=body, headers=auth(admin))) == (403, "forbidden")
    token = user(voice_client)  # both applications share the database, so the session holds for both
    assert error(client.post("/api/voice/verifications", json=body, headers=auth(token))) == (503, "voice_unavailable")
    assert voice_client.post("/api/voice/verifications", json={**body, "source": "upload"},
                             headers=auth(token)).status_code == 422  # a device or a file only (H57)


def test_verification_before_an_enrolment_offers_the_enrolment(voice_client):
    assert error(voice_client.post("/api/voice/verifications", json={"recording": recording()},
                                   headers=auth(user(voice_client)))) == (409, "not_enrolled")


def test_a_matching_recording_is_saved_with_its_sealed_recording_before_the_answer(voice_client, databases, keys):
    token = user(voice_client)
    enrol(voice_client, token)
    probe = raw(variant=7)
    answer = voice_client.post("/api/voice/verifications", json={"recording": base64.b64encode(probe).decode()},
                               headers=auth(token)).json()
    assert answer["status"] == "verified" and answer["accepted"] is True and answer["source"] == "device"
    expected = [cosine(fake_embedding("a", 7), fake_embedding("a", v)) for v in range(3)]
    assert [c["placement"] for c in answer["comparisons"]] == [1, 2, 3]
    assert [c["score"] for c in answer["comparisons"]] == pytest.approx(expected, abs=1e-6)
    best = max(range(3), key=lambda i: expected[i])
    assert answer["score"] == pytest.approx(expected[best], abs=1e-6) and answer["view"]["placement"] == best + 1
    assert base64.b64decode(answer["view"]["reference"]) == b"RIFFWAV:" + raw(variant=best)  # the owner's own recording
    assert (answer["threshold"], answer["threshold_origin"], answer["threshold_provisional"]) == (
        0.25, "SpeechBrain's verification threshold", False)
    subject = subject_of(voice_client, databases, keys, token)
    with Session(databases.biometric) as db:
        attempt = db.scalars(select(Attempt)).one()
        enrolment = db.scalars(select(Enrolment)).one()
        assert (attempt.modality, attempt.mode, attempt.algorithm, attempt.enrolment_id, attempt.source) == (
            "voice", "verify", "ecapa-voxceleb", enrolment.id, "device")
        assert (attempt.score, attempt.threshold, attempt.accepted) == (pytest.approx(answer["score"]), 0.25, True)
        assert str(attempt.id) == answer["attempt_id"] and attempt.duration_ms == answer["duration_ms"] >= 0
        assert keyring.open_sealed(keys, keyring.PROBE, attempt.id.bytes + subject.bytes, attempt.probe) == b"RIFFWAV:" + probe


def test_another_persons_recording_does_not_match_and_is_saved_too(voice_client, databases):
    token = user(voice_client)
    enrol(voice_client, token)
    answer = voice_client.post("/api/voice/verifications", json={"recording": recording(person="b")}, headers=auth(token)).json()
    assert answer["status"] == "verified" and answer["accepted"] is False and answer["score"] < 0.25
    assert not any(c["accepted"] for c in answer["comparisons"])
    with Session(databases.biometric) as db:
        assert db.scalars(select(Attempt)).one().accepted is False


def test_a_refused_recording_makes_no_attempt(voice_client, databases):
    token = user(voice_client)
    enrol(voice_client, token)
    answer = voice_client.post("/api/voice/verifications", json={"recording": recording(speech=0.5)}, headers=auth(token)).json()
    assert answer["status"] == "rejected" and [c["name"] for c in answer["checks"] if not c["passed"]] == ["speech"]
    with Session(databases.biometric) as db:
        assert db.scalars(select(Attempt)).all() == []


def test_equal_scores_go_to_the_earliest_recording(voice_client):
    token = user(voice_client)
    same = recording(variant=0)
    enrol(voice_client, token, same, same, same)
    answer = voice_client.post("/api/voice/verifications", json={"recording": same}, headers=auth(token)).json()
    assert len({c["score"] for c in answer["comparisons"]}) == 1 and answer["view"]["placement"] == 1


def test_a_stored_recording_that_does_not_give_its_embedding_again_ends_unsaved(databases, keys, outbox):
    service = service_with("--drift")
    try:
        with TestClient(base_url="http://127.0.0.1", app=create_app(databases, keys, outbox, voices=service)) as client:
            token = user(client)
            enrol(client, token)
            assert error(client.post("/api/voice/verifications", json={"recording": recording()}, headers=auth(token))) == (
                503, "engine_unavailable")
            with Session(databases.biometric) as db:
                assert db.scalars(select(Attempt)).all() == []
    finally:
        service.close()


def test_a_model_other_than_the_pinned_one_is_refused(databases, keys, outbox):
    first = service_with()
    try:
        with TestClient(base_url="http://127.0.0.1", app=create_app(databases, keys, outbox, voices=first)) as client:
            token = user(client)
            enrol(client, token)
    finally:
        first.close()
    other = service_with("--ecapa-sha256", "0" * 64)
    try:
        with TestClient(base_url="http://127.0.0.1", app=create_app(databases, keys, outbox, voices=other)) as client:
            assert error(client.post("/api/voice/verifications", json={"recording": recording()}, headers=auth(token))) == (
                503, "method_version_differs")
    finally:
        other.close()


def test_an_enrolment_deleted_during_the_comparison_ends_unsaved(voice_client, databases, keys, monkeypatch):
    token = user(voice_client)
    enrol(voice_client, token)
    subject = subject_of(voice_client, databases, keys, token)
    repeat = voice._repeat_view

    def deleted_meanwhile(*args):
        view = repeat(*args)
        assert voice.delete_voice(databases, subject)
        return view

    monkeypatch.setattr(voice, "_repeat_view", deleted_meanwhile)
    assert error(voice_client.post("/api/voice/verifications", json={"recording": recording()}, headers=auth(token))) == (
        409, "enrolment_changed")
    with Session(databases.biometric) as db:
        assert db.scalars(select(Attempt)).all() == []


def test_deleting_the_voice_erases_its_verification_attempts_and_a_new_enrolment_keeps_them(voice_client, databases):
    token = user(voice_client)
    enrol(voice_client, token)
    voice_client.post("/api/voice/verifications", json={"recording": recording()}, headers=auth(token))
    enrol(voice_client, token)  # a new enrolment keeps the earlier attempts
    voice_client.post("/api/voice/verifications", json={"recording": recording()}, headers=auth(token))
    with Session(databases.biometric) as db:
        assert len(db.scalars(select(Attempt)).all()) == 2
    assert voice_client.delete("/api/voice/enrolment", headers=auth(token)).status_code == 204
    with Session(databases.biometric) as db:
        assert db.scalars(select(Attempt)).all() == [] and db.scalars(select(Sample)).all() == []
