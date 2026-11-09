"""H44: pore illustrations from the comparison that decided, with the pores each template was described from."""

import base64
import struct

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from mbs.models import Attempt

from test_fingerprint import finger, fp_client, plan, script, service  # noqa: F401
from test_learned_verification import add_learned
from test_pore_verification import add_pore, verify
from test_verification import enrolled


def observe(monkeypatch, engine):
    calls, request = [], engine.request

    def record(header, parts):
        calls.append((header["op"], header.get("view") is True, list(parts)))
        return request(header, parts)

    monkeypatch.setattr(engine, "request", record)
    return calls


def test_pore_sift_pairs_come_from_every_scoring_comparison(fp_client, script, service, monkeypatch):
    add_pore(service)
    token = enrolled(fp_client, script)
    calls = observe(monkeypatch, service.pore)
    plan(script, finger("q60:A4"))
    result = verify(fp_client, token)[-1]
    assert result["type"] == "verified" and result["algorithm"] == "pore-sift"
    compares = [call for call in calls if call[0] == "compare"]
    assert len(compares) == 3 and all(view and len(parts) == 2 for _, view, parts in compares)
    view = result["match_view"]
    assert view["placement"] == 1 and view["count"] == result["score"] == 45
    assert base64.b64decode(view["reference_image"]) == b"FAKEPNG:q60:A1"
    assert base64.b64decode(view["pairs"]) == struct.pack("<4f", 10, 20, 30, 40) * 45


@pytest.mark.parametrize("stored_pores", [True, False])
def test_learned_pairs_repeat_the_winning_comparison_with_its_pores(fp_client, script, service, monkeypatch, stored_pores):
    if stored_pores:
        add_pore(service)  # the enrolment then stores Pore SIFT templates, whose points the Pore CNN ones reuse
    token = enrolled(fp_client, script)
    add_learned(service)
    detections, learned = observe(monkeypatch, service.pore), observe(monkeypatch, service.learned)

    def detected():
        return sum(1 for op, _, _ in detections if op == "detect")

    plan(script, finger("q60:A4"))
    first = verify(fp_client, token, "learned-pore")[-1]
    assert first["type"] == "verified" and first["match_view"]["count"] == first["score"] == 30
    # The probe is detected once. Templates prepared in this run keep their own detection for the view.
    assert detected() == (1 if stored_pores else 4)
    views = [parts for op, view, parts in learned if op == "compare" and view]
    assert len(views) == 1 and len(views[0]) == 4
    before = detected()
    plan(script, finger("q60:A5"))
    second = verify(fp_client, token, "learned-pore")[-1]
    assert second["match_view"]["placement"] == 1 and second["match_view"]["count"] == 30
    # Without a stored Pore SIFT template, the pinned detector finds the winning capture's pores again.
    assert detected() - before == (1 if stored_pores else 2)


def test_learned_view_of_a_non_match_uses_the_highest_comparison(fp_client, script, service):
    add_pore(service)
    token = enrolled(fp_client, script)
    add_learned(service)
    plan(script, finger("q60:B1"))
    result = verify(fp_client, token, "learned-pore")[-1]
    assert result["accepted"] is False and result["score"] == 2
    view = result["match_view"]
    assert view["placement"] == 1 and view["count"] == 2
    assert base64.b64decode(view["pairs"]) == struct.pack("<4f", 10, 20, 30, 40) * 2


def test_a_changed_repeated_score_fails_the_run_before_saving(fp_client, script, service, databases, monkeypatch):
    add_pore(service)
    token = enrolled(fp_client, script)
    add_learned(service)
    original = service.learned.request

    def drift(header, parts):
        reply, data = original(header, parts)
        if header.get("view") is True:
            return {**reply, "score": reply["score"] - 1, "matches": reply["score"] - 1}, [data[0][16:]]
        return reply, data

    monkeypatch.setattr(service.learned, "request", drift)
    plan(script, finger("q60:A4"))
    assert verify(fp_client, token, "learned-pore")[-1] == {"type": "failed", "error": "engine_unavailable"}
    with Session(databases.biometric) as db:
        assert db.scalars(select(Attempt)).all() == []
