"""The administration area's attempt history (H61) against a real PostgreSQL: who may read it, its rows newest first,
its filters, keyset paging, combined tests with their comparisons, and what it never shows. The attempts are written
straight into the biometric database; their probes are placeholders that the history must never read."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from mbs import accounts, fusion
from mbs.models import Attempt, Enrolment, FusedAttempt, FusionPolicy
from test_api import administrator, auth, error, register, sign_in

T0 = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
METHOD = {"fingerprint": "opencv-sift", "face": "sface", "voice": "ecapa-voxceleb"}
THRESHOLD = {"opencv-sift": 57.0, "pore-sift": 37.0, "learned-pore": 21.0, "sface": 0.363, "ecapa-voxceleb": 0.25}
PROBE = b"NOT-A-REAL-PROBE"
SEARCH = "/api/admin/attempts/search"


def person(client, databases, keys, username: str, national_id: str, phone: str) -> uuid.UUID:
    response = register(client, username=username, email=f"{username}@example.org", national_id=national_id,
                        phone=phone)
    assert response.status_code == 201, response.text
    return accounts.user_subject(databases, keys, uuid.UUID(response.json()["account"]["id"]))


def enrolment(db: Session, subject: uuid.UUID, modality: str, finger: int | None = None) -> uuid.UUID:
    row = Enrolment(id=uuid.uuid4(), subject_id=subject, modality=modality,
                    finger=finger if modality == "fingerprint" else None, created_at=T0 - timedelta(days=1))
    db.add(row)
    db.flush()
    return row.id


def attempt(db: Session, subject: uuid.UUID, at: datetime, *, modality: str = "fingerprint", mode: str = "verify",
            algorithm: str | None = None, score: float = 614.0, enrolment_id: uuid.UUID | None = None,
            top: uuid.UUID | None = None, gallery: int | None = None, source: str = "device",
            fused: uuid.UUID | None = None, evidence: float | None = None, capture: uuid.UUID | None = None,
            ms: int = 700) -> Attempt:
    method = algorithm or METHOD[modality]
    row = Attempt(id=uuid.uuid4(), at=at, subject_id=subject, modality=modality, mode=mode, algorithm=method,
                  enrolment_id=enrolment_id if mode == "verify" else None,
                  top_enrolment_id=top if mode == "identify" else None,
                  gallery_size=gallery if mode == "identify" else None, score=score, threshold=THRESHOLD[method],
                  accepted=score > THRESHOLD[method], duration_ms=ms, source=source, probe=PROBE,
                  fused_attempt_id=fused, evidence=evidence, capture_attempt_id=capture)
    db.add(row)
    db.flush()
    return row


def combined(db: Session, subject: uuid.UUID, at: datetime, scores: dict[str, float], *, mode: str = "verify",
             enrolments: dict[str, uuid.UUID] | None = None, tops: dict[str, uuid.UUID | None] | None = None,
             people: int = 3) -> FusedAttempt:
    """A combined test as H60 saves it: the test, then one comparison of its own per modality pointing to it."""
    policy = fusion.policy_of(db.get_one(FusionPolicy, 1))
    parts = {m: fusion.part(policy, m, METHOD[m], s, THRESHOLD[METHOD[m]], 3) for m, s in scores.items()}
    score = fusion.score_of(policy, {m: p.evidence for m, p in parts.items()})
    links = enrolments or {}
    test = FusedAttempt(id=uuid.uuid4(), at=at, subject_id=subject, mode=mode, policy_id=1,
                        fingerprint_enrolment_id=links.get("fingerprint") if mode == "verify" else None,
                        face_enrolment_id=links.get("face") if mode == "verify" else None,
                        voice_enrolment_id=links.get("voice") if mode == "verify" else None,
                        gallery_size=people if mode == "identify" else None, score=score,
                        threshold=policy.threshold, accepted=score > policy.threshold,
                        evidence=sum(p.evidence for p in parts.values()), duration_ms=920)
    db.add(test)
    db.flush()
    for m, piece in parts.items():
        attempt(db, subject, at, modality=m, mode=mode, score=piece.score, enrolment_id=links.get(m),
                top=(tops or {}).get(m), gallery=3 * people, fused=test.id, evidence=piece.evidence)
    return test


@pytest.fixture
def world(client, databases, keys):
    """Two users with a fingerprint, a face and a voice each, and a signed-in administrator."""
    noa = person(client, databases, keys, "noa.b", "123456782", "050-123-4567")
    dana = person(client, databases, keys, "Dana", "000000018", "050-123-4568")
    with Session(databases.biometric) as db, db.begin():
        enrolled = {who: {m: enrolment(db, subject, m, 1) for m in METHOD}
                    for who, subject in (("noa", noa), ("dana", dana))}
    return {"noa": noa, "dana": dana, "enrolled": enrolled, "token": administrator(client, databases)}


def read(client, token, **body) -> dict:
    response = client.post(SEARCH, json=body, headers=auth(token))
    assert response.status_code == 200, response.text
    return response.json()


def test_only_administrators_read_the_history(client, databases, keys, world):
    register(client, username="other", email="other@example.org", national_id="000000026", phone="050-123-4569")
    assert error(client.post(SEARCH, json={}, headers=auth(sign_in(client, "other")))) == (403, "forbidden")
    assert error(client.post(SEARCH, json={})) == (401, "not_signed_in")
    assert read(client, world["token"]) == {"rows": [], "total": 0, "next": None}


def test_rows_come_newest_first_with_their_outcomes_and_nothing_sealed(client, databases, world):
    noa, dana, enrolled = world["noa"], world["dana"], world["enrolled"]
    with Session(databases.biometric) as db, db.begin():
        attempt(db, noa, T0, enrolment_id=enrolled["noa"]["fingerprint"])
        attempt(db, dana, T0 + timedelta(minutes=1), modality="face", score=0.191, source="file",
                enrolment_id=enrolled["dana"]["face"], ms=50)
        attempt(db, noa, T0 + timedelta(minutes=2), algorithm="learned-pore", score=58,
                enrolment_id=enrolled["noa"]["fingerprint"], ms=3080)
    answer = read(client, world["token"])
    assert answer["total"] == 3 and answer["next"] is None
    first, second, third = answer["rows"]
    assert first == {
        "kind": "attempt", "id": first["id"], "at": (T0 + timedelta(minutes=2)).isoformat(),
        "user": {"username": "noa.b", "disabled": False}, "modality": "fingerprint", "mode": "verify",
        "algorithm": "learned-pore", "provisional": True, "score": 58.0, "threshold": 21.0, "accepted": True,
        "duration_ms": 3080, "source": "device", "gallery_size": None, "leader": None, "capture_of": None}
    assert (second["user"]["username"], second["modality"], second["accepted"], second["source"],
            second["provisional"]) == ("Dana", "face", False, "file", False)
    assert (third["algorithm"], third["score"], third["accepted"]) == ("opencv-sift", 614.0, True)
    text = json.dumps(answer)
    assert "probe" not in text and PROBE.decode() not in text and "123456782" not in text


def test_the_filters_narrow_the_rows(client, databases, world):
    noa, dana, enrolled = world["noa"], world["dana"], world["enrolled"]
    with Session(databases.biometric) as db, db.begin():
        attempt(db, noa, T0, enrolment_id=enrolled["noa"]["fingerprint"])
        attempt(db, noa, T0 + timedelta(hours=1), algorithm="pore-sift", score=14,
                enrolment_id=enrolled["noa"]["fingerprint"])
        attempt(db, dana, T0 + timedelta(hours=2), modality="voice", mode="identify", score=0.733, gallery=6,
                top=enrolled["dana"]["voice"], source="file")
        attempt(db, dana, T0 + timedelta(days=1), modality="face", score=0.712, enrolment_id=enrolled["dana"]["face"])
        combined(db, noa, T0 + timedelta(hours=3), {"fingerprint": 383, "face": 0.73, "voice": 0.75},
                 enrolments=enrolled["noa"])

    def count(**body) -> int:
        return read(client, world["token"], **body)["total"]

    assert count() == 5
    assert count(type="fingerprint") == 2 and count(type="combined") == 1 and count(type="voice") == 1
    assert count(mode="identify") == 1 and count(mode="verify") == 4
    assert count(method="pore-sift") == 1 and count(method="opencv-sift") == 1  # a combined test has no one method
    assert count(result="rejected") == 1 and count(result="accepted") == 4
    assert count(source="file") == 1 and count(source="device") == 4  # a combined test takes the devices
    assert count(user="DAN") == 2 and count(user="b") == 3 and count(user="nobody") == 0
    day = T0.replace(hour=0)
    assert count(since=day.isoformat(), until=(day + timedelta(days=1)).isoformat()) == 4
    assert count(since=(day + timedelta(days=1)).isoformat()) == 1
    assert count(type="face", user="dana", result="accepted", since=day.isoformat()) == 1


def test_pages_follow_on_by_time_and_id(client, databases, world):
    noa, enrolled = world["noa"], world["enrolled"]
    with Session(databases.biometric) as db, db.begin():
        made = [attempt(db, noa, T0 + timedelta(minutes=i), enrolment_id=enrolled["noa"]["fingerprint"]).id
                for i in range(5)]
        same_moment = attempt(db, noa, T0 + timedelta(minutes=2), enrolment_id=enrolled["noa"]["fingerprint"]).id
    answer = read(client, world["token"], limit=2)
    assert answer["total"] == 6
    seen = [row["id"] for row in answer["rows"]]
    with Session(databases.biometric) as db, db.begin():  # saved meanwhile: newer than every page, it shifts none
        attempt(db, noa, T0 + timedelta(hours=1), enrolment_id=enrolled["noa"]["fingerprint"])
    while answer["next"] is not None:
        answer = read(client, world["token"], limit=2, after=answer["next"])
        assert answer["total"] == 7
        seen += [row["id"] for row in answer["rows"]]
    tied = sorted([str(made[2]), str(same_moment)], reverse=True)
    assert seen == [str(made[4]), str(made[3]), *tied, str(made[1]), str(made[0])]


def test_a_combined_test_is_one_row_with_its_comparisons(client, databases, world):
    noa, enrolled = world["noa"], world["enrolled"]
    with Session(databases.biometric) as db, db.begin():
        refused = combined(db, noa, T0, {"fingerprint": 8, "face": 0.73, "voice": 0.75},
                           enrolments=enrolled["noa"]).id
        policy = fusion.policy_of(db.get_one(FusionPolicy, 1))
    rows = read(client, world["token"])["rows"]
    assert len(rows) == 1
    row = rows[0]
    assert (row["kind"], row["id"], row["mode"], row["policy"], row["accepted"]) == \
        ("combined", str(refused), "verify", 1, False)
    assert row["score"] == pytest.approx(65.64, abs=0.01) and row["threshold"] == 75.0
    assert row["weights"] == {"fingerprint": 55, "face": 25, "voice": 20} and row["budget"] == 6.0
    assert [part["modality"] for part in row["parts"]] == ["fingerprint", "face", "voice"]
    fingerprint, face, voice = row["parts"]
    assert (fingerprint["algorithm"], fingerprint["score"], fingerprint["accepted"], fingerprint["capped"]) == \
        ("opencv-sift", 8.0, False, False)
    assert fingerprint["points"] == pytest.approx(fusion.points(policy, "fingerprint", fingerprint["evidence"]))
    assert (face["accepted"], face["capped"], face["points"], face["weight"]) == (True, True, 25.0, 25)
    assert (voice["accepted"], voice["capped"], voice["points"], voice["weight"]) == (True, True, 20.0, 20)
    assert sum(part["evidence"] for part in row["parts"]) == pytest.approx(row["evidence"])


def test_the_leader_of_a_search_is_never_named(client, databases, world):
    noa, dana, enrolled = world["noa"], world["dana"], world["enrolled"]
    with Session(databases.biometric) as db, db.begin():
        attempt(db, noa, T0, mode="identify", score=579, gallery=6, top=enrolled["noa"]["fingerprint"])
        attempt(db, noa, T0 + timedelta(minutes=1), modality="face", mode="identify", score=0.402, gallery=6,
                top=enrolled["dana"]["face"])
        attempt(db, noa, T0 + timedelta(minutes=2), modality="voice", mode="identify", score=0.214, gallery=6)
        combined(db, dana, T0 + timedelta(minutes=3), {"fingerprint": 614, "face": 0.73, "voice": 0.75},
                 mode="identify", tops=enrolled["dana"], people=2)
    rows = read(client, world["token"], mode="identify")["rows"]
    assert [(row["leader"], row["accepted"]) for row in rows] == \
        [("own", True), ("gone", False), ("other", True), ("own", True)]
    assert rows[0]["gallery_size"] == 2 and rows[3]["gallery_size"] == 6
    text = json.dumps(rows)
    assert text.count("Dana") == 1 and text.count("noa.b") == 3  # each row names only who searched


def test_a_capture_compared_again_names_when_it_was_taken(client, databases, world):
    noa, enrolled = world["noa"], world["enrolled"]
    with Session(databases.biometric) as db, db.begin():
        first = attempt(db, noa, T0, enrolment_id=enrolled["noa"]["fingerprint"])
        attempt(db, noa, T0 + timedelta(minutes=1), algorithm="learned-pore", score=58,
                enrolment_id=enrolled["noa"]["fingerprint"], capture=first.id)
    again, original = read(client, world["token"])["rows"]
    assert again["capture_of"] == T0.isoformat() and original["capture_of"] is None


def test_a_disabled_account_is_marked(client, databases, keys, world):
    with Session(databases.biometric) as db, db.begin():
        attempt(db, world["dana"], T0, modality="voice", score=0.733, enrolment_id=world["enrolled"]["dana"]["voice"])
    admin = accounts.session_account(databases, world["token"])
    assert admin is not None
    dana = next(row for row in accounts.list_accounts(databases) if row["username"] == "Dana")
    accounts.set_status(databases, admin.id, "Another one 2027", uuid.UUID(dana["id"]), "disabled")
    assert read(client, world["token"])["rows"][0]["user"] == {"username": "Dana", "disabled": True}


@pytest.mark.parametrize("body", [
    {"type": "gait"}, {"mode": "both"}, {"method": "fusion"}, {"result": "maybe"}, {"source": "phone"},
    {"limit": 51}, {"limit": 0}, {"since": "2026-11-23T12:00:00"}, {"after": {"at": "2026-11-23T12:00:00Z"}},
    {"user": "x" * 33},
])
def test_unknown_filters_are_refused(client, world, body):
    assert client.post(SEARCH, json=body, headers=auth(world["token"])).status_code == 422
