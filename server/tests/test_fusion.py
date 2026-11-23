"""The combined test (H60) against a real PostgreSQL, with the scanner and every engine replaced by the stand-ins of
tests/fakes/. Captures, images and recordings here are labels, never a person's."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from mbs import fusion
from mbs import keys as keyring
from mbs.api import create_app
from mbs.models import Attempt, Enrolment, FusedAttempt
from test_api import auth, register, sign_in
from test_face import faces, image, taken
from test_fingerprint import enrol, finger, placements, plan, script, service, subject_of
from test_voice import made, recording, voices


@pytest.fixture
def all_client(databases, keys, outbox, service, faces, voices):
    with TestClient(base_url="http://127.0.0.1",
                    app=create_app(databases, keys, outbox, service, faces=faces, voices=voices)) as client:
        yield client


def person(client, script, letter: str, name: str = "michael", national_id: str = "123456782",
           phone: str = "050-123-4567", face: str | None = "a", voice: str | None = "a") -> str:
    """A signed-in user whose finger 7 (the stand-in's letter), face and voice are enrolled."""
    assert register(client, username=name, email=f"{name}@example.org", national_id=national_id,
                    phone=phone).status_code == 201
    token = sign_in(client, login=name)
    plan(script, *placements(f"q64:{letter}1", f"q70:{letter}2", f"q58:{letter}3"))
    assert enrol(client, token)[-1]["type"] == "saved"
    if face:
        answer = client.post("/api/face/enrolments", json=taken(*(image(face, v) for v in (0, 1, 2))), headers=auth(token))
        assert answer.status_code == 201, answer.text
    if voice:
        answer = client.post("/api/voice/enrolments", json=made(*(recording(voice, v) for v in (0, 1, 2))),
                             headers=auth(token))
        assert answer.status_code == 201, answer.text
    return token


def samples(face: str | None = "a", voice: str | None = "a", age_s: int = 20) -> dict:
    at = (datetime.now(UTC) - timedelta(seconds=age_s)).isoformat()
    body: dict = {}
    if face:
        body["face"] = {"image": image(face, 5), "captured_at": at}
    if voice:
        body["voice"] = {"recording": recording(voice, 5), "captured_at": at}
    return body


def stream(client, token, path: str, body: dict) -> list[dict]:
    with client.stream("POST", path, json=body, headers=auth(token)) as answer:
        assert answer.status_code == 200, answer.read()
        return [json.loads(line) for line in answer.iter_lines() if line]


def verify(client, token, body: dict | None = None) -> list[dict]:
    return stream(client, token, "/api/fusion/verifications", {"finger": 7, **(samples() if body is None else body)})


def kinds(events: list[dict]) -> list[str]:
    return [event["type"] for event in events]


def stored(databases) -> tuple[list[FusedAttempt], list[Attempt]]:
    with Session(databases.biometric) as db:
        return (list(db.scalars(select(FusedAttempt)).all()),
                list(db.scalars(select(Attempt).order_by(Attempt.modality)).all()))


def test_the_first_policy_shares_six_orders_of_evidence_by_55_25_and_20(databases):
    policy = fusion.current_policy(databases)
    assert (policy.weights, policy.budget, policy.threshold) == ({"fingerprint": 55, "face": 25, "voice": 20}, 6.0, 75.0)
    assert [fusion.cap(policy, m) for m in fusion.MODALITIES] == pytest.approx([3.3, 1.5, 1.2])
    # The SD302 curve: x1 at about 12 pairs, x26 at 57; the best of three counts a third.
    assert fusion.evidence(policy, "fingerprint", 12, 1) == pytest.approx(0.0, abs=0.01)
    assert 10 ** fusion.evidence(policy, "fingerprint", 57, 1) == pytest.approx(25.8, abs=0.1)
    assert fusion.evidence(policy, "fingerprint", 57, 3) == pytest.approx(math.log10(25.8 / 3), abs=0.01)
    assert fusion.evidence(policy, "fingerprint", 5000, 3) == pytest.approx(3.3)  # capped at 0.06 x 55
    # Face and voice: neutral at their models' thresholds, capped within about 0.1 of them.
    assert fusion.evidence(policy, "face", 0.363, 1) == 0.0 and fusion.evidence(policy, "voice", 0.25, 1) == 0.0
    assert fusion.evidence(policy, "face", 0.73, 3) == 1.5 and fusion.evidence(policy, "voice", 0.20, 3) == -1.2
    # Points: half of the weight says nothing; the score is 75 exactly at a combined ratio of 1,000.
    assert fusion.points(policy, "face", 0.0) == 12.5 and fusion.points(policy, "voice", 1.2) == 20
    assert fusion.score_of(policy, {"fingerprint": 1.0, "face": 1.0, "voice": 1.0}) == pytest.approx(75.0)
    # The camera and the microphone at their caps never pass without a fingerprint in favour.
    assert fusion.score_of(policy, {"fingerprint": 0.0, "face": 1.5, "voice": 1.2}) < policy.threshold


def test_the_card_shows_the_policy_and_which_calibrations_are_provisional(all_client, script):
    token = person(all_client, script, "A")
    card = all_client.get("/api/fusion/method", headers=auth(token)).json()
    assert card["policy"]["weights"] == {"fingerprint": 55, "face": 25, "voice": 20} and card["policy"]["threshold"] == 75
    assert {m: c["provisional"] for m, c in card["policy"]["calibration"].items()} == \
           {"fingerprint": False, "face": True, "voice": True}
    assert card["available"] == {"fingerprint": True, "face": True, "voice": True}


def test_a_test_of_the_same_person_is_accepted_and_saved_with_each_comparison(all_client, script, databases, keys):
    token = person(all_client, script, "A")
    plan(script, finger("q60:A9"))
    events = verify(all_client, token)
    assert kinds(events) == ["started", "checking_sample", "checking_sample", "place", "checking", "captured",
                             "comparing", "saving", "verified"]
    assert events[0]["modalities"] == ["fingerprint", "face", "voice"] and events[0]["threshold"] == 75
    result = events[-1]
    parts = {p["modality"]: p for p in result["parts"]}
    assert parts["fingerprint"]["score"] == 90 and parts["fingerprint"]["compared"] == 3
    assert parts["face"]["points"] == 25 and parts["voice"]["points"] == 20  # at their caps
    assert len(parts["face"]["values"]) == 128 and len(parts["voice"]["values"]) == 192  # the rings of the result
    assert "values" not in parts["fingerprint"]
    assert result["accepted"] is True and result["score"] == pytest.approx(
        50 + 50 * sum(p["evidence"] for p in parts.values()) / 6)
    (test,), comparisons = stored(databases)
    subject = subject_of(all_client, databases, keys, token)
    assert (test.mode, test.subject_id, test.policy_id, test.accepted) == ("verify", subject, 1, True)
    assert test.score == pytest.approx(result["score"]) and test.gallery_size is None
    assert [(c.modality, c.mode, c.fused_attempt_id) for c in comparisons] == \
           [("face", "verify", test.id), ("fingerprint", "verify", test.id), ("voice", "verify", test.id)]
    for comparison in comparisons:
        assert comparison.evidence == pytest.approx(parts[comparison.modality]["evidence"])
        assert comparison.accepted == (comparison.score > comparison.threshold)
        sealed = keyring.open_sealed(keys, keyring.PROBE, comparison.id.bytes + subject.bytes, comparison.probe)
        assert sealed.startswith(b"FAKEPNG:q60:A9" if comparison.modality == "fingerprint" else b"")


def test_another_finger_with_the_same_face_and_voice_is_not_enough(all_client, script, databases):
    token = person(all_client, script, "A")
    plan(script, finger("q60:B1"))
    result = verify(all_client, token)[-1]
    parts = {p["modality"]: p for p in result["parts"]}
    assert parts["fingerprint"]["score"] == 5 and parts["fingerprint"]["evidence"] < 0
    assert parts["face"]["accepted"] and parts["voice"]["accepted"]
    assert result["accepted"] is False and result["score"] < 75
    (test,), comparisons = stored(databases)
    assert not test.accepted and [c.accepted for c in comparisons] == [True, False, True]


def test_a_refused_face_ends_the_test_before_the_scanner(all_client, script, databases):
    token = person(all_client, script, "A")
    plan(script, finger("q60:A9"))
    body = samples()
    body["face"]["image"] = image("a", 5, faces=[])
    events = verify(all_client, token, body)
    assert kinds(events) == ["started", "checking_sample", "sample_rejected"]
    assert events[-1]["modality"] == "face" and stored(databases) == ([], [])


def test_the_test_needs_a_second_modality_and_its_samples(all_client, script, databases):
    token = person(all_client, script, "A", face=None, voice=None)
    assert verify(all_client, token, {})[-1] == {"type": "failed", "error": "not_enough_modalities"}
    answer = all_client.post("/api/face/enrolments", json=taken(*(image("a", v) for v in (0, 1, 2))), headers=auth(token))
    assert answer.status_code == 201
    # The face is enrolled, so its image is needed; the voice is not, so a recording is refused.
    assert verify(all_client, token, {})[-1] == {"type": "failed", "error": "invalid_request"}
    assert verify(all_client, token, samples())[-1] == {"type": "failed", "error": "invalid_request"}
    assert verify(all_client, token, samples(voice=None, age_s=11 * 60))[-1] == {"type": "failed", "error": "sample_too_old"}
    assert stored(databases) == ([], [])


def test_deleting_a_modality_erases_its_combined_tests_with_every_comparison(all_client, script, databases):
    token = person(all_client, script, "A")
    plan(script, finger("q60:A9"))
    assert verify(all_client, token)[-1]["type"] == "verified"
    assert all_client.delete("/api/face/enrolment", headers=auth(token)).status_code == 204
    assert stored(databases) == ([], [])  # the fingerprint's and the voice's comparisons go with the test (H35)


def test_identification_ranks_the_people_enrolled_in_every_modality(all_client, script, databases):
    other = person(all_client, script, "B", name="dana", national_id="314159260", phone="052-765-4321", face="b",
                   voice="b")
    token = person(all_client, script, "A")
    person(all_client, script, "C", name="noa", national_id="000000018", phone="054-111-2222", voice=None)
    plan(script, finger("q60:A9"))
    events = stream(all_client, token, "/api/fusion/identifications", samples())
    assert events[0]["people"] == 2  # noa has no voice, so she is not in a test of all three
    result = events[-1]
    assert result["type"] == "identified" and result["accepted"] is True and result["people"] == 2
    assert result["leader"] == {"own": True, "finger": 7}
    first, second = result["candidates"]
    assert first["own"] and first["finger"] == 7 and not second["own"] and "finger" not in second
    assert second["score"] < 75 < first["score"] and set(second["points"]) == {"fingerprint", "face", "voice"}
    (test,), comparisons = stored(databases)
    assert (test.mode, test.gallery_size, test.fingerprint_enrolment_id) == ("identify", 2, None)
    with Session(databases.biometric) as db:
        tops = {c.modality: db.get_one(Enrolment, c.top_enrolment_id).subject_id for c in comparisons}
    assert len(set(tops.values())) == 1 and all(c.enrolment_id is None for c in comparisons)
    assert {c.modality: c.gallery_size for c in comparisons} == {"fingerprint": 6, "face": 6, "voice": 6}
    assert other  # dana's own test would lead with her own enrolments; her token stays unused here
