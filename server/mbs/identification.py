"""Fingerprint 1:N with the selected research method (H13, H15, H18, H25, H41, H42, H45).

A gallery snapshots current enrolments of active user accounts. Only metadata spans the full gallery.
At most four encrypted references are opened and compared at once, each in its own engine process.
The probe is extracted once. The final transaction rechecks gallery membership and account status.
Results expose only per-attempt ranks, scores and the caller's own finger positions. H45 adds the
match illustration of the caller's own highest-ranked print among the shown candidates, never another
user's: its winning comparison is repeated once with `view`, and the repeated score must equal it.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import datetime, timezone

import anyio
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from . import fingerprint as fp
from . import keys as keyring
from .db import Databases
from .engines import MAX_DATA, Engine, EngineError, ScannerError, ScannerRun
from .keys import Keys
from .models import ACTIVE, USER, Account, Algorithm, Attempt, Enrolment, IdentityLink, Sample, Template

logger = logging.getLogger("mbs.identification")
SHOWN_CANDIDATES = 5


class IdentificationError(Exception):
    """An expected refusal, expressed as a client error code."""


@dataclass(frozen=True)
class Owner:
    account_id: uuid.UUID
    subject_id: uuid.UUID
    sealed_link: bytes


@dataclass(frozen=True)
class Candidate:
    id: uuid.UUID
    subject_id: uuid.UUID
    finger: int


@dataclass(frozen=True)
class Reference:
    enrolment_id: uuid.UUID
    sample_id: uuid.UUID
    placement: int
    template_id: uuid.UUID | None
    version: str | None
    size: int | None


@dataclass
class Gallery:
    owners: list[Owner]
    candidates: list[Candidate]
    references: list[Reference]
    threshold: float
    origin: str
    provisional: bool
    version: str
    algorithm: str = fp.OPENCV_SIFT


def _reference_rows(db: Session, enrolments: list[uuid.UUID], algorithm: str = fp.OPENCV_SIFT) -> list[Reference]:
    rows = db.execute(select(Sample.enrolment_id, Sample.id, Sample.placement, Template.id,
                             Template.version, func.octet_length(Template.data)).outerjoin(
        Template, (Template.sample_id == Sample.id) & (Template.algorithm == algorithm)).where(
        Sample.enrolment_id.in_(enrolments)).order_by(Sample.enrolment_id, Sample.placement)).all()
    return [Reference(*row) for row in rows]


def _validate_reference(reference: Reference, version: str) -> None:
    if reference.version != version:
        raise IdentificationError("template_version_mismatch")
    if reference.size is None or reference.size <= keyring.HEADER_BYTES + 16 or reference.size > MAX_DATA:
        raise IdentificationError("stored_template_unreadable")


def active_owners(databases: Databases, keys: Keys) -> list[Owner]:
    """The active user accounts and their subjects, through their sealed identity links (H3, H41); face
    identification (H50) fixes its gallery from the same list."""
    with Session(databases.accounts) as db:
        rows = db.execute(select(Account.id, IdentityLink.subject).join(IdentityLink).where(
            Account.role == USER, Account.status == ACTIVE).order_by(Account.id)).all()
    return [Owner(account_id, uuid.UUID(bytes=keyring.open_sealed(
        keys, keyring.IDENTITY_LINK, account_id.bytes, sealed)), sealed) for account_id, sealed in rows]


def owners_unchanged(db: Session, owners: list[Owner]) -> bool:
    """Lock the gallery's accounts, before any enrolment is locked, and tell whether each is still the same
    active user account (H41, H50)."""
    rows = db.execute(select(Account.id, Account.status, Account.role, IdentityLink.subject).join(
        IdentityLink).where(Account.id.in_([owner.account_id for owner in owners])).order_by(
        Account.id).with_for_update()).all()
    return list(rows) == [(owner.account_id, ACTIVE, USER, owner.sealed_link) for owner in owners]


def _load_gallery(databases: Databases, keys: Keys, subject: uuid.UUID, code: str = fp.OPENCV_SIFT) -> Gallery:
    owners = active_owners(databases, keys)
    with Session(databases.biometric) as db:
        candidates = [Candidate(*row) for row in db.execute(select(Enrolment.id, Enrolment.subject_id,
            Enrolment.finger).where(Enrolment.modality == fp.FINGERPRINT, Enrolment.replaced_at.is_(None),
            Enrolment.subject_id.in_([owner.subject_id for owner in owners])).order_by(Enrolment.id))]
        if not any(candidate.subject_id == subject for candidate in candidates):
            raise IdentificationError("not_enrolled")
        algorithm = db.get(Algorithm, code)
        references = _reference_rows(db, [candidate.id for candidate in candidates], code)
        counts = dict.fromkeys((candidate.id for candidate in candidates), 0)
        for reference in references:
            counts[reference.enrolment_id] += 1
            if reference.template_id is None:
                if code == fp.OPENCV_SIFT:
                    raise IdentificationError("gallery_templates_unavailable")
            else:
                _validate_reference(reference, algorithm.version)
        if any(count != fp.PLACEMENTS for count in counts.values()):
            raise IdentificationError("gallery_templates_unavailable")
        participating = {candidate.subject_id for candidate in candidates}
        return Gallery([owner for owner in owners if owner.subject_id in participating], candidates, references,
                       algorithm.threshold, algorithm.threshold_origin, algorithm.threshold_provisional, algorithm.version, code)


def _open_reference(databases: Databases, keys: Keys, candidate: Candidate, reference: Reference,
                    algorithm: str = fp.OPENCV_SIFT) -> bytes:
    with Session(databases.biometric) as db:
        row = db.execute(select(Template.data, Template.version).join(Sample).join(Enrolment).where(
            Template.id == reference.template_id, Template.sample_id == reference.sample_id,
            Template.algorithm == algorithm, Sample.enrolment_id == candidate.id,
            Enrolment.subject_id == candidate.subject_id, Enrolment.replaced_at.is_(None))).first()
        if row is None:
            raise IdentificationError("gallery_changed")
        if row.version != reference.version or len(row.data) != reference.size:
            raise IdentificationError("gallery_changed")
    return keyring.open_sealed(keys, keyring.TEMPLATE,
        reference.template_id.bytes + candidate.subject_id.bytes + algorithm.encode("ascii"), row.data)


def _preparation_source(databases: Databases, keys: Keys, candidate: Candidate, reference: Reference,
                         gallery: Gallery) -> tuple[bytes, bytes | None]:
    """H42: open one sealed capture, reusing its pinned pore coordinates when available."""
    with Session(databases.biometric) as db:
        sample = db.scalar(select(Sample).join(Enrolment).where(
            Sample.id == reference.sample_id, Sample.enrolment_id == candidate.id,
            Sample.placement == reference.placement, Enrolment.subject_id == candidate.subject_id,
            Enrolment.replaced_at.is_(None)))
        if sample is None:
            raise IdentificationError("gallery_changed")
        png = keyring.open_sealed(keys, keyring.SAMPLE, sample.id.bytes + candidate.subject_id.bytes, sample.data)
        pores = None
        if gallery.algorithm == fp.LEARNED_PORE:
            stored = db.scalar(select(Template).where(Template.sample_id == sample.id, Template.algorithm == fp.PORE_SIFT))
            if stored is not None:
                if stored.version != gallery.version:
                    raise IdentificationError("template_version_mismatch")
                if stored.data is None:
                    raise keyring.KeysError("missing pore template")
                pores = keyring.open_sealed(keys, keyring.TEMPLATE,
                    stored.id.bytes + candidate.subject_id.bytes + fp.PORE_SIFT.encode("ascii"), stored.data)
        return png, pores


def _store_prepared(databases: Databases, keys: Keys, candidate: Candidate, gallery: Gallery,
                    references: list[Reference], generated: dict[uuid.UUID, bytes]) -> list[Reference]:
    """H42: commit missing templates per enrolment, reusing a concurrent complete preparation."""
    with Session(databases.biometric) as db, db.begin():
        enrolment = db.scalar(select(Enrolment).where(
            Enrolment.id == candidate.id, Enrolment.subject_id == candidate.subject_id).with_for_update())
        if enrolment is None or enrolment.replaced_at is not None:
            raise IdentificationError("gallery_changed")
        current = _reference_rows(db, [candidate.id], gallery.algorithm)
        if [(r.sample_id, r.placement) for r in current] != [(r.sample_id, r.placement) for r in references]:
            raise IdentificationError("gallery_changed")
        for expected, actual in zip(references, current):
            if expected.template_id is not None:
                if actual != expected:
                    raise IdentificationError("gallery_changed")
            elif actual.template_id is None:
                stored = Template(id=uuid.uuid4(), sample_id=actual.sample_id, algorithm=gallery.algorithm,
                                  version=gallery.version, created_at=datetime.now(timezone.utc))
                stored.data = keyring.seal(keys, keyring.TEMPLATE,
                    stored.id.bytes + candidate.subject_id.bytes + gallery.algorithm.encode("ascii"), generated[actual.sample_id])
                db.add(stored)
            else:
                _validate_reference(actual, gallery.version)
        db.flush()
        return _reference_rows(db, [candidate.id], gallery.algorithm)


async def _engine_call(engine: Engine, work: Callable):
    """Cancel computation promptly and join its thread before releasing the shared scanner lock."""
    stopped, started, finished = threading.Event(), threading.Event(), threading.Event()

    def execute():
        if stopped.is_set():
            return None
        started.set()
        try:
            if not stopped.is_set():
                return work()
        finally:
            finished.set()

    try:
        return await anyio.to_thread.run_sync(execute, abandon_on_cancel=True)
    finally:
        stopped.set()
        if started.is_set() and not finished.is_set():
            with anyio.CancelScope(shield=True):
                while not finished.is_set():
                    engine.interrupt()
                    await anyio.sleep(0.02)


async def _compare_batch(engines: list[Engine], databases: Databases, keys: Keys,
                         candidates: dict[uuid.UUID, Candidate], references: list[Reference], probe: bytes,
                         algorithm: str = fp.OPENCV_SIFT) -> list[int]:
    results: list[int | Exception | None] = [None] * len(references)

    async def compare(index: int, engine: Engine, reference: Reference):
        try:
            native = await run_in_threadpool(_open_reference, databases, keys, candidates[reference.enrolment_id], reference, algorithm)
            if len(probe) + len(native) > MAX_DATA:
                raise EngineError("comparison exceeds the engine message limit")
            result, _ = await _engine_call(engine, lambda: engine.request({"op": "compare"}, [probe, native]))
            results[index] = fp.comparison_score(result)
        except Exception as error:
            results[index] = error

    async with anyio.create_task_group() as group:
        for index, (engine, reference) in enumerate(zip(engines, references)):
            group.start_soon(compare, index, engine, reference)
    for result in results:
        if isinstance(result, Exception):
            raise result
    return results


def _save(databases: Databases, keys: Keys, subject: uuid.UUID, gallery: Gallery,
          best: Candidate, score: int, png: bytes, at: datetime, duration_ms: int) -> Attempt:
    attempt = Attempt(id=uuid.uuid4(), at=at, subject_id=subject, modality=fp.FINGERPRINT, mode="identify",
                      algorithm=gallery.algorithm, top_enrolment_id=best.id, gallery_size=len(gallery.references),
                      score=score, threshold=gallery.threshold, accepted=score > gallery.threshold,
                      duration_ms=duration_ms, source="device")
    attempt.probe = keyring.seal(keys, keyring.PROBE, attempt.id.bytes + subject.bytes, png)
    # Lock accounts first, then enrolments. Capture and comparison hold neither transaction open.
    with Session(databases.accounts) as accounts_db, accounts_db.begin():
        if not owners_unchanged(accounts_db, gallery.owners):
            raise IdentificationError("gallery_changed")
        with Session(databases.biometric, expire_on_commit=False) as db, db.begin():
            ids = [candidate.id for candidate in gallery.candidates]
            current = db.execute(select(Enrolment.id, Enrolment.subject_id, Enrolment.finger, Enrolment.replaced_at).where(
                Enrolment.id.in_(ids)).order_by(Enrolment.id).with_for_update()).all()
            if list(current) != [(candidate.id, candidate.subject_id, candidate.finger, None) for candidate in gallery.candidates]:
                raise IdentificationError("gallery_changed")
            if _reference_rows(db, ids, gallery.algorithm) != gallery.references:
                raise IdentificationError("gallery_changed")
            db.add(attempt)
    return attempt


async def identify(service: fp.FingerprintService, databases: Databases, keys: Keys,
                   subject: uuid.UUID, algorithm: str = fp.OPENCV_SIFT) -> AsyncIterator[dict]:
    if not service._busy.acquire(blocking=False):
        yield {"type": "failed", "error": "scanner_busy"}
        return
    run = ScannerRun()
    try:
        async for event in _identify(service, databases, keys, subject, run, algorithm):
            yield event
    except IdentificationError as error:
        yield {"type": "failed", "error": str(error)}
    except ScannerError as error:
        yield {"type": "failed", "error": error.code}
    except EngineError:
        yield {"type": "failed", "error": "engine_unavailable"}
    except keyring.KeysError:
        yield {"type": "failed", "error": "stored_template_unreadable"}
    except Exception as error:
        logger.error("fingerprint identification failed (%s)", type(error).__name__)
        yield {"type": "failed", "error": "unexpected"}
    finally:
        run.cancel()
        service._busy.release()


async def _extract(service: fp.FingerprintService, algorithm: str, png: bytes, pores: bytes | None = None) -> bytes:
    engine = fp.engine_for(service, algorithm)
    if algorithm == fp.LEARNED_PORE and pores is None:
        _, detected = await _engine_call(service.pore, lambda: service.pore.request({"op": "detect"}, [png]))
        if not detected or not detected[0]:
            raise EngineError("missing pore coordinates")
        pores = detected[0]
    return await _engine_call(engine, lambda: fp.extract_native(service, algorithm, png, pores))


async def _detect(service: fp.FingerprintService, png: bytes) -> bytes:
    return await _engine_call(service.pore, lambda: fp.detect_pores(service, png))


async def _match_view(service, engine: Engine, databases, keys, gallery: Gallery, candidate: Candidate,
                      reference: Reference, rank: int, score: int, probe: bytes, probe_pores: bytes | None,
                      described_from: dict[uuid.UUID, bytes]) -> dict:
    """H18, H45: the caller's own print only. Its winning comparison is repeated once with `view` and, for
    Pore CNN, the pores both templates were described from (H44)."""
    png, stored_pores = await run_in_threadpool(_preparation_source, databases, keys, candidate, reference, gallery)
    native = await run_in_threadpool(_open_reference, databases, keys, candidate, reference, gallery.algorithm)
    parts = [probe, native]
    if gallery.algorithm == fp.LEARNED_PORE:
        reference_pores = described_from.get(reference.sample_id) or stored_pores
        if reference_pores is None:
            reference_pores = await _detect(service, png)
        parts += [probe_pores, reference_pores]
    result, data = await _engine_call(engine, lambda: engine.request({"op": "compare", "view": True}, parts))
    if fp.comparison_score(result) != score:
        raise EngineError("the repeated comparison changed its score")
    pairs = fp.match_pairs(result, data, score)
    return {"rank": rank, "finger": candidate.finger, "placement": reference.placement,
            "reference_image": fp._b64(png), "count": score, "pairs": fp._b64(pairs)}


async def _prepare_gallery(service, databases, keys, gallery: Gallery, subject: uuid.UUID | None = None,
                           described_from: dict[uuid.UUID, bytes] | None = None) -> AsyncIterator[dict]:
    missing = sum(reference.template_id is None for reference in gallery.references)
    if not missing:
        return
    yield {"type": "preparing_templates", "algorithm": gallery.algorithm, "completed": 0, "total": missing}
    by_enrolment = {candidate.id: [] for candidate in gallery.candidates}
    for reference in gallery.references:
        by_enrolment[reference.enrolment_id].append(reference)
    completed = 0
    for candidate in gallery.candidates:
        references = by_enrolment[candidate.id]
        generated = {}
        for reference in references:
            if reference.template_id is None:
                png, pores = await run_in_threadpool(_preparation_source, databases, keys, candidate, reference, gallery)
                if gallery.algorithm == fp.LEARNED_PORE and pores is None:
                    pores = await _detect(service, png)
                    if described_from is not None and candidate.subject_id == subject:
                        # H45: only the caller's own detected points, for a possible illustration.
                        described_from[reference.sample_id] = pores
                generated[reference.sample_id] = await _extract(service, gallery.algorithm, png, pores)
                completed += 1
                yield {"type": "preparing_templates", "algorithm": gallery.algorithm, "completed": completed, "total": missing}
        if generated:
            by_enrolment[candidate.id] = await run_in_threadpool(
                _store_prepared, databases, keys, candidate, gallery, references, generated)
    gallery.references = [reference for candidate in gallery.candidates for reference in by_enrolment[candidate.id]]


async def _identify(service, databases, keys, subject, run, algorithm) -> AsyncIterator[dict]:
    if algorithm not in (fp.OPENCV_SIFT, fp.PORE_SIFT, fp.LEARNED_PORE):
        raise IdentificationError("unknown_method")
    if fp.engine_for(service, algorithm) is None:
        raise IdentificationError("method_unavailable")
    gallery = await run_in_threadpool(_load_gallery, databases, keys, subject, algorithm)
    total = len(gallery.references)
    yield {"type": "started", "algorithm": algorithm, "threshold": gallery.threshold,
           "quality_minimum": service.quality_minimum, "gallery_size": total, "enrolments": len(gallery.candidates)}
    engines = service.search_engines(algorithm)[:total]
    startup = [*engines, service.pore] if algorithm == fp.LEARNED_PORE else engines
    for engine in startup:
        ready = await _engine_call(engine, engine.start)
        if ready["version"] != gallery.version:
            raise IdentificationError("template_version_mismatch")
    await _engine_call(service.quality, service.quality.start)
    described_from: dict[uuid.UUID, bytes] = {}
    async for event in _prepare_gallery(service, databases, keys, gallery, subject, described_from):
        yield event
    for capture in range(1, fp.MOST_CAPTURES + 1):
        yield {"type": "place", "capture": capture, "maximum": fp.MOST_CAPTURES}
        header, png = await fp.acquire(service, "finger", run)
        at, started = datetime.now(timezone.utc), time.perf_counter()
        yield {"type": "checking"}
        score, checks = await _engine_call(service.quality, lambda: fp.capture_quality(service, header, png))
        image = fp._b64(png)
        if checks[-1]["passed"]:
            break
        yield {"type": "rejected", "image": image, "checks": checks, "score": score, "minimum": service.quality_minimum}
        if capture == fp.MOST_CAPTURES:
            raise IdentificationError("too_many_captures")
        yield {"type": "lift"}
        await fp.acquire(service, "lift", run)

    yield {"type": "captured", "image": image, "checks": checks}
    yield {"type": "extracting"}
    probe_pores = await _detect(service, png) if algorithm == fp.LEARNED_PORE else None
    probe = await _extract(service, algorithm, png, probe_pores)
    candidates = {candidate.id: candidate for candidate in gallery.candidates}
    scores = dict.fromkeys(candidates, 0)
    winners: dict[uuid.UUID, Reference] = {}  # H45: each enrolment's earliest highest-scoring placement
    yield {"type": "searching", "completed": 0, "total": total}
    for offset in range(0, total, len(engines)):
        batch = gallery.references[offset:offset + len(engines)]
        results = await _compare_batch(engines, databases, keys, candidates, batch, probe, algorithm)
        for reference, value in zip(batch, results):
            if reference.enrolment_id not in winners or value > scores[reference.enrolment_id]:
                winners[reference.enrolment_id] = reference
            scores[reference.enrolment_id] = max(scores[reference.enrolment_id], value)
        yield {"type": "searching", "completed": offset + len(batch), "total": total}
    # UUID orders equal scores deterministically. The response reports ties explicitly.
    ranked = sorted(gallery.candidates, key=lambda candidate: (-scores[candidate.id], candidate.id))
    best, score = ranked[0], scores[ranked[0].id]
    duration_ms = round((time.perf_counter() - started) * 1000)
    shown = ranked[:SHOWN_CANDIDATES]
    own = next(((rank, candidate) for rank, candidate in enumerate(shown, 1) if candidate.subject_id == subject), None)
    match_view = None
    if own is not None:
        rank, candidate = own
        match_view = await _match_view(service, engines[0], databases, keys, gallery, candidate, winners[candidate.id],
                                       rank, scores[candidate.id], probe, probe_pores, described_from)
    yield {"type": "saving"}
    attempt = await run_in_threadpool(_save, databases, keys, subject, gallery, best, score, png, at, duration_ms)
    yield {"type": "identified", "attempt_id": str(attempt.id), "at": attempt.at.isoformat(),
           "algorithm": algorithm, "score": score, "threshold": attempt.threshold,
           "threshold_origin": gallery.origin, "threshold_provisional": gallery.provisional,
           "accepted": attempt.accepted, "duration_ms": duration_ms, "gallery_size": total,
           "enrolments": len(ranked), "tied_leaders": sum(scores[c.id] == score for c in ranked),
           "candidates": [{"rank": rank, "own": candidate.subject_id == subject,
                           "finger": candidate.finger if candidate.subject_id == subject else None,
                           "score": scores[candidate.id], "accepted": scores[candidate.id] > attempt.threshold}
                          for rank, candidate in enumerate(shown, 1)],
           **({"match_view": match_view} if match_view is not None else {})}
