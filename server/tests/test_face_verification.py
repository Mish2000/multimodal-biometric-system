"""Face verification (H49) against a real PostgreSQL, with the face engine replaced by the stand-in of
tests/fakes/fake_face_engine.py. Images here are labels, never pictures of a person."""

from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from mbs import face
from mbs import keys as keyring
from mbs.api import create_app
from mbs.models import Algorithm, Attempt, Enrolment, Template

from test_api import administrator, auth, error
from test_face import (cosine, face_client, faces, fake_embedding, image, raw, service_with, subject_of,  # noqa: F401
                       taken, user)


def enrolled(client, *variants: int) -> str:
    """A signed-in user whose face is enrolled from three images of person "a"."""
    token = user(client)
    answer = client.post("/api/face/enrolments", json=taken(*(image(variant=v) for v in variants or (0, 1, 2))),
                         headers=auth(token))
    assert answer.status_code == 201, answer.text
    return token


def verify(client, token, **kwargs):
    return client.post("/api/face/verifications", json={"image": image(**kwargs)}, headers=auth(token))


def attempts(databases) -> list[Attempt]:
    with Session(databases.biometric) as db:
        return db.scalars(select(Attempt).order_by(Attempt.at)).all()


def test_the_same_person_matches_and_the_attempt_is_saved_with_its_sealed_image(face_client, databases, keys):
    token = enrolled(face_client)
    answer = verify(face_client, token, variant=3)
    assert answer.status_code == 200, answer.text
    result = answer.json()
    probe = fake_embedding("a", 3)
    expected = {placement: cosine(probe, fake_embedding("a", placement - 1)) for placement in (1, 2, 3)}
    assert [c["placement"] for c in result["comparisons"]] == [1, 2, 3]
    for comparison in result["comparisons"]:  # pgvector's cosine similarity, as at enrolment (H48)
        assert comparison["score"] == pytest.approx(expected[comparison["placement"]], abs=1e-6)
    best = max(expected, key=expected.get)
    assert result["status"] == "verified" and result["accepted"] is True and result["threshold"] == 0.363
    assert result["score"] == pytest.approx(expected[best], abs=1e-6) and result["view"]["placement"] == best
    assert base64.b64decode(result["view"]["probe"]) == b"ALIGNED:a" == base64.b64decode(result["view"]["reference"])
    assert result["threshold_origin"] == "OpenCV's SFace sample, cosine similarity" and result["threshold_provisional"] is False
    (attempt,) = attempts(databases)
    subject = subject_of(face_client, databases, keys, token)
    with Session(databases.biometric) as db:
        current = db.scalars(select(Enrolment).where(Enrolment.modality == "face")).one()
    assert (attempt.subject_id, attempt.modality, attempt.mode, attempt.algorithm, attempt.enrolment_id) == \
           (subject, "face", "verify", "sface", current.id)
    assert (attempt.accepted, attempt.source, attempt.top_enrolment_id, attempt.gallery_size) == (True, "device", None, None)
    assert attempt.score == result["score"] and attempt.duration_ms == result["duration_ms"] >= 0
    assert str(attempt.id) == result["attempt_id"]
    assert keyring.open_sealed(keys, keyring.PROBE, attempt.id.bytes + subject.bytes, attempt.probe) == \
           b"PNG:" + raw(variant=3)


def test_another_person_is_a_saved_non_match(face_client, databases):
    token = enrolled(face_client)
    result = verify(face_client, token, person="b").json()
    assert result["status"] == "verified" and result["accepted"] is False
    assert not any(c["accepted"] for c in result["comparisons"])
    assert [a.accepted for a in attempts(databases)] == [False]


def test_a_score_equal_to_the_threshold_does_not_pass(face_client, databases):
    token = enrolled(face_client)
    first = verify(face_client, token, variant=3).json()
    with Session(databases.biometric) as db, db.begin():
        db.execute(update(Algorithm).where(Algorithm.code == "sface").values(threshold=first["score"]))
    second = verify(face_client, token, variant=3).json()
    assert second["score"] == first["score"] == second["threshold"] and second["accepted"] is False
    assert [a.accepted for a in attempts(databases)] == [True, False]


def test_equal_scores_go_to_the_earliest_image(face_client):
    token = enrolled(face_client, 0, 0, 1)  # images 1 and 2 have the same embedding
    result = verify(face_client, token, variant=0).json()
    scores = {c["placement"]: c["score"] for c in result["comparisons"]}
    assert scores[1] == scores[2] == result["score"] and result["view"]["placement"] == 1


def test_a_rejected_image_makes_no_attempt(face_client, databases):
    token = enrolled(face_client)
    result = verify(face_client, token, faces=[]).json()
    assert result["status"] == "rejected" and [c["name"] for c in result["checks"] if not c["passed"]] == ["one_face"]
    assert attempts(databases) == []


def test_verification_needs_a_signed_in_user_with_an_enrolled_face(face_client, databases):
    assert error(face_client.post("/api/face/verifications", json={"image": image()})) == (401, "not_signed_in")
    admin = administrator(face_client, databases)
    assert error(face_client.post("/api/face/verifications", json={"image": image()}, headers=auth(admin))) == (403, "forbidden")
    token = user(face_client)
    assert error(verify(face_client, token)) == (409, "not_enrolled")
    assert attempts(databases) == []


def test_an_enrolment_replaced_before_the_save_invalidates_the_comparison(face_client, databases, monkeypatch):
    token = enrolled(face_client)
    original = face._repeat_view

    def replaced_meanwhile(*args):
        face_client.post("/api/face/enrolments", json=taken(*(image(variant=v) for v in (4, 5, 6))), headers=auth(token))
        return original(*args)

    monkeypatch.setattr(face, "_repeat_view", replaced_meanwhile)
    assert error(verify(face_client, token, variant=3)) == (409, "enrolment_changed")
    assert attempts(databases) == []


def test_deleting_the_face_erases_its_verification_attempts_and_a_new_enrolment_keeps_them(face_client, databases):
    token = enrolled(face_client)
    verify(face_client, token, variant=3)
    face_client.post("/api/face/enrolments", json=taken(*(image(variant=v) for v in (4, 5, 6))), headers=auth(token))
    verify(face_client, token, variant=3)
    with Session(databases.biometric) as db:
        linked = [db.get(Enrolment, a.enrolment_id).replaced_at is None for a in db.scalars(select(Attempt).order_by(Attempt.at))]
    assert linked == [False, True]  # the earlier attempt stays with the enrolment it compared
    assert face_client.delete("/api/face/enrolment", headers=auth(token)).status_code == 204
    assert attempts(databases) == []


def test_templates_of_another_model_version_are_refused(face_client, databases):
    token = enrolled(face_client)
    with Session(databases.biometric) as db, db.begin():
        db.execute(update(Template).values(version="0" * 64))
    assert error(verify(face_client, token, variant=3)) == (503, "method_version_differs")
    assert attempts(databases) == []


def test_a_stored_face_that_does_not_repeat_its_embedding_saves_nothing(databases, keys, outbox):
    with TestClient(create_app(databases, keys, outbox, faces=service_with())) as client:
        token = enrolled(client)
    drifting = service_with("--drift")
    try:
        with TestClient(create_app(databases, keys, outbox, faces=drifting)) as client:
            from test_api import sign_in
            again = sign_in(client)
            assert error(verify(client, again, variant=3)) == (503, "engine_unavailable")
    finally:
        drifting.close()
    assert attempts(databases) == []
    assert token
