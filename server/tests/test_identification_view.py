"""H18, H45: a 1:N result illustrates only the caller's own highest-ranked print among the shown candidates."""

import base64
import struct

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from mbs import identification
from mbs.models import Attempt

from test_fingerprint import finger, fp_client, plan, script, service  # noqa: F401
from test_identification import identify, other_enrolled
from test_learned_verification import add_learned
from test_pore_verification import add_pore
from test_verification import enrolled


def observe(monkeypatch, engines):
    calls = []
    for engine in engines:
        request = engine.request

        def record(header, parts, request=request):
            calls.append((header["op"], header.get("view") is True, len(parts)))
            return request(header, parts)

        monkeypatch.setattr(engine, "request", record)
    return calls


@pytest.mark.parametrize("probe,rank,score", [("A4", 1, 90), ("B4", 2, 5)])
def test_the_callers_own_highest_print_is_illustrated_never_another_users(fp_client, script, service, monkeypatch, probe, rank, score):
    token = enrolled(fp_client, script)  # the caller's finger 7: A1, A2, A3
    other_enrolled(fp_client, script)  # another user's finger 2: B1, B2, B3
    calls = observe(monkeypatch, service.search_engines())
    plan(script, finger(f"q60:{probe}"))
    result = identify(fp_client, token)[-1]
    assert result["type"] == "identified" and result["candidates"][rank - 1]["own"] is True
    view = result["match_view"]
    # Equal placement scores keep the earliest placement, as in H43.
    assert (view["rank"], view["finger"], view["placement"], view["count"]) == (rank, 7, 1, score)
    assert base64.b64decode(view["reference_image"]) == b"FAKEPNG:q60:A1"
    assert base64.b64decode(view["pairs"]) == struct.pack("<4f", 10, 20, 30, 40) * score
    assert [call for call in calls if call[1]] == [("compare", True, 2)]


def test_no_illustration_when_none_of_the_shown_candidates_is_the_callers(fp_client, script, service, monkeypatch):
    token = enrolled(fp_client, script)
    other_enrolled(fp_client, script)
    monkeypatch.setattr(identification, "SHOWN_CANDIDATES", 1)
    calls = observe(monkeypatch, service.search_engines())
    plan(script, finger("q60:B4"))
    result = identify(fp_client, token)[-1]
    assert result["type"] == "identified" and [c["own"] for c in result["candidates"]] == [False]
    assert "match_view" not in result and not any(view for _, view, _ in calls)


@pytest.mark.parametrize("stored_pores", [True, False])
def test_learned_illustration_uses_the_pores_its_templates_were_described_from(fp_client, script, service, monkeypatch, stored_pores):
    if stored_pores:
        add_pore(service)  # both enrolments then store Pore SIFT templates
    token = enrolled(fp_client, script)
    other_enrolled(fp_client, script)
    add_learned(service)
    detections = observe(monkeypatch, [service.pore])
    learned = observe(monkeypatch, [service.learned])

    def detected():
        return sum(1 for op, _, _ in detections if op == "detect")

    plan(script, finger("q60:A4"))
    first = identify(fp_client, token, algorithm="learned-pore")[-1]
    assert first["type"] == "identified" and first["match_view"]["count"] == first["score"] == 30
    # One probe detection; without stored pores the six gallery captures are detected once for preparation,
    # and the caller's winning capture reuses that detection.
    assert detected() == (1 if stored_pores else 7)
    assert [parts for op, view, parts in learned if view] == [4]
    before = detected()
    plan(script, finger("q60:A5"))
    second = identify(fp_client, token, algorithm="learned-pore")[-1]
    assert second["match_view"]["placement"] == 1 and second["match_view"]["finger"] == 7
    assert detected() - before == (1 if stored_pores else 2)


def test_a_changed_repeated_score_fails_the_search_before_saving(fp_client, script, service, databases, monkeypatch):
    token = enrolled(fp_client, script)
    for engine in service.search_engines():
        original = engine.request

        def drift(header, parts, request=original):
            reply, data = request(header, parts)
            if header.get("view") is True:
                return {**reply, "score": reply["score"] - 1, "matches": reply["score"] - 1}, [data[0][16:]]
            return reply, data

        monkeypatch.setattr(engine, "request", drift)
    plan(script, finger("q60:A4"))
    assert identify(fp_client, token)[-1] == {"type": "failed", "error": "engine_unavailable"}
    with Session(databases.biometric) as db:
        assert db.scalars(select(Attempt)).all() == []
