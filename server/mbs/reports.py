"""The administration area's reports (H62): for each method and for the combined test (H60), what its completed
comparisons decided, where their scores lie against the current threshold, how long they took and on which days they
were made, under the history's filters of dates, 1:1 or 1:N, and source.

Everything is counted in PostgreSQL, in one snapshot, and only sums leave it: no sample, probe, template, embedding or
identity link is read, so no sealed value is opened and nobody is named. A 1:N search that found someone was led by
the user's own enrolment, another registered user's, or one no longer enrolled, as the history shows it (H61).

A report counts what the history lists under the same filters: a method's report its comparisons of their own, the
combined test's report its tests. A comparison made inside a combined test counts there and not in its method's
report, as the history lists it inside its test; in 1:N its score is that of the person the combined score ranked
first, not of its own method's leader. The days are the PC's, in the time zone it names (checked against PostgreSQL's
own list), so each day starts at its own midnight, also on the days the clock changes."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CTE,
    Boolean,
    ColumnElement,
    Date,
    DateTime,
    Double,
    Integer,
    Select,
    case,
    cast,
    extract,
    false,
    func,
    literal,
    null,
    select,
    true,
)
from sqlalchemy.orm import InstrumentedAttribute, Session, aliased
from sqlalchemy.sql import column, table

from .db import Databases
from .fusion import policy_of
from .models import Algorithm, Attempt, Enrolment, FusedAttempt, FusionPolicy

METHODS = ("opencv-sift", "pore-sift", "learned-pore", "sface", "ecapa-voxceleb")
COMBINED = "combined"
MODES = ("verify", "identify")
MODALITY_ORDER = ("fingerprint", "face", "voice")
DATES = {"today": 0, "week": 6, "month": 29}  # days before today, as the history's filter counts them
HOURS = 24  # "today" is counted by the hour of the PC's clock
WEEKS_AFTER = 62  # a longer range is counted by the week: seven days at a time from its first day
PERCENTILE_FROM = 10  # the 90th percentile of the processing time is given from this many attempts on
SCALE_OF = {"fingerprint": "pairs", "face": "similarity", "voice": "similarity", COMBINED: "points"}
STEP = {"similarity": Decimal("0.05"), "points": Decimal(5)}
TOP = {"similarity": Decimal(1), "points": Decimal(100)}

_ZONES = table("pg_timezone_names", column("name"))
_known_zones: set[str] = set()


class ReportError(Exception):
    """An expected refusal of a report, answered as its code."""

    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code, self.status = code, status


@dataclass(frozen=True)
class Filters:
    dates: str | None = None  # today, week or month: from that day's midnight on; none: since the first attempt
    mode: str | None = None  # verify or identify
    source: str | None = None  # device or file; a combined test always takes the devices


@dataclass(frozen=True)
class Scale:
    """The bars of a report's scores, aligned so that the current threshold is an edge: bar k holds the scores above
    edge(k - 1) up to edge(k), and edge(0) is the threshold, so a score equal to the threshold lies left of it, as its
    decision does (accepted above the threshold). Fingerprint pairs double from bar to bar, which is ln(1 + pairs), the
    axis H60 calibrated the fingerprint on; similarities step by 0.05 and points by 5. The first bar also holds every
    score below it."""

    name: str  # pairs, similarity or points
    threshold: float

    def edge(self, k: int) -> float:
        # The same operations as the bars' SQL below, so both draw the same edges.
        if self.name == "pairs":
            return (self.threshold + 1) * 2.0 ** k - 1
        return self.threshold + float(STEP[self.name]) * k

    def first(self) -> int:
        if self.name == "pairs":
            return math.ceil(-math.log2(self.threshold + 1))  # the bar that holds 0 pairs
        steps = -Decimal(repr(self.threshold)) / STEP[self.name]
        if self.name == "similarity":
            return math.ceil(steps)  # the bar that holds a similarity of 0, and every one below it
        return math.floor(steps) + 1  # points start at 0, so their first bar starts there

    def last(self, highest: int | None) -> int:
        reached = self.first() if highest is None else highest
        if self.name == "pairs":
            return max(reached, 1)  # at least one bar above the threshold
        return max(reached, math.ceil((TOP[self.name] - Decimal(repr(self.threshold))) / STEP[self.name]))

    def bar(self, score: ColumnElement[float] | InstrumentedAttribute[float]) -> ColumnElement:
        """A score's bar, computed in PostgreSQL: an estimate, then corrected against the edges themselves, so that
        rounding can never move a score across one."""
        t = self.threshold
        if self.name == "pairs":
            estimate = func.ceil(func.ln((score + 1) / (t + 1), type_=Double) / math.log(2), type_=Double)

            def edge(k: ColumnElement) -> ColumnElement:
                return (t + 1) * func.power(2.0, k, type_=Double) - 1
        else:
            step = float(STEP[self.name])
            estimate = func.ceil((score - t) / step, type_=Double)

            def edge(k: ColumnElement) -> ColumnElement:
                return t + step * k
        k = estimate - case((score <= edge(estimate - 1), 1), else_=0) + case((score > edge(estimate), 1), else_=0)
        return func.greatest(cast(k, Integer), self.first())


@dataclass(frozen=True)
class Range:
    start: date  # the first day counted
    end: date  # today, on the PC's clock
    unit: str  # hour, day or week
    slots: int

    def json(self) -> dict:
        return {"from": self.start.isoformat(), "to": self.end.isoformat(), "unit": self.unit, "slots": self.slots}


def _check_zone(db: Session, zone: str) -> None:
    if zone in _known_zones:
        return
    if not db.scalar(select(func.count()).select_from(_ZONES).where(_ZONES.c.name == zone)):
        raise ReportError("unknown_time_zone")
    _known_zones.add(zone)


def _local(zone: str, at: Any) -> ColumnElement:
    """A moment as the PC's clock shows it, in the zone it names."""
    return func.timezone(zone, at, type_=DateTime())


def _range(db: Session, filters: Filters, zone: str, now: datetime) -> Range:
    today = db.scalar(select(cast(_local(zone, literal(now, DateTime(timezone=True))), Date)))
    assert today is not None, "PostgreSQL gives every moment a date"
    if filters.dates is not None:
        start = today - timedelta(days=DATES[filters.dates])
    else:
        # Since the system's first attempt, of any kind and whatever the other filters are.
        earliest = func.least(select(func.min(Attempt.at)).scalar_subquery(),
                              select(func.min(FusedAttempt.at)).scalar_subquery())
        first = db.scalar(select(cast(_local(zone, earliest), Date)))
        start = min(first, today) if first is not None else today
    days = (today - start).days + 1
    if filters.dates == "today":
        return Range(start, today, "hour", HOURS)
    if days > WEEKS_AFTER:
        return Range(start, today, "week", -(-days // 7))
    return Range(start, today, "day", days)


def _slot(at: Any, zone: str, period: Range) -> ColumnElement:
    """The hour, day or week a moment falls in, counted from the range's first one."""
    local = _local(zone, at)
    if period.unit == "hour":
        return cast(extract("hour", local), Integer)
    days = cast(local, Date) - literal(period.start, Date)  # an integer number of days
    return days if period.unit == "day" else days // 7


def _since(zone: str, period: Range, filters: Filters) -> ColumnElement | None:
    """The first moment counted: the midnight that starts the range, as the history's date filter has it."""
    if filters.dates is None:
        return None
    return func.timezone(zone, literal(datetime.combine(period.start, time.min), DateTime()),
                         type_=DateTime(timezone=True))


def _method_rows(code: str, scale: Scale, filters: Filters, zone: str, period: Range) -> CTE:
    """A method's comparisons of their own, as the history lists them under the same filters."""
    lead = aliased(Enrolment)
    whose = case((Attempt.top_enrolment_id.is_(None), "gone"), (lead.subject_id == Attempt.subject_id, "own"),
                 else_="other")
    where: list[ColumnElement] = [Attempt.fused_attempt_id.is_(None), Attempt.algorithm == code]
    since = _since(zone, period, filters)
    if since is not None:
        where.append(Attempt.at >= since)
    if filters.mode is not None:
        where.append(Attempt.mode == filters.mode)
    if filters.source is not None:
        where.append(Attempt.source == filters.source)
    return (select(Attempt.mode.label("mode"), Attempt.accepted.label("accepted"),
                   case((Attempt.mode == "identify", whose), else_=null()).label("leader"),
                   Attempt.threshold.label("threshold"), cast(null(), Integer).label("policy"),
                   Attempt.duration_ms.label("ms"), cast(null(), Boolean).label("alone"),
                   scale.bar(Attempt.score).label("k"),
                   _slot(Attempt.at, zone, period).label("slot"))
            .select_from(Attempt).outerjoin(lead, lead.id == Attempt.top_enrolment_id)
            .where(*where).cte("rows"))


def _test_rows(scale: Scale, filters: Filters, zone: str, period: Range) -> CTE:
    """The combined tests, each with its fingerprint comparison's own decision (`alone`) and, in 1:N, whose enrolment
    the person ranked first had: each comparison names that person's enrolment in its modality, so the first link
    still there tells it, as in the history."""
    part, owner, finger = aliased(Attempt), aliased(Enrolment), aliased(Attempt)
    order = case({modality: index for index, modality in enumerate(MODALITY_ORDER)}, value=part.modality)
    lead = (select(owner.subject_id.label("subject"), part.top_enrolment_id.label("top"))
            .select_from(part).outerjoin(owner, owner.id == part.top_enrolment_id)
            .where(part.fused_attempt_id == FusedAttempt.id, part.top_enrolment_id.is_not(None))
            .order_by(order).limit(1).lateral("lead"))
    whose = case((lead.c.top.is_(None), "gone"), (lead.c.subject == FusedAttempt.subject_id, "own"), else_="other")
    where: list[ColumnElement] = []
    since = _since(zone, period, filters)
    if since is not None:
        where.append(FusedAttempt.at >= since)
    if filters.mode is not None:
        where.append(FusedAttempt.mode == filters.mode)
    if filters.source is not None and filters.source != "device":
        where.append(false())
    return (select(FusedAttempt.mode.label("mode"), FusedAttempt.accepted.label("accepted"),
                   case((FusedAttempt.mode == "identify", whose), else_=null()).label("leader"),
                   FusedAttempt.threshold.label("threshold"), FusedAttempt.policy_id.label("policy"),
                   FusedAttempt.duration_ms.label("ms"), finger.accepted.label("alone"),
                   scale.bar(FusedAttempt.score).label("k"), _slot(FusedAttempt.at, zone, period).label("slot"))
            .select_from(FusedAttempt)
            .outerjoin(finger, (finger.fused_attempt_id == FusedAttempt.id) & (finger.modality == "fingerprint"))
            .outerjoin(lead, true())
            .where(*where).cte("tests"))


def _counts(rows: CTE, key: ColumnElement) -> Select:
    """Accepted (found, in 1:N), of them led by another registered user, and rejected, for each value of the key."""
    accepted = rows.c.accepted
    return (select(key.label("key"), func.count().filter(accepted).label("accepted"),
                   func.count().filter(accepted & (rows.c.leader == "other")).label("other"),
                   func.count().filter(~accepted).label("rejected"))
            .group_by(key))


def _modes(db: Session, rows: CTE, combined: bool) -> dict[str, dict]:
    accepted = rows.c.accepted
    columns = [rows.c.mode, func.count().label("n"), func.count().filter(accepted).label("accepted"),
               *[func.count().filter(accepted & (rows.c.leader == whose)).label(whose) for whose in ("own", "other", "gone")],
               func.percentile_cont(0.5).within_group(cast(rows.c.ms, Double)).label("median"),
               func.percentile_cont(0.9).within_group(cast(rows.c.ms, Double)).label("p90")]
    if combined:
        # Where the combined decision differs from the fingerprint comparison's own: rescued and stopped.
        columns += [func.count().filter(accepted & rows.c.alone.is_(False)).label("rescued"),
                    func.count().filter(~accepted & rows.c.alone.is_(True)).label("stopped")]
    found = {row.mode: row for row in db.execute(select(*columns).group_by(rows.c.mode))}
    figures = {}
    for mode in MODES:
        row = found.get(mode)
        n = row.n if row is not None else 0
        figure: dict[str, Any] = {
            "n": n, "accepted": row.accepted if row else 0, "rejected": n - (row.accepted if row else 0),
            "own": row.own if row else 0, "other": row.other if row else 0, "gone": row.gone if row else 0,
            "median_ms": row.median if row else None,
            "p90_ms": row.p90 if row is not None and n >= PERCENTILE_FROM else None,
        }
        if combined:
            figure.update(rescued=row.rescued if row else 0, stopped=row.stopped if row else 0)
        figures[mode] = figure
    return figures


def _bars(db: Session, rows: CTE, scale: Scale) -> list[dict]:
    counted = {row.key: row for row in db.execute(_counts(rows, rows.c.k))}
    first, last = scale.first(), scale.last(max(counted) if counted else None)
    bars = []
    for k in range(first, last + 1):
        row = counted.get(k)
        bars.append({"k": k, "low": scale.edge(k - 1), "high": scale.edge(k), "accepted": row.accepted if row else 0,
                     "other": row.other if row else 0, "rejected": row.rejected if row else 0})
    return bars


def _slots(db: Session, rows: CTE, period: Range) -> list[dict]:
    counted = {row.key: row for row in db.execute(_counts(rows, rows.c.slot))}
    return [{"accepted": counted[i].accepted, "other": counted[i].other, "rejected": counted[i].rejected}
            if i in counted else {"accepted": 0, "other": 0, "rejected": 0} for i in range(period.slots)]


def _report(db: Session, code: str, modality: str, scale: Scale, rows: CTE) -> dict[str, Any]:
    modes = _modes(db, rows, code == COMBINED)
    return {"code": code, "modality": modality, "scale": scale.name, "threshold": scale.threshold,
            "n": sum(mode["n"] for mode in modes.values()), **modes, "bars": _bars(db, rows, scale)}


def reports(databases: Databases, filters: Filters, zone: str, now: datetime | None = None) -> dict[str, Any]:
    """Every report under the filters, the five methods' and the combined test's, so that choosing another report
    needs no new request; with the range of days they cover."""
    moment = now or datetime.now(UTC)
    with Session(databases.biometric) as db:
        # One snapshot for every number, so attempts saved meanwhile change none of them against the others.
        db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        _check_zone(db, zone)
        period = _range(db, filters, zone, moment)
        algorithms = {row.code: row for row in db.scalars(select(Algorithm).where(Algorithm.code.in_(METHODS)))}
        found = []
        for code in METHODS:
            algorithm = algorithms[code]
            scale = Scale(SCALE_OF[algorithm.modality], algorithm.threshold)
            rows = _method_rows(code, scale, filters, zone, period)
            report = _report(db, code, algorithm.modality, scale, rows)
            report["provisional"] = algorithm.threshold_provisional
            report["slots"] = _slots(db, rows, period)
            # Attempts decided with another threshold than today's keep their own decision (H63 may change one).
            report["earlier"] = [{"threshold": row.threshold, "n": row.n} for row in db.execute(
                select(rows.c.threshold, func.count().label("n")).where(rows.c.threshold != algorithm.threshold)
                .group_by(rows.c.threshold).order_by(rows.c.threshold))]
            found.append(report)
        stored = db.scalar(select(FusionPolicy).order_by(FusionPolicy.id.desc()).limit(1))
        if stored is not None:
            policy = policy_of(stored)
            scale = Scale(SCALE_OF[COMBINED], policy.threshold)
            rows = _test_rows(scale, filters, zone, period)
            report = _report(db, COMBINED, COMBINED, scale, rows)
            report["policy"] = {"id": policy.id, "weights": policy.weights, "budget": policy.budget,
                                "threshold": policy.threshold,
                                "provisional": [m for m in MODALITY_ORDER
                                                if policy.calibration.get(m, {}).get("provisional")]}
            report["slots"] = _slots(db, rows, period)
            # Tests decided by an earlier version of the policy (H64 may add one) keep their own decision.
            report["earlier"] = [{"policy": row.policy, "threshold": row.threshold, "n": row.n} for row in db.execute(
                select(rows.c.policy, rows.c.threshold, func.count().label("n")).where(rows.c.policy != policy.id)
                .group_by(rows.c.policy, rows.c.threshold).order_by(rows.c.policy))]
            found.append(report)
    return {"range": period.json(), "reports": found}
