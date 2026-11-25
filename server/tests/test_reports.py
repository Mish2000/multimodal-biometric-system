"""The administration area's reports (H62) against a real PostgreSQL: who may read them, every number against known
values, the bars around each threshold, the days of the PC's clock around midnight and when the clock changes, the
combined test's comparisons kept out of the methods' reports, rescued and stopped, decisions made with an earlier
threshold or policy, the same totals as the history, and nothing sealed opened. The attempts are written straight into
the biometric database, as the history's tests write them."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Double, literal, select, text
from sqlalchemy.orm import Session

from mbs import keys as keyring
from mbs import reports
from mbs.models import Attempt, FusedAttempt, FusionPolicy
from mbs.reports import Filters, Scale
from test_api import auth, error, register, sign_in
from test_history import PROBE, attempt, combined, world

ZONE = "Asia/Jerusalem"
NOW = datetime(2026, 11, 24, 10, 0, tzinfo=UTC)  # noon in Israel
T0 = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
REPORTS = "/api/admin/reports"
CODES = ["opencv-sift", "pore-sift", "learned-pore", "sface", "ecapa-voxceleb", "combined"]


def read(client, token, **body) -> dict:
    response = client.post(REPORTS, json={"zone": ZONE, **body}, headers=auth(token))
    assert response.status_code == 200, response.text
    return response.json()


def report_of(answer: dict, code: str) -> dict:
    return next(report for report in answer["reports"] if report["code"] == code)


def report(databases, code: str, filters: Filters | None = None, now: datetime = NOW) -> dict:
    return report_of(reports.reports(databases, filters or Filters(), ZONE, now), code)


def bars(found: dict) -> dict[int, tuple[int, int, int]]:
    """The bars that hold attempts: accepted, of them led by another registered user, and rejected."""
    return {bar["k"]: (bar["accepted"], bar["other"], bar["rejected"]) for bar in found["bars"]
            if bar["accepted"] or bar["rejected"]}


def test_only_administrators_read_the_reports(client, world):
    register(client, username="other", email="other@example.org", national_id="000000026", phone="050-123-4569")
    assert error(client.post(REPORTS, json={"zone": ZONE}, headers=auth(sign_in(client, "other")))) == (403, "forbidden")
    assert error(client.post(REPORTS, json={"zone": ZONE})) == (401, "not_signed_in")
    answer = read(client, world["token"])
    assert [found["code"] for found in answer["reports"]] == CODES
    assert all(found["n"] == 0 and found["verify"]["median_ms"] is None for found in answer["reports"])
    # No attempt yet: the range is today alone.
    assert answer["range"]["from"] == answer["range"]["to"] and answer["range"]["unit"] == "day"


def test_a_methods_numbers(databases, world):
    noa, dana, enrolled = world["noa"], world["dana"], world["enrolled"]
    with Session(databases.biometric) as db, db.begin():
        for score, ms in ((614, 700), (383, 710), (58, 720), (57, 730), (8, 740)):
            attempt(db, noa, T0, score=score, ms=ms, enrolment_id=enrolled["noa"]["fingerprint"])
        attempt(db, noa, T0, mode="identify", score=579, gallery=6, top=enrolled["noa"]["fingerprint"], ms=1800)
        attempt(db, noa, T0, mode="identify", score=412, gallery=6, top=enrolled["dana"]["fingerprint"], ms=1900)
        attempt(db, dana, T0, mode="identify", score=266, gallery=6, ms=2000)  # its leader's enrolment was deleted
        attempt(db, dana, T0, mode="identify", score=17, gallery=6, ms=2100)  # not found
        attempt(db, noa, T0, algorithm="pore-sift", score=14, enrolment_id=enrolled["noa"]["fingerprint"])
    found = report(databases, "opencv-sift")
    assert (found["n"], found["modality"], found["scale"], found["threshold"], found["provisional"]) == \
        (9, "fingerprint", "pairs", 57.0, False)
    assert found["verify"] == {"n": 5, "accepted": 3, "rejected": 2, "own": 0, "other": 0, "gone": 0,
                               "median_ms": 720.0, "p90_ms": None}
    assert found["identify"] == {"n": 4, "accepted": 3, "rejected": 1, "own": 1, "other": 1, "gone": 1,
                                 "median_ms": 1950.0, "p90_ms": None}
    # Pairs double from bar to bar, aligned on 57: (6.25, 13.5], (13.5, 28], (28, 57], (57, 115], ... (463, 927].
    assert bars(found) == {-2: (0, 0, 1), -1: (0, 0, 1), 0: (0, 0, 1), 1: (1, 0, 0), 3: (3, 1, 0), 4: (2, 0, 0)}
    assert [bar["k"] for bar in found["bars"]] == list(range(-5, 5))
    first, last = found["bars"][0], found["bars"][-1]
    assert (first["low"], first["high"], last["low"], last["high"]) == (-0.09375, 0.8125, 463.0, 927.0)
    assert report(databases, "pore-sift")["n"] == 1 and report(databases, "pore-sift")["provisional"] is True
    assert report(databases, "sface")["n"] == 0


def test_the_ninetieth_percentile_comes_from_ten_attempts(databases, world):
    with Session(databases.biometric) as db, db.begin():
        for ms in range(100, 1001, 100):
            attempt(db, world["noa"], T0, modality="face", score=0.7, ms=ms,
                    enrolment_id=world["enrolled"]["noa"]["face"])
    found = report(databases, "sface")["verify"]
    # PostgreSQL's percentile_cont: 550 between the fifth and the sixth, 910 a tenth of the way from 900 to 1000.
    assert (found["n"], found["median_ms"]) == (10, 550.0) and found["p90_ms"] == pytest.approx(910.0)


def reference(scale: Scale, score: float) -> int:
    """The bar by its definition, as the key screens counted it: the first bar whose upper edge the score reaches."""
    k = scale.first()
    while score > scale.edge(k):
        k += 1
    return k


@pytest.mark.parametrize("name,threshold,known", [
    # (score, its bar): equal to the threshold is rejected and lies left of it; an edge closes its bar.
    ("pairs", 57.0, [(57, 0), (58, 1), (115, 1), (116, 2), (0, -5), (8, -2), (10_000, 8)]),
    ("similarity", 0.363, [(0.363, 0), (0.3630001, 1), (0.364, 1), (-0.9, -7), (1.0, 13)]),
    ("points", 75.0, [(75.0, 0), (75.5, 1), (80.0, 1), (80.01, 2), (0.0, -14), (5.0, -14), (100.0, 5)]),
])
def test_bars_close_at_their_edges_and_the_threshold_is_one(databases, name, threshold, known):
    scale = Scale(name, threshold)
    assert scale.edge(0) == threshold
    assert [reference(scale, score) for score, _ in known] == [bar for _, bar in known]
    # Every edge and the next number above it: PostgreSQL puts each score in the bar its definition gives.
    edges = [scale.edge(k) for k in range(scale.first() - 1, scale.last(None) + 1)]
    scores = [float(score) for score, _ in known] + edges + [math.nextafter(edge, math.inf) for edge in edges]
    with Session(databases.biometric) as db:
        for score in scores:
            assert db.scalar(select(scale.bar(literal(score, Double)))) == reference(scale, score), score


def test_a_score_equal_to_the_threshold_is_rejected_left_of_it(databases, world):
    noa, enrolled = world["noa"], world["enrolled"]
    with Session(databases.biometric) as db, db.begin():
        attempt(db, noa, T0, modality="face", score=0.363, enrolment_id=enrolled["noa"]["face"])
        attempt(db, noa, T0, modality="face", score=0.364, enrolment_id=enrolled["noa"]["face"])
        attempt(db, noa, T0, modality="face", score=-0.2, enrolment_id=enrolled["noa"]["face"])
    found = report(databases, "sface")
    assert bars(found) == {-7: (0, 0, 1), 0: (0, 0, 1), 1: (1, 0, 0)}
    # Similarities step by 0.05 from 0.363 and reach 1: the first bar holds 0 and everything below it.
    assert found["bars"][0]["k"] == -7 and found["bars"][-1]["k"] == 13
    assert found["bars"][0]["high"] == pytest.approx(0.013) and found["bars"][-1]["high"] == pytest.approx(1.013)


def test_the_days_follow_the_pcs_clock_around_midnight_and_the_clock_change(databases, world):
    # Israel's clock went back on Sunday 25 October 2026 at 02:00 (UTC+3 to UTC+2), so that day had 25 hours.
    noa, fingerprint = world["noa"], world["enrolled"]["noa"]["fingerprint"]
    moments = ["2026-10-20T20:59:59", "2026-10-20T21:00:00", "2026-10-24T21:30:00", "2026-10-25T21:30:00",
               "2026-10-25T22:30:00", "2026-10-26T21:59:59", "2026-10-26T22:00:00"]
    with Session(databases.biometric) as db, db.begin():
        for moment in moments:
            attempt(db, noa, datetime.fromisoformat(moment).replace(tzinfo=UTC), enrolment_id=fingerprint)
    answer = reports.reports(databases, Filters(dates="week"), ZONE, datetime(2026, 10, 27, 10, 0, tzinfo=UTC))
    assert answer["range"] == {"from": "2026-10-21", "to": "2026-10-27", "unit": "day", "slots": 7}
    found = report_of(answer, "opencv-sift")
    # 23:59:59 on the 20th is before the week; 00:30 and 23:30 on the 25th share it, on either side of the change.
    assert found["n"] == 6
    assert [slot["accepted"] for slot in found["slots"]] == [1, 0, 0, 0, 2, 2, 1]


def test_today_is_counted_by_the_hour_also_when_the_clock_changes(databases, world):
    noa, fingerprint = world["noa"], world["enrolled"]["noa"]["fingerprint"]
    with Session(databases.biometric) as db, db.begin():
        for moment, score in (("2026-10-24T20:30:00", 614), ("2026-10-24T22:30:00", 614), ("2026-10-24T23:30:00", 8),
                              ("2026-10-25T21:59:00", 614)):
            attempt(db, noa, datetime.fromisoformat(moment).replace(tzinfo=UTC), score=score, enrolment_id=fingerprint)
    answer = reports.reports(databases, Filters(dates="today"), ZONE, datetime(2026, 10, 25, 20, 0, tzinfo=UTC))
    assert answer["range"] == {"from": "2026-10-25", "to": "2026-10-25", "unit": "hour", "slots": 24}
    slots = report_of(answer, "opencv-sift")["slots"]
    # 01:30 came twice that night, once before the change and once after it; 23:30 on the 24th is not today.
    assert (slots[1], slots[23]) == ({"accepted": 1, "other": 0, "rejected": 1}, {"accepted": 1, "other": 0, "rejected": 0})
    assert sum(slot["accepted"] + slot["rejected"] for slot in slots) == 3


def test_a_long_range_is_counted_by_the_week(databases, world):
    noa, fingerprint = world["noa"], world["enrolled"]["noa"]["fingerprint"]
    first = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
    with Session(databases.biometric) as db, db.begin():
        for days in (0, 6, 7, 70):
            attempt(db, noa, first + timedelta(days=days), enrolment_id=fingerprint)
    answer = reports.reports(databases, Filters(), ZONE, first + timedelta(days=70, hours=3))
    # 71 days from the first attempt: more than 62, so eleven weeks of seven days from 1 September.
    assert answer["range"] == {"from": "2026-09-01", "to": "2026-11-10", "unit": "week", "slots": 11}
    assert [slot["accepted"] for slot in report_of(answer, "opencv-sift")["slots"]] == [2, 1, 0, 0, 0, 0, 0, 0, 0, 0, 1]


def test_the_filters_narrow_every_report(databases, world):
    noa, enrolled = world["noa"], world["enrolled"]
    with Session(databases.biometric) as db, db.begin():
        attempt(db, noa, NOW - timedelta(hours=1), modality="face", score=0.7, enrolment_id=enrolled["noa"]["face"])
        attempt(db, noa, NOW - timedelta(days=3), modality="face", score=0.2, source="file",
                enrolment_id=enrolled["noa"]["face"])
        attempt(db, noa, NOW - timedelta(days=20), modality="face", mode="identify", score=0.7, gallery=2,
                top=enrolled["noa"]["face"])
        attempt(db, noa, NOW - timedelta(days=40), modality="face", score=0.7, enrolment_id=enrolled["noa"]["face"])

    def count(**chosen) -> int:
        return report(databases, "sface", Filters(**chosen))["n"]

    assert (count(), count(dates="today"), count(dates="week"), count(dates="month")) == (4, 1, 2, 3)
    assert (count(mode="identify"), count(mode="verify"), count(source="file"), count(source="device")) == (1, 3, 1, 3)
    assert count(dates="week", source="device") == 1


def test_the_combined_tests_count_in_their_own_report_with_rescued_and_stopped(databases, world):
    noa, enrolled = world["noa"], world["enrolled"]["noa"]
    with Session(databases.biometric) as db, db.begin():
        tests = [combined(db, noa, T0 + timedelta(minutes=i), scores, enrolments=enrolled).id for i, scores in enumerate([
            {"fingerprint": 383, "face": 0.73, "voice": 0.75},  # accepted, as the fingerprint alone
            {"fingerprint": 30, "face": 0.73, "voice": 0.75},  # rescued: the fingerprint alone is not above 57
            {"fingerprint": 601, "face": 0.30, "voice": 0.75},  # stopped: the fingerprint alone is above 57
            {"fingerprint": 8, "face": 0.73, "voice": 0.75},  # rejected, as the fingerprint alone
        ])]
        attempt(db, noa, T0, enrolment_id=enrolled["fingerprint"])  # a comparison of its own
        decided = [(db.get_one(FusedAttempt, test).accepted, db.scalar(select(Attempt.accepted).where(
            Attempt.fused_attempt_id == test, Attempt.modality == "fingerprint"))) for test in tests]
    assert decided == [(True, True), (True, False), (False, True), (False, False)]
    answer = reports.reports(databases, Filters(), ZONE, NOW)
    found = report_of(answer, "combined")
    assert (found["n"], found["scale"], found["threshold"], found["modality"]) == (4, "points", 75.0, "combined")
    assert {key: found["verify"][key] for key in ("n", "accepted", "rejected", "rescued", "stopped")} == \
        {"n": 4, "accepted": 2, "rejected": 2, "rescued": 1, "stopped": 1}
    assert found["policy"] == {"id": 1, "weights": {"fingerprint": 55, "face": 25, "voice": 20}, "budget": 6.0,
                               "threshold": 75.0, "provisional": ["face", "voice"]}
    # Their comparisons count here only, as the history lists them inside their tests.
    assert [report_of(answer, code)["n"] for code in ("opencv-sift", "sface", "ecapa-voxceleb")] == [1, 0, 0]
    assert sum(sum(bar[key] for key in ("accepted", "rejected")) for bar in found["bars"]) == 4
    assert [bar["k"] for bar in found["bars"]] == list(range(-14, 6))


def test_whose_enrolment_led_a_found_search(databases, world):
    noa, dana, enrolled = world["noa"], world["dana"], world["enrolled"]
    strong = {"fingerprint": 614, "face": 0.73, "voice": 0.75}
    with Session(databases.biometric) as db, db.begin():
        combined(db, noa, T0, strong, mode="identify", tops=enrolled["noa"])
        combined(db, noa, T0, strong, mode="identify", tops=enrolled["dana"])
        combined(db, noa, T0, strong, mode="identify")  # its leader's enrolments are gone
        combined(db, dana, T0, {"fingerprint": 9, "face": 0.73, "voice": 0.75}, mode="identify", tops=enrolled["dana"])
    found = report(databases, "combined")["identify"]
    assert {key: found[key] for key in ("n", "accepted", "rejected", "own", "other", "gone")} == \
        {"n": 4, "accepted": 3, "rejected": 1, "own": 1, "other": 1, "gone": 1}
    led = report(databases, "combined")["bars"]
    assert sum(bar["other"] for bar in led) == 1


def test_decisions_made_with_an_earlier_threshold_keep_their_own(databases, world):
    noa, enrolled = world["noa"], world["enrolled"]["noa"]
    with Session(databases.biometric) as db, db.begin():
        earlier = attempt(db, noa, T0, score=55, enrolment_id=enrolled["fingerprint"])
        earlier.threshold, earlier.accepted = 50.0, True  # decided before the threshold became 57
        attempt(db, noa, T0, score=55, enrolment_id=enrolled["fingerprint"])
        combined(db, noa, T0, {"fingerprint": 383, "face": 0.73, "voice": 0.75}, enrolments=enrolled)
        stored = db.get_one(FusionPolicy, 1)
        db.add(FusionPolicy(id=2, created_at=T0, weight_fingerprint=55, weight_face=25, weight_voice=20, budget=6.0,
                            threshold=80.0, calibration=stored.calibration, origin="a later version, for this test"))
    found = report(databases, "opencv-sift")
    assert found["earlier"] == [{"threshold": 50.0, "n": 1}]
    assert bars(found) == {0: (1, 0, 1)}  # both at 55, left of 57: one accepted by its own threshold of 50
    tests = report(databases, "combined")
    assert (tests["threshold"], tests["policy"]["id"]) == (80.0, 2)
    assert tests["earlier"] == [{"policy": 1, "threshold": 75.0, "n": 1}]
    assert tests["bars"][0]["k"] == -15 and tests["bars"][-1]["high"] == 100.0  # 80 + 5k, from 0 to 100


def test_the_totals_are_the_historys_under_the_same_filters(client, databases, world):
    noa, dana, enrolled = world["noa"], world["dana"], world["enrolled"]
    now = datetime.now(UTC)
    with Session(databases.biometric) as db, db.begin():
        attempt(db, noa, now - timedelta(minutes=5), enrolment_id=enrolled["noa"]["fingerprint"])
        attempt(db, noa, now - timedelta(days=2), algorithm="learned-pore", score=12,
                enrolment_id=enrolled["noa"]["fingerprint"])
        attempt(db, dana, now - timedelta(days=9), modality="voice", mode="identify", score=0.733, gallery=6,
                top=enrolled["dana"]["voice"], source="file")
        attempt(db, dana, now - timedelta(days=31), modality="face", score=0.712, enrolment_id=enrolled["dana"]["face"])
        combined(db, noa, now - timedelta(hours=2), {"fingerprint": 383, "face": 0.73, "voice": 0.75},
                 enrolments=enrolled["noa"])
        combined(db, noa, now - timedelta(days=12), {"fingerprint": 8, "face": 0.73, "voice": 0.75}, mode="identify")
        midnight = {dates: db.scalar(text("SELECT timezone(:zone, CAST(CAST(timezone(:zone, now()) AS date)"
                                          " - CAST(:back AS integer) AS timestamp))").bindparams(zone=ZONE, back=back))
                    for dates, back in reports.DATES.items()}
    history = {"opencv-sift": {"type": "fingerprint", "method": "opencv-sift"},
               "pore-sift": {"type": "fingerprint", "method": "pore-sift"},
               "learned-pore": {"type": "fingerprint", "method": "learned-pore"},
               "sface": {"type": "face", "method": "sface"}, "ecapa-voxceleb": {"type": "voice", "method": "ecapa-voxceleb"},
               "combined": {"type": "combined"}}
    token = world["token"]
    for chosen in ({}, {"dates": "today"}, {"dates": "week"}, {"dates": "month"}, {"mode": "identify"},
                   {"source": "file"}, {"source": "device", "mode": "verify"}):
        answer = read(client, token, **chosen)
        for code, kind in history.items():
            asked = {**kind, **{key: value for key, value in chosen.items() if key != "dates"}}
            if "dates" in chosen:
                asked["since"] = midnight[chosen["dates"]].isoformat()
            listed = client.post("/api/admin/attempts/search", json=asked, headers=auth(token)).json()["total"]
            assert report_of(answer, code)["n"] == listed, (code, chosen)
    assert sum(found["n"] for found in read(client, token)["reports"]) == 6


def test_no_sealed_value_is_opened_and_nobody_is_named(client, databases, world, monkeypatch):
    noa, enrolled = world["noa"], world["enrolled"]
    with Session(databases.biometric) as db, db.begin():
        attempt(db, noa, T0, mode="identify", score=412, gallery=6, top=enrolled["dana"]["fingerprint"])
        combined(db, noa, T0, {"fingerprint": 614, "face": 0.73, "voice": 0.75}, mode="identify", tops=enrolled["dana"])

    def refuse(*args, **kwargs):
        raise AssertionError("a report opened a sealed value")

    monkeypatch.setattr(keyring, "open_sealed", refuse)
    answer = read(client, world["token"])
    text_ = json.dumps(answer)
    assert "noa.b" not in text_ and "Dana" not in text_ and PROBE.decode() not in text_ and "probe" not in text_
    assert report_of(answer, "opencv-sift")["identify"]["other"] == 1


@pytest.mark.parametrize("body,status,code", [
    ({"zone": "Mars/Olympus"}, 400, "unknown_time_zone"),
    ({"zone": "../etc/passwd"}, 422, None),
    ({}, 422, None),
    ({"zone": ZONE, "dates": "year"}, 422, None),
    ({"zone": ZONE, "mode": "both"}, 422, None),
    ({"zone": ZONE, "source": "phone"}, 422, None),
])
def test_unknown_zones_and_filters_are_refused(client, world, body, status, code):
    response = client.post(REPORTS, json=body, headers=auth(world["token"]))
    assert response.status_code == status, response.text
    if code is not None:
        assert response.json() == {"error": code}
