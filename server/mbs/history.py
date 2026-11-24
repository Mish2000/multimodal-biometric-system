"""The administration area's attempt history (H61): every comparison by every user, newest first, read in pages of
at most 50 and filtered, single comparisons and combined tests (H60) alike. A combined test is one row that carries
its comparisons; they are not listed again on their own.

Only outcomes are read. No sample, probe, template or embedding is loaded or opened; the one sealed value opened is
the identity link of each user account, which turns subject identifiers into usernames (H12, H25). The leader of a
1:N search is never named: it was the user's own enrolment, another registered user's, or one no longer enrolled
(the researcher's choice of 2026-11-23, as H18 shows other users to a user)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import ColumnElement, CompoundSelect, false, func, literal, select, tuple_, union_all
from sqlalchemy.orm import Session, aliased

from . import keys as keyring
from .db import Databases
from .fusion import Policy, cap, points, policy_of
from .keys import Keys
from .models import DISABLED, Account, Algorithm, Attempt, Enrolment, FusedAttempt, FusionPolicy, IdentityLink

PAGE = 50
COMBINED = "combined"
MODALITY_ORDER = ("fingerprint", "face", "voice")


@dataclass(frozen=True)
class Filters:
    since: datetime | None = None  # from this moment on
    until: datetime | None = None  # before this moment
    user: str | None = None  # a part of the username, in any case
    type: str | None = None  # fingerprint, face, voice or combined
    mode: str | None = None  # verify or identify
    method: str | None = None  # a method's code: only single comparisons have one
    result: str | None = None  # accepted (found, in 1:N) or rejected (not found)
    source: str | None = None  # device or file; a combined test always takes the devices


@dataclass(frozen=True)
class Person:
    username: str
    disabled: bool


def people(databases: Databases, keys: Keys) -> dict[uuid.UUID, Person]:
    """Every user account's subject, opened from its sealed identity link (H3), with its username and status.
    Administrators have no link and no subject (H12)."""
    with Session(databases.accounts) as db:
        rows = db.execute(select(IdentityLink.account_id, IdentityLink.subject, Account.username, Account.status)
                          .join(Account, Account.id == IdentityLink.account_id)).all()
    found = {}
    for account_id, sealed, username, status in rows:
        subject = uuid.UUID(bytes=keyring.open_sealed(keys, keyring.IDENTITY_LINK, account_id.bytes, sealed))
        found[subject] = Person(username, status == DISABLED)
    return found


def _conditions(filters: Filters, subjects: list[uuid.UUID] | None, at, subject, accepted) -> list[ColumnElement]:
    """The filters both kinds of row take alike: the dates, the users and the result."""
    where: list[ColumnElement] = []
    if filters.since is not None:
        where.append(at >= filters.since)
    if filters.until is not None:
        where.append(at < filters.until)
    if subjects is not None:
        where.append(subject.in_(subjects))
    if filters.result is not None:
        where.append(accepted == (filters.result == "accepted"))
    return where


def _rows(filters: Filters, subjects: list[uuid.UUID] | None) -> CompoundSelect:
    """Single comparisons and combined tests as one list of (kind, id, at), filtered."""
    singles = [Attempt.fused_attempt_id.is_(None),
               *_conditions(filters, subjects, Attempt.at, Attempt.subject_id, Attempt.accepted)]
    tests = _conditions(filters, subjects, FusedAttempt.at, FusedAttempt.subject_id, FusedAttempt.accepted)
    if filters.type == COMBINED:
        singles.append(false())
    elif filters.type is not None:
        singles.append(Attempt.modality == filters.type)
        tests.append(false())
    if filters.mode is not None:
        singles.append(Attempt.mode == filters.mode)
        tests.append(FusedAttempt.mode == filters.mode)
    if filters.method is not None:
        singles.append(Attempt.algorithm == filters.method)
        tests.append(false())
    if filters.source is not None:
        singles.append(Attempt.source == filters.source)
        if filters.source != "device":
            tests.append(false())
    return union_all(
        select(literal("attempt").label("kind"), Attempt.id.label("id"), Attempt.at.label("at")).where(*singles),
        select(literal(COMBINED).label("kind"), FusedAttempt.id.label("id"), FusedAttempt.at.label("at")).where(*tests))


def _leader(top: uuid.UUID | None, leader_subject: uuid.UUID | None, subject: uuid.UUID) -> str:
    if top is None:
        return "gone"
    return "own" if leader_subject == subject else "other"


def _user(found: dict[uuid.UUID, Person], subject: uuid.UUID) -> dict | None:
    person = found.get(subject)
    return None if person is None else {"username": person.username, "disabled": person.disabled}


def _singles(db: Session, ids: list[uuid.UUID], found: dict[uuid.UUID, Person]) -> dict[uuid.UUID, dict]:
    leader = aliased(Enrolment)
    source = aliased(Attempt)
    rows = db.execute(
        select(Attempt.id, Attempt.at, Attempt.subject_id, Attempt.modality, Attempt.mode, Attempt.algorithm,
               Attempt.score, Attempt.threshold, Attempt.accepted, Attempt.duration_ms, Attempt.source,
               Attempt.gallery_size, Attempt.top_enrolment_id, leader.subject_id, source.at,
               Algorithm.threshold_provisional)
        .join(Algorithm, Algorithm.code == Attempt.algorithm)
        .outerjoin(leader, leader.id == Attempt.top_enrolment_id)
        .outerjoin(source, source.id == Attempt.capture_attempt_id)
        .where(Attempt.id.in_(ids))).all()
    shown = {}
    for (id_, at, subject, modality, mode, algorithm, score, threshold, accepted, duration_ms, origin, gallery_size,
         top, leader_subject, captured_at, provisional) in rows:
        shown[id_] = {
            "kind": "attempt", "id": str(id_), "at": at.astimezone(UTC).isoformat(), "user": _user(found, subject),
            "modality": modality, "mode": mode, "algorithm": algorithm, "provisional": provisional,
            "score": score, "threshold": threshold, "accepted": accepted, "duration_ms": duration_ms,
            "source": origin, "gallery_size": gallery_size,
            "leader": _leader(top, leader_subject, subject) if mode == "identify" else None,
            "capture_of": captured_at.astimezone(UTC).isoformat() if captured_at is not None else None,
        }
    return shown


def _part(policy: Policy, modality: str, algorithm: str, score: float, threshold: float, accepted: bool,
          evidence: float) -> dict:
    limit = cap(policy, modality)
    return {"modality": modality, "algorithm": algorithm, "score": score, "threshold": threshold, "accepted": accepted,
            "evidence": evidence, "capped": limit > 0 and abs(abs(evidence) - limit) < 1e-9,
            "points": points(policy, modality, evidence), "weight": policy.weights[modality]}


def _tests(db: Session, ids: list[uuid.UUID], found: dict[uuid.UUID, Person]) -> dict[uuid.UUID, dict]:
    tests = db.execute(
        select(FusedAttempt.id, FusedAttempt.at, FusedAttempt.subject_id, FusedAttempt.mode, FusedAttempt.policy_id,
               FusedAttempt.score, FusedAttempt.threshold, FusedAttempt.accepted, FusedAttempt.evidence,
               FusedAttempt.duration_ms, FusedAttempt.gallery_size)
        .where(FusedAttempt.id.in_(ids))).all()
    if not tests:
        return {}
    policies = {row.id: policy_of(row) for row in db.scalars(
        select(FusionPolicy).where(FusionPolicy.id.in_({test.policy_id for test in tests})))}
    leader = aliased(Enrolment)
    parts: dict[uuid.UUID | None, list] = {}  # the key is never None here: only comparisons of these tests
    for row in db.execute(
            select(Attempt.fused_attempt_id, Attempt.modality, Attempt.algorithm, Attempt.score, Attempt.threshold,
                   Attempt.accepted, Attempt.evidence, Attempt.top_enrolment_id, leader.subject_id)
            .outerjoin(leader, leader.id == Attempt.top_enrolment_id)
            .where(Attempt.fused_attempt_id.in_(ids))).all():
        parts.setdefault(row[0], []).append(row)
    shown = {}
    for (id_, at, subject, mode, policy_id, score, threshold, accepted, evidence, duration_ms,
         gallery_size) in tests:
        policy = policies[policy_id]
        mine = sorted(parts.get(id_, []), key=lambda part: MODALITY_ORDER.index(part[1]))
        leader_state = None
        if mode == "identify":
            # Each comparison names the leader's enrolment in its modality: the same person, so the first link that
            # is still there tells whose it was.
            linked = [part for part in mine if part[7] is not None]
            leader_state = _leader(linked[0][7], linked[0][8], subject) if linked else "gone"
        shown[id_] = {
            "kind": COMBINED, "id": str(id_), "at": at.astimezone(UTC).isoformat(), "user": _user(found, subject), "mode": mode,
            "policy": policy_id, "weights": policy.weights, "budget": policy.budget, "score": score,
            "threshold": threshold, "accepted": accepted, "evidence": evidence, "duration_ms": duration_ms,
            "gallery_size": gallery_size, "leader": leader_state,
            "parts": [_part(policy, part[1], part[2], part[3], part[4], part[5], part[6]) for part in mine],
        }
    return shown


def search(databases: Databases, keys: Keys, filters: Filters, after: tuple[datetime, uuid.UUID] | None = None,
           limit: int = PAGE) -> dict[str, Any]:
    """One page of the history, newest first, after the given row when paging on (keyset paging by time and id,
    so rows saved meanwhile never shift a page), with the number of rows the filters match."""
    found = people(databases, keys)
    subjects = None
    if filters.user:
        needle = filters.user.casefold()
        subjects = [subject for subject, person in found.items() if needle in person.username.casefold()]
        if not subjects:
            return {"rows": [], "total": 0, "next": None}
    listed = _rows(filters, subjects).subquery()
    with Session(databases.biometric) as db:
        total = db.scalar(select(func.count()).select_from(listed)) or 0
        page = select(listed.c.kind, listed.c.id, listed.c.at)
        if after is not None:
            page = page.where(tuple_(listed.c.at, listed.c.id) < tuple_(*after))
        chosen = db.execute(page.order_by(listed.c.at.desc(), listed.c.id.desc()).limit(limit + 1)).all()
        more = len(chosen) > limit
        chosen = chosen[:limit]
        singles = _singles(db, [row.id for row in chosen if row.kind == "attempt"], found)
        tests = _tests(db, [row.id for row in chosen if row.kind == COMBINED], found)
    rows = [singles[row.id] if row.kind == "attempt" else tests[row.id] for row in chosen]
    last = chosen[-1] if more else None
    return {"rows": rows, "total": total,
            "next": {"at": last.at.astimezone(UTC).isoformat(), "id": str(last.id)} if last is not None else None}
