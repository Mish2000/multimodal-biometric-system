"""1:N over face and voice embeddings (H50, H56): the gallery, its ranking and the locked save, one implementation for
both modalities, parameterized by the modality, its algorithm and its refusal.

The gallery is the current enrolments of the modality of the active user accounts, found through their sealed identity
links (H41), each with its three embeddings of the pinned model version; it is fixed, with the threshold, when the new
finding arrives. One SQL statement ranks the enrolments by their highest cosine similarity, an exact pgvector search
without an index (docs/data-model.md): a window function keeps each enrolment's highest score and its earliest
placement, and the enrolments are ordered by score, then by enrolment, so equal leaders always come in the same order
and are reported as a tie. Before the save, the accounts are locked first, then the enrolments, and both are compared
with the gallery again: a deletion, a new enrolment, a disabled account or a changed template since the start ends the
search unsaved (H41). Only the caller's own enrolment is named; the others have a rank for this attempt alone (H18).
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import Row, bindparam, select, text
from sqlalchemy.orm import Session as DbSession

from .db import Databases
from .identification import SHOWN_CANDIDATES, Owner, active_owners, owners_unchanged
from .keys import Keys
from .models import Attempt, Enrolment, Sample, Template, vector_text


def _db(engine) -> DbSession:
    return DbSession(engine, expire_on_commit=False)

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
