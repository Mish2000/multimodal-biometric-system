"""Voice identification (H56) against a real PostgreSQL, with the voice engine replaced by the stand-in of
tests/fakes/fake_voice_engine.py: a gallery of several fake people, each a fixed random direction. Recordings here are
labels, never a person's voice."""

from __future__ import annotations

import base64
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from mbs import keys as keyring
from mbs import voice
from mbs.api import create_app
from mbs.models import Account, Algorithm, Attempt, Enrolment, Sample, Template

from test_api import administrator, auth, error, register, sign_in
from test_face import image, service_with as face_service_with, taken
from test_face_identification import national_id
from test_voice import (cosine, fake_embedding, made, raw, recording, service_with, subject_of, user,  # noqa: F401
                        voice_client, voices)

ROUTE = "/api/voice/identifications"


def enrolled(client) -> str:
    """A signed-in user whose voice is enrolled from three recordings of person "a"."""
    token = user(client)
    answer = client.post("/api/voice/enrolments", json=made(*(recording(variant=v) for v in (0, 1, 2))), headers=auth(token))
    assert answer.status_code == 201, answer.text
    return token


def other(client, name: str, n: int, person: str, variants=(0, 1, 2)) -> str:
    """Another registered user, whose voice is enrolled from three recordings of the fake `person`."""
    assert register(client, username=name, email=f"{name}@example.org", national_id=national_id(n),
                    phone=f"0521234{n:03d}").status_code == 201
    token = sign_in(client, name)
    answer = client.post("/api/voice/enrolments", json=made(*(recording(person, v) for v in variants)), headers=auth(token))
    assert answer.status_code == 201, answer.text
    return token


def identify(client, token, **kwargs):
    return client.post(ROUTE, json={"recording": recording(**kwargs)}, headers=auth(token))


def attempts(databases) -> list[Attempt]:
    with Session(databases.biometric) as db:
        return db.scalars(select(Attempt).order_by(Attempt.at)).all()


def highest(probe: str, person: str, variants=(0, 1, 2)) -> tuple[float, int]:
    """The stand-in's highest similarity of a new recording (variant 3) to an enrolment, and its earliest recording."""
    new = fake_embedding(probe, 3)
    scores = [cosine(new, fake_embedding(person, v)) for v in variants]
    return max(scores), scores.index(max(scores)) + 1


@pytest.mark.parametrize("probe,found", [("a", True), ("b", True), ("z", False)])
def test_identification_ranks_the_enrolments_and_keeps_other_people_anonymous(voice_client, databases, keys, probe, found):
    tokens = {"a": enrolled(voice_client), "b": other(voice_client, "dana", 1, "b"), "c": other(voice_client, "noa", 2, "c")}
    answer = identify(voice_client, tokens["a"], person=probe, variant=3)
    assert answer.status_code == 200, answer.text
    result = answer.json()
    expected = {person: highest(probe, person)[0] for person in "abc"}
    order = sorted(expected, key=expected.get, reverse=True)
    assert result["status"] == "identified" and result["accepted"] is found is (expected[order[0]] > 0.25)
    assert (result["gallery_size"], result["enrolments"], result["tied_leaders"], result["threshold"]) == (9, 3, 1, 0.25)
    assert (result["threshold_origin"], result["threshold_provisional"], result["source"]) == (
        "SpeechBrain's verification threshold", False, "device")
    assert [c["rank"] for c in result["candidates"]] == [1, 2, 3]
    assert [c["own"] for c in result["candidates"]] == [person == "a" for person in order]
    for candidate, person in zip(result["candidates"], order):  # pgvector's cosine similarity, as at enrolment
        assert candidate["score"] == pytest.approx(expected[person], abs=1e-6)
        assert candidate["accepted"] is (candidate["score"] > 0.25)
        assert set(candidate) == {"rank", "own", "score", "accepted"}
    assert result["score"] == result["candidates"][0]["score"]
    # The caller's own enrolled recording is sent beside the new one, wherever it ranks among the five.
    assert result["view"]["rank"] == order.index("a") + 1 and result["view"]["placement"] == highest(probe, "a")[1]
    assert base64.b64decode(result["view"]["reference"]) == b"RIFFWAV:" + raw("a", highest(probe, "a")[1] - 1)
    assert set(result["view"]) == {"rank", "placement", "reference"}
    (attempt,) = attempts(databases)
    subject = subject_of(voice_client, databases, keys, tokens["a"])
    leader = subject_of(voice_client, databases, keys, tokens[order[0]])
    with Session(databases.biometric) as db:
        assert db.get(Enrolment, attempt.top_enrolment_id).subject_id == leader
        hidden = [*db.scalars(select(Enrolment.id)), *db.scalars(select(Enrolment.subject_id)),
                  *db.scalars(select(Sample.id)), *db.scalars(select(Template.id))]
    assert (attempt.subject_id, attempt.modality, attempt.mode, attempt.algorithm, attempt.enrolment_id) == \
           (subject, "voice", "identify", "ecapa-voxceleb", None)
    assert (attempt.gallery_size, attempt.accepted, attempt.threshold, attempt.source) == (9, found, 0.25, "device")
    assert attempt.score == result["score"] and attempt.duration_ms == result["duration_ms"] >= 0
    assert str(attempt.id) == result["attempt_id"]
    assert keyring.open_sealed(keys, keyring.PROBE, attempt.id.bytes + subject.bytes, attempt.probe) == \
           b"RIFFWAV:" + raw(probe, 3)
    with pytest.raises(keyring.KeysError):  # sealed to the caller's subject only
        keyring.open_sealed(keys, keyring.PROBE, attempt.id.bytes + uuid.uuid4().bytes, attempt.probe)
    wire = answer.text  # H18: no name, address or identifier of anyone, and no stored recording but the caller's own
    assert "dana" not in wire and "noa" not in wire and "example.org" not in wire
    assert all(str(identifier) not in wire for identifier in hidden)


def test_identification_needs_a_signed_in_user_with_an_enrolled_voice_and_the_engine(voice_client, client, databases):
    body = {"recording": recording()}
    assert error(voice_client.post(ROUTE, json=body)) == (401, "not_signed_in")
    admin = administrator(voice_client, databases)
    assert error(voice_client.post(ROUTE, json=body, headers=auth(admin))) == (403, "forbidden")
    token = user(voice_client)  # both applications share the database, so the session holds for both
    assert error(client.post(ROUTE, json=body, headers=auth(token))) == (503, "voice_unavailable")
    assert voice_client.post(ROUTE, json={**body, "source": "upload"}, headers=auth(token)).status_code == 422  # device or file (H57)
    other(voice_client, "dana", 1, "b")
    assert error(identify(voice_client, token, person="b")) == (409, "not_enrolled")  # H15, before any comparison
    assert attempts(databases) == []


def test_a_refused_recording_makes_no_attempt(voice_client, databases):
    token = enrolled(voice_client)
    result = identify(voice_client, token, speech=0.5).json()
    assert result["status"] == "rejected" and result["source"] == "device"
    assert [c["name"] for c in result["checks"] if not c["passed"]] == ["speech"]
    assert attempts(databases) == []


def test_the_gallery_has_only_the_current_voice_enrolments_of_active_user_accounts(databases, keys, outbox):
    faces, voices_ = face_service_with(), service_with()
    try:
        with TestClient(base_url="http://127.0.0.1", app=create_app(databases, keys, outbox, faces=faces, voices=voices_)) as client:
            token = enrolled(client)
            again = client.post("/api/voice/enrolments", json=made(*(recording(variant=v) for v in (4, 5, 6))),
                                headers=auth(token))
            assert again.status_code == 201  # the first enrolment is replaced and stays stored
            other(client, "dana", 1, "b")
            with Session(databases.accounts) as db, db.begin():
                db.scalar(select(Account).where(Account.username == "dana")).status = "disabled"
            assert register(client, username="noa", email="noa@example.org", national_id=national_id(2),
                            phone="0521234002").status_code == 201
            noa = sign_in(client, "noa")  # a face enrolment only, never in a voice gallery
            assert client.post("/api/face/enrolments", json=taken(*(image("c", v) for v in (0, 1, 2))),
                               headers=auth(noa)).status_code == 201
            result = identify(client, token, person="b", variant=3).json()
            assert (result["gallery_size"], result["enrolments"], result["accepted"]) == (3, 1, False)
            assert [c["own"] for c in result["candidates"]] == [True]
            # And the face's gallery holds no voice enrolment (H50).
            face = client.post("/api/face/identifications", json={"image": image("c", 3)}, headers=auth(noa)).json()
            assert (face["gallery_size"], face["enrolments"], [c["own"] for c in face["candidates"]]) == (3, 1, [True])
            assert error(client.post("/api/face/identifications", json={"image": image("c", 3)}, headers=auth(token))) == (
                409, "not_enrolled")
    finally:
        faces.close()
        voices_.close()


def test_equal_leaders_are_a_tie_in_a_fixed_order(voice_client, databases):
    token = enrolled(voice_client)
    other(voice_client, "dana", 1, "a")  # the same three recordings, so the same similarities
    results = [identify(voice_client, token, variant=3).json() for _ in range(2)]
    assert results[0]["tied_leaders"] == 2 and results[0]["accepted"] is True
    assert results[0]["candidates"][0]["score"] == results[0]["candidates"][1]["score"] == results[0]["score"]
    assert results[0]["candidates"] == results[1]["candidates"]
    with Session(databases.biometric) as db:
        leaders = set(db.scalars(select(Attempt.top_enrolment_id)))
        first = min(db.scalars(select(Enrolment.id).where(Enrolment.modality == "voice")))
    assert leaders == {first}  # the lower enrolment id, in PostgreSQL's order of uuids


def test_a_leader_equal_to_the_threshold_is_not_found(voice_client, databases):
    token = enrolled(voice_client)
    first = identify(voice_client, token, variant=3).json()
    with Session(databases.biometric) as db, db.begin():
        db.execute(update(Algorithm).where(Algorithm.code == "ecapa-voxceleb").values(threshold=first["score"]))
    second = identify(voice_client, token, variant=3).json()
    assert second["score"] == first["score"] == second["threshold"] and second["accepted"] is False
    assert second["candidates"][0]["accepted"] is False
    assert [a.accepted for a in attempts(databases)] == [True, False]


@pytest.mark.parametrize("change", ["delete", "replace", "disable", "template"])
def test_a_change_to_the_gallery_before_the_save_ends_the_search_unsaved(voice_client, databases, keys, monkeypatch, change):
    token = enrolled(voice_client)
    other_token = other(voice_client, "dana", 1, "b")
    dana = subject_of(voice_client, databases, keys, other_token)
    original = voice._repeat_view

    def changed_meanwhile(*args):
        if change == "delete":
            voice.delete_voice(databases, dana)
        elif change == "replace":
            voice_client.post("/api/voice/enrolments", json=made(*(recording("b", v) for v in (4, 5, 6))),
                              headers=auth(other_token))
        elif change == "disable":
            with Session(databases.accounts) as db, db.begin():
                db.scalar(select(Account).where(Account.username == "dana")).status = "disabled"
        else:
            with Session(databases.biometric) as db, db.begin():
                db.scalars(select(Template).join(Sample).join(Enrolment).where(Enrolment.subject_id == dana)).first() \
                    .version = "0" * 64
        return original(*args)

    monkeypatch.setattr(voice, "_repeat_view", changed_meanwhile)
    assert error(identify(voice_client, token, variant=3)) == (409, "gallery_changed")
    assert attempts(databases) == []


def test_a_new_enrolment_or_threshold_after_the_start_does_not_change_the_search(voice_client, databases, monkeypatch):
    token = enrolled(voice_client)
    original = voice._extract
    changed = []

    def meanwhile(service, data):
        if not changed:  # the new recording's extraction comes after the gallery and the threshold are fixed
            changed.append(True)
            other(voice_client, "dana", 1, "a")
            with Session(databases.biometric) as db, db.begin():
                db.execute(update(Algorithm).where(Algorithm.code == "ecapa-voxceleb").values(threshold=0.99))
        return original(service, data)

    monkeypatch.setattr(voice, "_extract", meanwhile)
    result = identify(voice_client, token, variant=3).json()
    assert (result["threshold"], result["gallery_size"], result["enrolments"], result["accepted"]) == (0.25, 3, 1, True)
    later = identify(voice_client, token, variant=3).json()
    assert (later["threshold"], later["gallery_size"], later["accepted"]) == (0.99, 6, False)


def test_deleting_the_leading_enrolment_keeps_the_attempt_and_its_recording(voice_client, databases, keys):
    token = enrolled(voice_client)
    other_token = other(voice_client, "dana", 1, "b")
    subject = subject_of(voice_client, databases, keys, token)
    result = identify(voice_client, token, person="b", variant=3).json()
    assert result["accepted"] is True and result["candidates"][0]["own"] is False
    with Session(databases.biometric) as db:
        before = db.get(Attempt, uuid.UUID(result["attempt_id"])).probe
    assert voice_client.delete("/api/voice/enrolment", headers=auth(other_token)).status_code == 204
    with Session(databases.biometric) as db:
        attempt = db.get(Attempt, uuid.UUID(result["attempt_id"]))
        assert attempt is not None and attempt.top_enrolment_id is None and attempt.probe == before
        assert attempt.accepted and attempt.gallery_size == 6
    assert keyring.open_sealed(keys, keyring.PROBE, attempt.id.bytes + subject.bytes, attempt.probe) == \
           b"RIFFWAV:" + raw("b", 3)
    # The caller's own deletion erases the voice's verification attempts; its identification attempts stay.
    assert voice_client.post("/api/voice/verifications", json={"recording": recording(variant=3)},
                             headers=auth(token)).status_code == 200
    assert identify(voice_client, token, variant=3).json()["candidates"][0]["own"] is True
    assert voice_client.delete("/api/voice/enrolment", headers=auth(token)).status_code == 204
    assert [(a.mode, a.top_enrolment_id) for a in attempts(databases)] == [("identify", None), ("identify", None)]


@pytest.mark.parametrize("fault,code", [("version", "method_version_differs"), ("missing", "gallery_templates_unavailable")])
def test_a_gallery_with_another_model_version_or_a_missing_embedding_is_refused(voice_client, databases, keys, fault, code):
    token = enrolled(voice_client)
    dana = subject_of(voice_client, databases, keys, other(voice_client, "dana", 1, "b"))
    with Session(databases.biometric) as db, db.begin():
        template = db.scalars(select(Template).join(Sample).join(Enrolment).where(Enrolment.subject_id == dana)).first()
        if fault == "version":
            template.version = "0" * 64
        else:
            db.delete(template)
    assert error(identify(voice_client, token, variant=3)) == (503, code)
    assert attempts(databases) == []


def test_five_leading_candidates_are_shown_and_the_own_recording_only_among_them(voice_client, databases):
    token = enrolled(voice_client)
    people = [f"p{n}" for n in range(1, 7)]
    for n, person in enumerate(people, 1):
        other(voice_client, f"user{n}", n, person)

    def ranking(probe: str) -> list[str]:
        best = {person: highest(probe, person)[0] for person in ["a", *people]}
        return sorted(best, key=best.get, reverse=True)

    # The stand-in's directions are fixed, so this finds the same probe every time: six others rank above the caller.
    probe = next(name for name in (f"q{n}" for n in range(500)) if ranking(name).index("a") == 6)
    result = identify(voice_client, token, person=probe, variant=3).json()
    assert (result["enrolments"], result["gallery_size"], len(result["candidates"])) == (7, 21, 5)
    assert [c["rank"] for c in result["candidates"]] == [1, 2, 3, 4, 5]
    assert not any(c["own"] for c in result["candidates"]) and "view" not in result
    shown = identify(voice_client, token, variant=3).json()
    assert shown["candidates"][0]["own"] is True and shown["view"]["rank"] == 1
    assert len(attempts(databases)) == 2


def test_a_stored_recording_that_does_not_give_its_embedding_again_saves_nothing(databases, keys, outbox):
    service = service_with("--drift")
    try:
        with TestClient(base_url="http://127.0.0.1", app=create_app(databases, keys, outbox, voices=service)) as client:
            token = enrolled(client)
            assert error(identify(client, token, variant=3)) == (503, "engine_unavailable")
    finally:
        service.close()
    assert attempts(databases) == []


def test_a_model_other_than_the_pinned_one_is_refused(databases, keys, outbox):
    first = service_with()
    try:
        with TestClient(base_url="http://127.0.0.1", app=create_app(databases, keys, outbox, voices=first)) as client:
            token = enrolled(client)
    finally:
        first.close()
    another = service_with("--ecapa-sha256", "0" * 64)
    try:
        with TestClient(base_url="http://127.0.0.1", app=create_app(databases, keys, outbox, voices=another)) as client:
            assert error(identify(client, token, variant=3)) == (503, "method_version_differs")
    finally:
        another.close()
    assert attempts(databases) == []
