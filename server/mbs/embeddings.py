"""What the face and the voice share (H48 to H57). Both describe a finding, an image or a recording, as one embedding
of a pinned model, keep three findings per enrolment, compare them by pgvector's cosine similarity and decide strictly
above the threshold. Their flows are written here once: enrolment and its save, deletion, verification (1:1) and
identification (1:N), with the engine's service and the refusal they answer with. Each modality module describes
itself in a `Modality`: its names and rules, and its own steps, such as how a finding is checked and what of it is
sealed.

1:N over face and voice embeddings (H50, H56): the gallery is the current enrolments of the modality of the active user
accounts, found through their sealed identity links (H41), each with its three embeddings of the pinned model version;
it is fixed, with the threshold, when the new finding arrives. One SQL statement ranks the enrolments by their highest
cosine similarity, an exact pgvector search without an index (docs/data-model.md): a window function keeps each
enrolment's highest score and its earliest placement, and the enrolments are ordered by score, then by enrolment, so
equal leaders always come in the same order and are reported as a tie. Before the save, the accounts are locked first,
then the enrolments, and both are compared with the gallery again: a deletion, a new enrolment, a disabled account or a
changed template since the start ends the search unsaved (H41). Only the caller's own enrolment is named; the others
have a rank for this attempt alone (H18).
"""

from __future__ import annotations

import base64
import itertools
import threading
import time
import uuid
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import CursorResult, Row, bindparam, delete, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from . import keys as keyring
from .db import Databases
from .engines import Engine, EngineError
from .fingerprint import best_three
from .identification import SHOWN_CANDIDATES, Owner, active_owners, owners_unchanged
from .keys import Keys
from .models import Algorithm, Attempt, Enrolment, Sample, Template, vector_text, vector_values

CAPTURE_AGE = timedelta(minutes=30)  # an enrolment's images or recordings were taken in the last half hour
CLOCK_SKEW = timedelta(minutes=1)


def _db(engine) -> DbSession:
    return DbSession(engine, expire_on_commit=False)


class ModalityError(Exception):
    """A refused face or voice request, answered as {"error": code, ...}."""

    def __init__(self, code: str, status: int = 422, **extra):
        super().__init__(code)
        self.code, self.status, self.extra = code, status, extra


@dataclass
class EngineService:
    """A modality's engine (H13), started in the background with the server, so the first request does not wait for
    its model to load."""
    engine: Engine

    def warm_up(self) -> None:
        def start():
            try:
                self.engine.start()
            except EngineError:
                pass  # reported when a request needs it
        threading.Thread(target=start, daemon=True).start()

    def close(self) -> None:
        self.engine.close()


@dataclass(frozen=True)
class Modality:
    """One embedding modality as the shared flows see it: its names, its rules and its own steps. A modality module
    passes the steps that the tests replace (its `_extract` and `_repeat_view`) as functions that look them up at
    each call."""
    name: str  # the enrolment's and the attempt's modality: "face" or "voice"
    algorithm: str  # its model's code: "sface" or "ecapa-voxceleb"
    version_key: str  # the key of the engine's start answer that names the model's SHA-256, the algorithm's version
    per_enrolment: int  # the findings an enrolment keeps (H17)
    most_kept: int  # the findings that may pass the checks while three that match each other are sought
    embedding_length: int  # the values of one embedding
    noun: str  # "image" or "recording", as the refusals name a finding
    refusal: type[ModalityError]
    extract: Callable[[Any, bytes], Any]  # a stored or enrolled finding's checks, embedding and sealed form
    take: Callable[[Any, bytes, str], Any]  # the new finding of a verification or identification, from a device or a file
    rejected: Callable[[Any, str], dict]  # the answer to a new finding that fails its checks; no attempt is made
    sealed: Callable[[Any], bytes]  # what of a finding is stored, sealed: the image's PNG or the recording's WAV
    sample_fields: Callable[[Any], dict]  # a sample row's own columns
    sample_json: Callable[[Sample, Any], dict]  # a saved sample as the enrolment's answer shows it
    shown: Callable[[bytes, Any], bytes]  # what the result screen shows of the caller's own stored finding
    origin: Callable[[Any, str], dict]  # where the new finding came from, as the answer says it
    view: Callable[[Any, bytes], dict]  # the new finding and the stored one, as the result screen shows them
    repeat_view: Callable[..., bytes]  # the caller's own stored finding, described again (H49, H55)

    @property
    def search(self) -> Search:
        return Search(self.name, self.algorithm, self.per_enrolment, self.refusal)


def decode(data: str, limit: int, refusal: type[ModalityError], code: str) -> bytes:
    """An image or a recording sent in base64; what it holds is decided by the engine from its content."""
    try:
        decoded = base64.b64decode(data, validate=True)
    except ValueError:
        raise refusal(code) from None
    if not decoded or len(decoded) > limit:
        raise refusal(code)
    return decoded


def check(name: str, passed: bool, detail: str, **extra) -> dict:
    return {"name": name, "passed": passed, "detail": detail, **extra}


def base64_text(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def similarity(db: DbSession, a: list[float], b: list[float]) -> float:
    """pgvector's cosine similarity of two embeddings: one minus its cosine distance."""
    return float(db.scalar(text("SELECT 1 - (CAST(:a AS vector) <=> CAST(:b AS vector))"),
                           {"a": vector_text(a), "b": vector_text(b)}))


def card(databases: Databases, algorithm: str, service: EngineService | None) -> dict:
    """A method's card: its threshold, where the threshold comes from, and whether its engine is set up."""
    with _db(databases.biometric) as db:
        row = db.get(Algorithm, algorithm)
    return {"code": algorithm, "threshold": row.threshold, "threshold_provisional": row.threshold_provisional,
            "threshold_origin": row.threshold_origin, "available": service is not None}


def _algorithm(databases: Databases, code: str) -> Algorithm:
    with _db(databases.biometric) as db:
        return db.get(Algorithm, code)


def current_enrolment(databases: Databases, subject: uuid.UUID, modality: str) -> Enrolment | None:
    with _db(databases.biometric) as db:
        return db.scalar(select(Enrolment).where(Enrolment.subject_id == subject, Enrolment.modality == modality,
                                                 Enrolment.replaced_at.is_(None)))


# Enrolment (H15, H17, H48, H54): the findings taken so far, in the order they were taken, are saved when three of them
# match each other; otherwise the client is asked for another, until six have passed the checks. The server keeps
# nothing between requests, so every finding is checked again before the save.

def enrol(modality: Modality, service: EngineService, databases: Databases, keys: Keys, subject: uuid.UUID,
          findings: list[tuple[bytes, datetime]]) -> dict:
    if not modality.per_enrolment <= len(findings) <= modality.most_kept:
        raise modality.refusal("invalid_request")
    now = datetime.now(timezone.utc)
    times = [taken for _, taken in findings]
    if any(taken.tzinfo is None or not now - CAPTURE_AGE <= taken <= now + CLOCK_SKEW for taken in times) \
            or times != sorted(times):
        raise modality.refusal("invalid_request")
    algorithm = _algorithm(databases, modality.algorithm)
    version, threshold = algorithm.version, algorithm.threshold
    if service.engine.start().get(modality.version_key) != version:
        raise modality.refusal("method_version_differs", 503)
    found = []
    for index, (data, _) in enumerate(findings):
        extracted = modality.extract(service, data)
        if not extracted.passed:
            raise modality.refusal(f"{modality.noun}_rejected", index=index, checks=extracted.checks)
        found.append(extracted)
    scores: dict[tuple[int, int], float] = {}
    with _db(databases.biometric) as db:
        for a, b in itertools.combinations(range(len(found)), 2):
            scores[(a, b)] = similarity(db, found[b].embedding, found[a].embedding)
    pairs = [{"probe": b + 1, "reference": a + 1, "score": score, "accepted": score > threshold}
             for (a, b), score in scores.items()]
    trio = best_three(found, scores, threshold)
    if trio is None:
        status = "failed" if len(found) >= modality.most_kept else "another"
        return {"status": status, **({"error": f"{modality.noun}s_do_not_match"} if status == "failed" else {}),
                "pairs": pairs, "threshold": threshold, "kept": len(found)}
    chosen = [(index + 1, found[index], times[index]) for index in trio]
    enrolment, replaced, samples, templates = save(modality, databases, keys, subject, chosen, version)
    return {
        "status": "saved",
        "enrolment": {"id": str(enrolment.id), "created_at": enrolment.created_at.isoformat(),
                      "replaced_previous": replaced},
        "samples": [modality.sample_json(sample, extracted) for sample, (_, extracted, _) in zip(samples, chosen)],
        "templates": [{"id": str(template.id), "sample_id": str(template.sample_id), "algorithm": modality.algorithm,
                       "version": version, "embedding_length": modality.embedding_length} for template in templates],
        "pairs": [pair for pair in pairs if pair["reference"] - 1 in trio and pair["probe"] - 1 in trio],
        "threshold": threshold,
        "not_kept": [index + 1 for index in range(len(found)) if index not in trio],
    }


def save(modality: Modality, databases: Databases, keys: Keys, subject: uuid.UUID, chosen: list[tuple[int, Any, datetime]],
         version: str) -> tuple[Enrolment, bool, list[Sample], list[Template]]:
    """The chosen findings as a new enrolment that replaces the current one: each finding sealed, bound to its row and
    its subject (H25), and its embedding as a pgvector value (H14)."""
    now = datetime.now(timezone.utc)
    try:
        with _db(databases.biometric) as db, db.begin():
            result: CursorResult = db.execute(update(Enrolment).where(
                Enrolment.subject_id == subject, Enrolment.modality == modality.name, Enrolment.replaced_at.is_(None)
            ).values(replaced_at=now))
            enrolment = Enrolment(id=uuid.uuid4(), subject_id=subject, modality=modality.name, finger=None,
                                  created_at=now)
            db.add(enrolment)
            db.flush()
            samples, templates = [], []
            for placement, extracted, taken in chosen:
                sample = Sample(id=uuid.uuid4(), enrolment_id=enrolment.id, placement=placement, captured_at=taken,
                                **modality.sample_fields(extracted))
                sample.data = keyring.seal(keys, keyring.SAMPLE, sample.id.bytes + subject.bytes,
                                           modality.sealed(extracted))
                db.add(sample)
                db.flush()
                template = Template(id=uuid.uuid4(), sample_id=sample.id, algorithm=modality.algorithm, version=version,
                                    created_at=now, embedding=extracted.embedding)
                db.add(template)
                samples.append(sample)
                templates.append(template)
    except IntegrityError:
        raise modality.refusal("enrolment_busy", 409) from None  # another enrolment of this person ended first
    return enrolment, result.rowcount > 0, samples, templates


def delete_enrolments(databases: Databases, subject: uuid.UUID, modality: str) -> bool:
    """As H34 for a finger: the modality's enrolment and those it replaced are erased with their sealed findings and
    embeddings, and (H49, H55) with their verification attempts, whose link cascades; the identification attempts they
    led stay, with the link emptied (H41, H50, H56). False when the modality is not enrolled."""
    with _db(databases.biometric) as db, db.begin():
        rows = db.execute(select(Enrolment.id, Enrolment.replaced_at).where(
            Enrolment.subject_id == subject, Enrolment.modality == modality
        ).order_by(Enrolment.id).with_for_update()).all()
        if not any(replaced_at is None for _, replaced_at in rows):
            return False
        enrolments = [enrolment_id for enrolment_id, _ in rows]
        samples = select(Sample.id).where(Sample.enrolment_id.in_(enrolments))
        db.execute(delete(Template).where(Template.sample_id.in_(samples)))
        db.execute(delete(Sample).where(Sample.enrolment_id.in_(enrolments)))
        db.execute(delete(Enrolment).where(Enrolment.id.in_(enrolments)))
    return True


def repeat_view(modality: Modality, service: EngineService, keys: Keys, databases: Databases, subject: uuid.UUID,
                sample_id: uuid.UUID, stored: list[float]) -> bytes:
    """The caller's own winning finding, for the result screen (H49, H55): the sealed finding is opened for its owner
    only and described again, and the repeated embedding must equal the stored one."""
    with _db(databases.biometric) as db:
        sample = db.get(Sample, sample_id)
    data = keyring.open_sealed(keys, keyring.SAMPLE, sample.id.bytes + subject.bytes, sample.data)
    again = modality.extract(service, data)
    if not again.passed or again.embedding is None or vector_values(vector_text(again.embedding)) != stored:
        raise EngineError(f"the stored {modality.noun} did not give its stored embedding again")
    return modality.shown(data, again)


# Verification (H49, H55): one finding against the caller's current enrolment, as H35 does for a finger. The highest of
# the three cosine similarities decides, strictly above the threshold, and equal scores go to the earliest finding (H43).
# A refused finding makes no attempt; a completed comparison is saved, match or not, with its finding sealed, and the
# answer is sent only after that.

COMPARISONS = text("""
SELECT s.id AS sample_id, s.placement, t.version, t.embedding::text AS embedding,
       1 - (t.embedding <=> CAST(:probe AS vector)) AS score
FROM template t JOIN sample s ON s.id = t.sample_id
WHERE s.enrolment_id = :enrolment AND t.algorithm = :algorithm
ORDER BY s.placement
""")


def verify(modality: Modality, service: EngineService, databases: Databases, keys: Keys, subject: uuid.UUID,
           data: bytes, source: str = "device") -> dict:
    at = datetime.now(timezone.utc)
    started = time.perf_counter()
    algorithm = _algorithm(databases, modality.algorithm)
    version, threshold = algorithm.version, algorithm.threshold
    origin, provisional = algorithm.threshold_origin, algorithm.threshold_provisional
    enrolment = current_enrolment(databases, subject, modality.name)
    if enrolment is None:
        raise modality.refusal("not_enrolled", 409)  # H15: the client offers the enrolment
    if service.engine.start().get(modality.version_key) != version:
        raise modality.refusal("method_version_differs", 503)
    probe = modality.take(service, data, source)
    if not probe.passed:
        return modality.rejected(probe, source)
    with _db(databases.biometric) as db:
        rows = db.execute(COMPARISONS, {"probe": vector_text(probe.embedding), "enrolment": enrolment.id,
                                        "algorithm": modality.algorithm}).all()
    if len(rows) != modality.per_enrolment:
        raise modality.refusal("enrolment_changed", 409)
    if any(row.version != version for row in rows):
        raise modality.refusal("method_version_differs", 503)
    comparisons = [{"placement": row.placement, "score": float(row.score), "accepted": float(row.score) > threshold}
                   for row in rows]
    best = sorted(rows, key=lambda row: (-float(row.score), row.placement))[0]
    score = float(best.score)
    duration_ms = round((time.perf_counter() - started) * 1000)  # receipt through the comparisons (H35)
    reference = modality.repeat_view(service, keys, databases, subject, best.sample_id, vector_values(best.embedding))
    attempt = Attempt(id=uuid.uuid4(), at=at, subject_id=subject, modality=modality.name, mode="verify",
                      algorithm=modality.algorithm, enrolment_id=enrolment.id, score=score, threshold=threshold,
                      accepted=score > threshold, duration_ms=duration_ms, source=source)
    attempt.probe = keyring.seal(keys, keyring.PROBE, attempt.id.bytes + subject.bytes, modality.sealed(probe))
    with _db(databases.biometric) as db, db.begin():
        # A deletion or a new enrolment since the comparison invalidates it (H35); a later deletion cascades.
        locked = db.scalar(select(Enrolment).where(Enrolment.id == enrolment.id, Enrolment.subject_id == subject)
                           .with_for_update())
        if locked is None or locked.replaced_at is not None:
            raise modality.refusal("enrolment_changed", 409)
        db.add(attempt)
    return {"status": "verified", "attempt_id": str(attempt.id), "at": at.isoformat(), "score": score,
            "threshold": threshold, "threshold_origin": origin, "threshold_provisional": provisional,
            "accepted": attempt.accepted, "duration_ms": duration_ms, "comparisons": comparisons,
            **modality.origin(probe, source), "view": {"placement": best.placement, **modality.view(probe, reference)}}


# Identification (H50, H56): one finding against every current enrolment of the modality of the active user accounts,
# as H41 does for fingerprints, with the gallery, the ranking and the locked save below. The leader is found only
# strictly above the threshold. A refused finding makes no attempt; a completed search is saved, found or not, with its
# finding sealed, and the answer is sent only after that. Only the caller's own enrolment is named or shown (H18).

def identify(modality: Modality, service: EngineService, databases: Databases, keys: Keys, subject: uuid.UUID,
             data: bytes, source: str = "device") -> dict:
    at = datetime.now(timezone.utc)
    started = time.perf_counter()
    algorithm = _algorithm(databases, modality.algorithm)
    version, threshold = algorithm.version, algorithm.threshold
    origin, provisional = algorithm.threshold_origin, algorithm.threshold_provisional
    search = modality.search
    gallery = search.gallery(databases, keys, subject, version)
    if service.engine.start().get(modality.version_key) != version:
        raise modality.refusal("method_version_differs", 503)
    probe = modality.take(service, data, source)
    if not probe.passed:
        return modality.rejected(probe, source)
    ranked = search.rank(databases, gallery, probe.embedding)
    duration_ms = round((time.perf_counter() - started) * 1000)  # receipt through every comparison (H41)
    own = ranked.own(subject)
    view = None
    if own is not None:  # the caller's own enrolled finding only, described again as verification does
        rank, row = own
        reference = modality.repeat_view(service, keys, databases, subject, row.sample_id, vector_values(row.embedding))
        view = {"rank": rank, "placement": row.placement, **modality.view(probe, reference)}
    attempt = Attempt(id=uuid.uuid4(), at=at, subject_id=subject, modality=modality.name, mode="identify",
                      algorithm=modality.algorithm, top_enrolment_id=ranked.leader.enrolment_id,
                      gallery_size=len(gallery.rows), score=ranked.score, threshold=threshold,
                      accepted=ranked.score > threshold, duration_ms=duration_ms, source=source)
    attempt.probe = keyring.seal(keys, keyring.PROBE, attempt.id.bytes + subject.bytes, modality.sealed(probe))
    search.save(databases, gallery, attempt)
    return {"status": "identified", "attempt_id": str(attempt.id), "at": at.isoformat(), "score": ranked.score,
            "threshold": threshold, "threshold_origin": origin, "threshold_provisional": provisional,
            "accepted": attempt.accepted, "duration_ms": duration_ms, "gallery_size": len(gallery.rows),
            "enrolments": len(ranked.rows), "tied_leaders": ranked.tied_leaders(), **modality.origin(probe, source),
            "candidates": ranked.candidates(subject, threshold),
            **({"view": view} if view is not None else {})}


RANKING = text("""
WITH scored AS (
    SELECT s.enrolment_id, s.id AS sample_id, s.placement, t.embedding::text AS embedding,
           1 - (t.embedding <=> CAST(:probe AS vector)) AS score
    FROM template t JOIN sample s ON s.id = t.sample_id
    WHERE t.id IN :templates AND t.algorithm = :algorithm
), ranked AS (
    SELECT scored.*, row_number() OVER (PARTITION BY enrolment_id ORDER BY score DESC, placement) AS place
    FROM scored
)
SELECT enrolment_id, sample_id, placement, embedding, score FROM ranked WHERE place = 1
ORDER BY score DESC, enrolment_id
""").bindparams(bindparam("templates", expanding=True))


@dataclass(frozen=True)
class Gallery:
    owners: list[Owner]  # the participating accounts, fixed as H41 fixes them
    enrolments: list[tuple[uuid.UUID, uuid.UUID]]  # (enrolment, subject), in enrolment order
    rows: list[tuple]  # (enrolment, sample, placement, template, version), in enrolment and placement order


@dataclass(frozen=True)
class Ranked:
    """Every enrolment of the gallery once, with its winning sample, placement, embedding and score, by score and
    then by enrolment."""
    rows: list[Row]
    owner_of: dict[uuid.UUID, uuid.UUID]  # enrolment -> subject

    @property
    def leader(self) -> Row:
        return self.rows[0]

    @property
    def score(self) -> float:
        return float(self.rows[0].score)

    def tied_leaders(self) -> int:
        return [float(row.score) for row in self.rows].count(self.score)

    def shown(self) -> list[tuple[int, Row]]:
        return list(enumerate(self.rows[:SHOWN_CANDIDATES], 1))

    def own(self, subject: uuid.UUID) -> tuple[int, Row] | None:
        """The caller's own enrolment and its rank, when it is among the candidates shown."""
        return next(((rank, row) for rank, row in self.shown() if self.owner_of[row.enrolment_id] == subject), None)

    def candidates(self, subject: uuid.UUID, threshold: float) -> list[dict]:
        """The candidates shown: a rank for this attempt, whether it is the caller's own, its score and decision."""
        return [{"rank": rank, "own": self.owner_of[row.enrolment_id] == subject, "score": float(row.score),
                 "accepted": float(row.score) > threshold} for rank, row in self.shown()]


@dataclass(frozen=True)
class Search:
    modality: str  # "face" or "voice"
    algorithm: str  # its model's code: "sface" or "ecapa-voxceleb"
    per_enrolment: int  # the images or recordings of an enrolment, so its embeddings (H17)
    refusal: Callable[..., Exception]  # the modality's error, made from a code and an HTTP status

    def _rows(self, db: DbSession, enrolments: list[uuid.UUID]) -> list[tuple]:
        return [tuple(row) for row in db.execute(
            select(Enrolment.id, Sample.id, Sample.placement, Template.id, Template.version)
            .join(Sample, Sample.enrolment_id == Enrolment.id)
            .outerjoin(Template, (Template.sample_id == Sample.id) & (Template.algorithm == self.algorithm))
            .where(Enrolment.id.in_(enrolments)).order_by(Enrolment.id, Sample.placement))]

    def gallery(self, databases: Databases, keys: Keys, subject: uuid.UUID, version: str) -> Gallery:
        """The current enrolments of the active user accounts, each with its embeddings of this version; without the
        caller's own enrolment, the message of H15."""
        owners = active_owners(databases, keys)
        with _db(databases.biometric) as db:
            enrolments = [tuple(row) for row in db.execute(select(Enrolment.id, Enrolment.subject_id).where(
                Enrolment.modality == self.modality, Enrolment.replaced_at.is_(None),
                Enrolment.subject_id.in_([owner.subject_id for owner in owners])).order_by(Enrolment.id))]
            if not any(owner == subject for _, owner in enrolments):
                raise self.refusal("not_enrolled", 409)  # H15: the client offers the enrolment
            rows = self._rows(db, [enrolment for enrolment, _ in enrolments])
        counts = Counter(row[0] for row in rows)
        if any(counts[enrolment] != self.per_enrolment for enrolment, _ in enrolments) or any(row[3] is None for row in rows):
            raise self.refusal("gallery_templates_unavailable", 503)
        if any(row[4] != version for row in rows):
            raise self.refusal("method_version_differs", 503)
        participating = {owner for _, owner in enrolments}
        return Gallery([owner for owner in owners if owner.subject_id in participating], enrolments, rows)

    def rank(self, databases: Databases, gallery: Gallery, embedding: list[float]) -> Ranked:
        """The new embedding against every embedding of the gallery, in the one statement of RANKING."""
        with _db(databases.biometric) as db:
            rows = list(db.execute(RANKING, {"probe": vector_text(embedding), "algorithm": self.algorithm,
                                             "templates": [row[3] for row in gallery.rows]}).all())
        owner_of = dict(gallery.enrolments)
        if len(rows) != len(owner_of) or {row.enrolment_id for row in rows} != set(owner_of):
            raise self.refusal("gallery_changed", 409)  # an enrolment's embeddings were erased since the start
        return Ranked(rows, owner_of)

    def save(self, databases: Databases, gallery: Gallery, attempt: Attempt) -> None:
        """As H41: the accounts are locked first, then the enrolments; the attempt is saved only while the gallery is
        what it was at the start. A later deletion of the leading enrolment keeps the attempt and empties its link."""
        ids = [enrolment for enrolment, _ in gallery.enrolments]
        with DbSession(databases.accounts) as accounts_db, accounts_db.begin():
            if not owners_unchanged(accounts_db, gallery.owners):
                raise self.refusal("gallery_changed", 409)
            with _db(databases.biometric) as db, db.begin():
                current = db.execute(select(Enrolment.id, Enrolment.subject_id, Enrolment.replaced_at).where(
                    Enrolment.id.in_(ids)).order_by(Enrolment.id).with_for_update()).all()
                if [tuple(row) for row in current] != [(enrolment, owner, None) for enrolment, owner in gallery.enrolments] \
                        or self._rows(db, ids) != gallery.rows:
                    raise self.refusal("gallery_changed", 409)
                db.add(attempt)
