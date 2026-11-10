"""Face enrolment (H17, H25, H48) against a real PostgreSQL, with the face engine replaced by a stand-in that
speaks its real protocol (tests/fakes/fake_face_engine.py). Images here are labels, never pictures of a
person."""

from __future__ import annotations

import base64
import json
import math
import random
import struct
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from mbs import accounts
from mbs import keys as keyring
from mbs.api import create_app
from mbs.engines import Engine
from mbs.face import FaceService
from mbs.models import Enrolment, Sample, Template, vector_text, vector_values

from test_api import administrator, auth, error, register, sign_in

FAKES = Path(__file__).resolve().parent / "fakes"
PYTHON = sys.executable
SFACE_SHA256 = "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79"
CHECKS = ["one_face", "detector_score", "inside", "face_size"]


def service_with(*options: str) -> FaceService:
    return FaceService(Engine("face", [PYTHON, str(FAKES / "fake_face_engine.py"), *options]))


@pytest.fixture
def faces():
    service = service_with()
    yield service
    service.close()


@pytest.fixture
def face_client(databases, keys, outbox, faces):
    with TestClient(create_app(databases, keys, outbox, faces=faces)) as client:
        yield client


def raw(person="a", variant=0, faces=None, width=1280, height=720) -> bytes:
    spec = {"width": width, "height": height, "person": person, "variant": variant,
            "faces": [{"box": [500, 200, 220, 260], "score": 0.95}] if faces is None else faces}
    return b"FAKEFACE" + json.dumps(spec).encode()


def image(*args, **kwargs) -> str:
    return base64.b64encode(raw(*args, **kwargs)).decode()


def taken(*images: str, start: datetime | None = None, step_s: int = 10) -> dict:
    start = start or datetime.now(timezone.utc) - timedelta(minutes=2)
    return {"images": [{"image": item, "captured_at": (start + timedelta(seconds=step_s * i)).isoformat()}
                       for i, item in enumerate(images)]}


def user(client) -> str:
    assert register(client).status_code == 201
    return sign_in(client)


def fake_embedding(person: str, variant: int) -> list[float]:
    """The stand-in's embedding, as float32 values."""
    base, change = random.Random(f"person:{person}"), random.Random(f"variant:{person}:{variant}")
    values = [base.gauss(0, 1) + 0.15 * change.gauss(0, 1) for _ in range(128)]
    return list(struct.unpack("<128f", struct.pack("<128f", *values)))


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b)) / math.sqrt(sum(x * x for x in a) * sum(y * y for y in b))


def subject_of(client, databases, keys, token):
    account_id = client.get("/api/me", headers=auth(token)).json()["account"]["id"]
    import uuid
    return accounts.subject_of(databases, keys, uuid.UUID(account_id))


def test_the_method_card_comes_from_the_algorithm_table(face_client, client):
    token = user(face_client)
    card = face_client.get("/api/face/method", headers=auth(token)).json()
    assert card == {"code": "sface", "threshold": 0.363, "threshold_provisional": False,
                    "threshold_origin": "OpenCV's SFace sample, cosine similarity", "available": True,
                    "images": 3, "most_kept": 6, "score_minimum": 0.9, "width_minimum": 112, "embedding_length": 128}
    assert client.get("/api/face/method", headers=auth(sign_in(client))).json()["available"] is False


def test_the_face_routes_are_only_for_signed_in_users(face_client, databases):
    routes = [("GET", "/api/face/method", None), ("POST", "/api/face/detect", {"image": image()}),
              ("POST", "/api/face/checks", {"image": image()}),
              ("POST", "/api/face/enrolments", taken(image(), image(variant=1), image(variant=2))),
              ("DELETE", "/api/face/enrolment", None), ("POST", "/api/face/verifications", {"image": image()}),
              ("POST", "/api/face/identifications", {"image": image()})]
    admin = administrator(face_client, databases)
    for method, path, body in routes:
        assert error(face_client.request(method, path, json=body)) == (401, "not_signed_in")
        assert error(face_client.request(method, path, json=body, headers=auth(admin))) == (403, "forbidden")


def test_without_the_face_environment_the_face_is_unavailable(client):
    token = user(client)
    for path, body in (("/api/face/detect", {"image": image()}), ("/api/face/checks", {"image": image()}),
                       ("/api/face/enrolments", taken(image(), image(variant=1), image(variant=2))),
                       ("/api/face/verifications", {"image": image()}), ("/api/face/identifications", {"image": image()})):
        assert error(client.post(path, json=body, headers=auth(token))) == (503, "face_unavailable")


def test_the_live_view_learns_where_the_faces_are_and_nothing_is_kept(face_client, databases):
    token = user(face_client)
    one = face_client.post("/api/face/detect", json={"image": image()}, headers=auth(token)).json()
    assert one["width"] == 1280 and one["height"] == 720 and len(one["faces"]) == 1
    assert one["faces"][0]["box"] == [500, 200, 220, 260] and len(one["faces"][0]["landmarks"]) == 5
    two = face_client.post("/api/face/detect", headers=auth(token), json={"image": image(
        faces=[{"box": [100, 100, 150, 180], "score": 0.97}, {"box": [700, 120, 160, 190], "score": 0.92}])}).json()
    assert [f["score"] for f in two["faces"]] == [0.97, 0.92]
    assert error(face_client.post("/api/face/detect", json={"image": base64.b64encode(b"not an image").decode()},
                                  headers=auth(token))) == (422, "invalid_image")
    assert error(face_client.post("/api/face/detect", json={"image": "not base64!"},
                                  headers=auth(token))) == (422, "invalid_image")
    assert face_client.post("/api/face/detect", json={"image": "A" * (2 << 20)}, headers=auth(token)).status_code == 422
    with Session(databases.biometric) as db:
        assert db.scalars(select(Sample)).all() == []


@pytest.mark.parametrize("found, failed", [
    ([], "one_face"),
    ([{"box": [100, 100, 150, 180], "score": 0.97}, {"box": [700, 120, 160, 190], "score": 0.92}], "one_face"),
    ([{"box": [500, 200, 220, 260], "score": 0.85}], "detector_score"),
    ([{"box": [-5, 200, 220, 260], "score": 0.95}], "inside"),
    ([{"box": [1100, 200, 220, 260], "score": 0.95}], "inside"),
    ([{"box": [500, 200, 100, 130], "score": 0.95}], "face_size"),
])
def test_a_taken_image_that_fails_a_check_is_not_shown_as_a_face(face_client, found, failed):
    token = user(face_client)
    answer = face_client.post("/api/face/checks", json={"image": image(faces=found)}, headers=auth(token)).json()
    assert answer["passed"] is False and answer["aligned"] is None
    assert [c["name"] for c in answer["checks"] if not c["passed"]] == [failed]


def test_a_taken_image_that_passes_shows_its_aligned_face(face_client):
    token = user(face_client)
    answer = face_client.post("/api/face/checks", json={"image": image()}, headers=auth(token)).json()
    assert answer["passed"] is True and [c["name"] for c in answer["checks"]] == CHECKS
    assert base64.b64decode(answer["aligned"]) == b"ALIGNED:a"
    score, size = answer["checks"][1], answer["checks"][3]
    assert (score["score"], score["minimum"], size["width"], size["minimum"]) == (0.95, 0.9, 220, 112)


def test_three_matching_images_enrol_the_face(face_client, databases, keys):
    token = user(face_client)
    images = [raw(variant=v) for v in range(3)]
    answer = face_client.post("/api/face/enrolments", headers=auth(token),
                              json=taken(*(base64.b64encode(i).decode() for i in images)))
    assert answer.status_code == 201, answer.text
    saved = answer.json()
    assert saved["status"] == "saved" and saved["enrolment"]["replaced_previous"] is False and saved["not_kept"] == []
    assert [s["placement"] for s in saved["samples"]] == [1, 2, 3]
    assert all(base64.b64decode(s["aligned"]) == b"ALIGNED:a" for s in saved["samples"])
    expected = [fake_embedding("a", v) for v in range(3)]
    assert len(saved["pairs"]) == 3 and all(pair["accepted"] for pair in saved["pairs"])
    for pair in saved["pairs"]:  # pgvector's cosine similarity, the score of every face comparison
        assert pair["score"] == pytest.approx(cosine(expected[pair["probe"] - 1], expected[pair["reference"] - 1]), abs=1e-6)
    subject = subject_of(face_client, databases, keys, token)
    with Session(databases.biometric) as db:
        enrolment = db.scalars(select(Enrolment)).one()
        assert (enrolment.subject_id, enrolment.modality, enrolment.finger, enrolment.replaced_at) == (subject, "face", None, None)
        samples = db.scalars(select(Sample).order_by(Sample.placement)).all()
        assert [(s.media_type, s.width, s.height, s.ppi) for s in samples] == [("image/png", 1280, 720, None)] * 3
        assert [c["name"] for c in samples[0].checks] == CHECKS
        for sample, original in zip(samples, images):
            assert keyring.open_sealed(keys, keyring.SAMPLE, sample.id.bytes + subject.bytes, sample.data) == b"PNG:" + original
        templates = db.scalars(select(Template)).all()
        assert {(t.algorithm, t.version, t.data) for t in templates} == {("sface", SFACE_SHA256, None)}
        by_sample = {t.sample_id: t.embedding for t in templates}
        assert [by_sample[s.id] for s in samples] == expected
    modalities = face_client.get("/api/me", headers=auth(token)).json()["modalities"]
    assert modalities["face"]["enrolled"] is True and modalities["face"]["enrolled_at"] == saved["enrolment"]["created_at"]


def test_another_image_is_asked_for_until_three_match(face_client, databases):
    token = user(face_client)
    first = [image(variant=0), image(variant=1), image(person="b")]
    answer = face_client.post("/api/face/enrolments", json=taken(*first), headers=auth(token))
    assert answer.status_code == 200
    another = answer.json()
    assert another["status"] == "another" and another["kept"] == 3 and another["threshold"] == 0.363
    assert {(p["probe"], p["reference"]): p["accepted"] for p in another["pairs"]} == {(2, 1): True, (3, 1): False, (3, 2): False}
    with Session(databases.biometric) as db:
        assert db.scalars(select(Enrolment)).all() == []
    saved = face_client.post("/api/face/enrolments", json=taken(*first, image(variant=2)), headers=auth(token)).json()
    assert saved["status"] == "saved" and saved["not_kept"] == [3]
    assert [s["placement"] for s in saved["samples"]] == [1, 2, 4]
    assert sorted((p["probe"], p["reference"]) for p in saved["pairs"]) == [(2, 1), (4, 1), (4, 2)]


def test_six_images_without_three_that_match_end_unsaved(face_client, databases):
    token = user(face_client)
    answer = face_client.post("/api/face/enrolments", headers=auth(token),
                              json=taken(*(image(person=p) for p in "abcdef"))).json()
    assert answer["status"] == "failed" and answer["error"] == "images_do_not_match" and len(answer["pairs"]) == 15
    with Session(databases.biometric) as db:
        assert db.scalars(select(Enrolment)).all() == []


def test_an_image_that_fails_its_checks_refuses_the_enrolment(face_client, databases):
    token = user(face_client)
    two = image(faces=[{"box": [100, 100, 150, 180], "score": 0.97}, {"box": [700, 120, 160, 190], "score": 0.92}])
    answer = face_client.post("/api/face/enrolments", json=taken(image(), two, image(variant=2)), headers=auth(token))
    assert error(answer) == (422, "image_rejected") and answer.json()["index"] == 1
    assert answer.json()["checks"][0]["count"] == 2
    with Session(databases.biometric) as db:
        assert db.scalars(select(Sample)).all() == []


def test_enrolling_again_replaces_the_face_and_deleting_erases_every_enrolment(face_client, databases):
    token = user(face_client)
    three = taken(image(variant=0), image(variant=1), image(variant=2))
    assert face_client.post("/api/face/enrolments", json=three, headers=auth(token)).status_code == 201
    again = face_client.post("/api/face/enrolments", json=three, headers=auth(token)).json()
    assert again["enrolment"]["replaced_previous"] is True
    with Session(databases.biometric) as db:
        enrolments = db.scalars(select(Enrolment).order_by(Enrolment.created_at)).all()
        assert len(enrolments) == 2 and enrolments[0].replaced_at is not None and enrolments[1].replaced_at is None
        assert len(db.scalars(select(Template)).all()) == 6
    assert face_client.delete("/api/face/enrolment", headers=auth(token)).status_code == 204
    with Session(databases.biometric) as db:
        assert db.scalars(select(Enrolment)).all() == [] and db.scalars(select(Sample)).all() == []
        assert db.scalars(select(Template)).all() == []
    assert error(face_client.delete("/api/face/enrolment", headers=auth(token))) == (404, "not_enrolled")
    assert face_client.get("/api/me", headers=auth(token)).json()["modalities"]["face"] == {"enrolled": False}


def test_an_enrolment_needs_three_to_six_images_taken_in_order_in_the_last_half_hour(face_client):
    token = user(face_client)
    three = [image(variant=v) for v in range(3)]
    now = datetime.now(timezone.utc)
    for body in (taken(*three[:2]), taken(*(three * 3)[:7]), taken(*three, start=now + timedelta(minutes=5)),
                 taken(*three, start=now - timedelta(hours=2)), taken(*three, step_s=-10)):
        assert face_client.post("/api/face/enrolments", json=body, headers=auth(token)).status_code == 422
    naive = taken(*three)
    for item in naive["images"]:
        item["captured_at"] = item["captured_at"].replace("+00:00", "")
    assert face_client.post("/api/face/enrolments", json=naive, headers=auth(token)).status_code == 422


def test_a_model_other_than_the_pinned_one_is_refused(databases, keys, outbox):
    service = service_with("--sface-sha256", "0" * 64)
    try:
        with TestClient(create_app(databases, keys, outbox, faces=service)) as client:
            token = user(client)
            body = taken(image(variant=0), image(variant=1), image(variant=2))
            assert error(client.post("/api/face/enrolments", json=body, headers=auth(token))) == (503, "method_version_differs")
    finally:
        service.close()


def test_an_engine_answer_that_breaks_the_rules_is_a_server_failure(databases, keys, outbox):
    service = service_with("--broken")
    try:
        with TestClient(create_app(databases, keys, outbox, faces=service)) as client:
            token = user(client)
            assert error(client.post("/api/face/checks", json={"image": image()}, headers=auth(token))) == (503, "engine_unavailable")
    finally:
        service.close()


def test_embeddings_reach_pgvector_as_exact_float32_values(databases):
    values = list(struct.unpack("<128f", struct.pack("<128f", *(random.Random(9).uniform(-3, 3) for _ in range(128)))))
    other = list(struct.unpack("<128f", struct.pack("<128f", *(random.Random(10).uniform(-3, 3) for _ in range(128)))))
    with Session(databases.biometric) as db:
        stored = db.scalar(text("SELECT CAST(:v AS vector)::text"), {"v": vector_text(values)})
        assert vector_values(stored) == values
        score = db.scalar(text("SELECT 1 - (CAST(:a AS vector) <=> CAST(:b AS vector))"),
                          {"a": vector_text(values), "b": vector_text(other)})
        assert score == pytest.approx(cosine(values, other), abs=1e-6)
