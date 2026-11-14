"""Fingerprint 1:1 verification (H15, H25, H35). Compare one quality-checked capture with the three
stored templates of the signed-in user's selected finger. The highest score decides, strictly above the
threshold. A result is sent only after its attempt and sealed probe have committed."""

from __future__ import annotations

import base64
import logging
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from . import fingerprint as fp
from . import keys as keyring
from .db import Databases
from .engines import EngineError, ScannerError, ScannerRun
from .keys import Keys
from .models import Algorithm, Attempt, Enrolment, Sample, Template

logger = logging.getLogger("mbs.verification")


class VerificationError(Exception):
    """An expected refusal, expressed as a client error code."""


@dataclass
class Reference:
    enrolment_id: uuid.UUID
    threshold: float
    origin: str
    version: str
    templates: list[tuple[int, bytes]]  # original placement numbers, native templates
    algorithm: str = fp.OPENCV_SIFT
    provisional: bool = False
    pending: list[tuple[uuid.UUID, int, bytes]] = field(default_factory=list)
    pore_sources: dict[uuid.UUID, bytes] = field(default_factory=dict)


def _load(databases: Databases, keys: Keys, subject: uuid.UUID, finger: int,
          code: str = fp.OPENCV_SIFT) -> Reference:
    with Session(databases.biometric) as db:
        enrolment = db.scalar(select(Enrolment).where(
            Enrolment.subject_id == subject, Enrolment.modality == fp.FINGERPRINT,
            Enrolment.finger == finger, Enrolment.replaced_at.is_(None)))
        if enrolment is None:
            raise VerificationError("not_enrolled")
        algorithm = db.get(Algorithm, code)
        rows = db.execute(select(Sample, Template).outerjoin(Template,
            (Template.sample_id == Sample.id) & (Template.algorithm == code)).where(
            Sample.enrolment_id == enrolment.id).order_by(Sample.placement)).all()
        if len(rows) != fp.PLACEMENTS:
            raise VerificationError("templates_unavailable")
        if any(template is not None and template.version != algorithm.version for _, template in rows):
            raise VerificationError("template_version_mismatch")
        reference = Reference(enrolment.id, algorithm.threshold, algorithm.threshold_origin, algorithm.version, [],
                              algorithm=code, provisional=algorithm.threshold_provisional)
        for sample, template in rows:
            if template is None:
                if code not in (fp.PORE_SIFT, fp.LEARNED_PORE):
                    raise VerificationError("templates_unavailable")
                png = keyring.open_sealed(keys, keyring.SAMPLE, sample.id.bytes + subject.bytes, sample.data)
                reference.pending.append((sample.id, sample.placement, png))
                if code == fp.LEARNED_PORE:
                    pores = db.scalar(select(Template).where(Template.sample_id == sample.id,
                                                             Template.algorithm == fp.PORE_SIFT))
                    if pores is not None:
                        if pores.version != algorithm.version:
                            raise VerificationError("template_version_mismatch")
                        reference.pore_sources[sample.id] = keyring.open_sealed(keys, keyring.TEMPLATE,
                            pores.id.bytes + subject.bytes + fp.PORE_SIFT.encode("ascii"), pores.data)
            else:
                native = keyring.open_sealed(keys, keyring.TEMPLATE,
                    template.id.bytes + subject.bytes + code.encode("ascii"), template.data)
                reference.templates.append((sample.placement, native))
        return reference


def _store_templates(databases: Databases, keys: Keys, subject: uuid.UUID, reference: Reference,
                     generated: list[tuple[uuid.UUID, int, bytes]]) -> list[tuple[int, bytes]]:
    """H38: fill missing templates atomically. A concurrent preparation reuses the already stored row."""
    templates = list(reference.templates)
    with Session(databases.biometric) as db, db.begin():
        enrolment = db.scalar(select(Enrolment).where(
            Enrolment.id == reference.enrolment_id, Enrolment.subject_id == subject).with_for_update())
        if enrolment is None or enrolment.replaced_at is not None:
            raise VerificationError("enrolment_changed")
        for sample_id, placement, native in generated:
            stored = db.scalar(select(Template).where(Template.sample_id == sample_id,
                                                      Template.algorithm == reference.algorithm))
            if stored is None:
                stored = Template(id=uuid.uuid4(), sample_id=sample_id, algorithm=reference.algorithm,
                                  version=reference.version, created_at=datetime.now(timezone.utc))
                stored.data = keyring.seal(keys, keyring.TEMPLATE,
                    stored.id.bytes + subject.bytes + reference.algorithm.encode("ascii"), native)
                db.add(stored)
            else:
                if stored.version != reference.version:
                    raise VerificationError("template_version_mismatch")
                native = keyring.open_sealed(keys, keyring.TEMPLATE,
                    stored.id.bytes + subject.bytes + reference.algorithm.encode("ascii"), stored.data)
            templates.append((placement, native))
    return sorted(templates)


def _save(databases: Databases, keys: Keys, subject: uuid.UUID, reference: Reference, png: bytes,
          at: datetime, score: int, duration_ms: int) -> Attempt:
    attempt = Attempt(id=uuid.uuid4(), at=at, subject_id=subject, modality=fp.FINGERPRINT, mode="verify",
                      algorithm=reference.algorithm, enrolment_id=reference.enrolment_id, score=score,
                      threshold=reference.threshold, accepted=score > reference.threshold,
                      duration_ms=duration_ms, source="device")
    attempt.probe = keyring.seal(keys, keyring.PROBE, attempt.id.bytes + subject.bytes, png)
    with Session(databases.biometric, expire_on_commit=False) as db, db.begin():
        # A deletion or replacement during capture invalidates the reference. Lock only for the save,
        # not while the user places a finger. A later deletion cascades to this attempt too (H35).
        enrolment = db.scalar(select(Enrolment).where(
            Enrolment.id == reference.enrolment_id, Enrolment.subject_id == subject).with_for_update())
        if enrolment is None or enrolment.replaced_at is not None:
            raise VerificationError("enrolment_changed")
        db.add(attempt)
    return attempt


_match_bytes = fp.match_pairs  # H43: shared with identification (H45)


def _reference_image(databases: Databases, keys: Keys, subject: uuid.UUID, enrolment_id: uuid.UUID,
                      placement: int, pores_version: str | None = None) -> tuple[bytes, bytes | None]:
    """H18, H43: one capture of the caller's current enrolment for the winning comparison.

    H44: with `pores_version`, also the stored Pore SIFT template of that capture, whose points
    Pore CNN was described from (H39, H42), when it exists in that version."""
    with Session(databases.biometric) as db:
        row = db.execute(select(Sample.id, Sample.data).join(Enrolment).where(
            Enrolment.id == enrolment_id, Enrolment.subject_id == subject, Enrolment.modality == fp.FINGERPRINT,
            Enrolment.replaced_at.is_(None), Sample.placement == placement)).first()
        if row is None:
            raise VerificationError("enrolment_changed")
        stored = None
        if pores_version is not None:
            stored = db.execute(select(Template.id, Template.version, Template.data).where(
                Template.sample_id == row.id, Template.algorithm == fp.PORE_SIFT)).first()
    image = keyring.open_sealed(keys, keyring.SAMPLE, row.id.bytes + subject.bytes, row.data)
    if stored is None or stored.version != pores_version:
        return image, None
    return image, keyring.open_sealed(keys, keyring.TEMPLATE,
                                      stored.id.bytes + subject.bytes + fp.PORE_SIFT.encode("ascii"), stored.data)


async def verify(service: fp.FingerprintService, databases: Databases, keys: Keys, subject: uuid.UUID,
                 finger: int, algorithm: str = fp.OPENCV_SIFT) -> AsyncIterator[dict]:
    if not service.scanner_lock.acquire(blocking=False):
        yield {"type": "failed", "error": "scanner_busy"}
        return
    run = ScannerRun()
    try:
        async for event in _verify(service, databases, keys, subject, finger, run, algorithm):
            yield event
    except VerificationError as error:
        yield {"type": "failed", "error": str(error)}
    except ScannerError as error:
        yield {"type": "failed", "error": error.code}
    except EngineError:
        yield {"type": "failed", "error": "engine_unavailable"}
    except keyring.KeysError:
        yield {"type": "failed", "error": "stored_template_unreadable"}
    except Exception as error:
        logger.error("fingerprint verification failed (%s)", type(error).__name__)
        yield {"type": "failed", "error": "unexpected"}
    finally:
        run.cancel()
        service.scanner_lock.release()


async def _verify(service, databases, keys, subject, finger, run, algorithm) -> AsyncIterator[dict]:
    if algorithm not in (fp.OPENCV_SIFT, fp.PORE_SIFT, fp.LEARNED_PORE):
        raise VerificationError("unknown_method")
    engine = fp.engine_for(service, algorithm)
    if engine is None:
        raise VerificationError("method_unavailable")
    reference = await run_in_threadpool(_load, databases, keys, subject, finger, algorithm)
    yield {"type": "started", "finger": finger, "threshold": reference.threshold,
           "quality_minimum": service.quality_minimum, "references": fp.PLACEMENTS,
           "algorithm": algorithm, "threshold_provisional": reference.provisional}
    if reference.pending:
        yield {"type": "preparing_templates", "completed": 0, "total": len(reference.pending)}
    await run_in_threadpool(service.quality.start)
    ready = await run_in_threadpool(engine.start)
    if ready["version"] != reference.version:
        raise VerificationError("template_version_mismatch")
    described_from: dict[int, bytes] = {}  # H44: the pores of Pore CNN templates prepared in this run
    if reference.pending:
        generated = []
        for sample_id, placement, png in reference.pending:
            pores = reference.pore_sources.get(sample_id)
            if algorithm == fp.LEARNED_PORE:
                if pores is None:
                    pores = await run_in_threadpool(fp.detect_pores, service, png)
                described_from[placement] = pores
            native = await run_in_threadpool(fp.extract_native, service, algorithm, png, pores)
            generated.append((sample_id, placement, native))
            yield {"type": "preparing_templates", "completed": len(generated), "total": len(reference.pending)}
        reference.templates = await run_in_threadpool(_store_templates, databases, keys, subject, reference, generated)
        reference.pending.clear()
        reference.pore_sources.clear()
    for capture in range(1, fp.MOST_CAPTURES + 1):
        yield {"type": "place", "capture": capture, "maximum": fp.MOST_CAPTURES}
        header, png = await fp.acquire(service, "finger", run)
        at, started = datetime.now(timezone.utc), time.perf_counter()
        yield {"type": "checking"}
        score, checks = await run_in_threadpool(fp.capture_quality, service, header, png)
        image = base64.b64encode(png).decode("ascii")
        if checks[-1]["passed"]:
            break
        yield {"type": "rejected", "image": image, "checks": checks, "score": score,
               "minimum": service.quality_minimum}
        if capture == fp.MOST_CAPTURES:
            raise VerificationError("too_many_captures")
        yield {"type": "lift"}
        await fp.acquire(service, "lift", run)

    yield {"type": "captured", "image": image, "checks": checks}
    yield {"type": "comparing", "completed": 0, "total": len(reference.templates)}
    probe_pores = None
    if algorithm == fp.LEARNED_PORE:
        probe_pores = await run_in_threadpool(fp.detect_pores, service, png)
    native = await run_in_threadpool(fp.extract_native, service, algorithm, png, probe_pores)
    comparisons = []
    # H43, H44: OpenCV SIFT and Pore SIFT templates hold their points, so each scoring comparison also
    # returns the pairs it counts. Pore CNN templates hold descriptors only (see below).
    pairs_in_comparison = algorithm in (fp.OPENCV_SIFT, fp.PORE_SIFT)
    best_score, best_placement, best_template, best_pairs = -1, None, b"", b""
    for placement, template in reference.templates:
        request = {"op": "compare", "view": True} if pairs_in_comparison else {"op": "compare"}
        result, parts = await run_in_threadpool(engine.request, request, [native, template])
        # H10 counts the research's defined comparison failures as zero. Process/protocol failures
        # raise EngineError and never become a non-match decision.
        value = fp.comparison_score(result)
        pairs = _match_bytes(result, parts, value) if pairs_in_comparison else b""
        if value > best_score:
            best_score, best_placement, best_template, best_pairs = value, placement, template, pairs
        comparisons.append({"placement": placement, "score": int(value),
                            "accepted": value > reference.threshold, "computed": result.get("status") == "ok"})
        yield {"type": "comparing", "completed": len(comparisons), "total": len(reference.templates)}
    score = max(item["score"] for item in comparisons)
    duration_ms = round((time.perf_counter() - started) * 1000)
    pores_version = reference.version if algorithm == fp.LEARNED_PORE else None
    stored_image, stored_pores = await run_in_threadpool(_reference_image, databases, keys, subject,
                                                         reference.enrolment_id, best_placement, pores_version)
    if algorithm == fp.LEARNED_PORE:
        # H44: repeat the winning comparison once with the pores each template was described from: this
        # run's detection for the probe, and for the stored capture this run's preparation, its Pore SIFT
        # template, or the pinned detector. The repeated score must equal the deciding one.
        reference_pores = described_from.get(best_placement) or stored_pores
        if reference_pores is None:
            reference_pores = await run_in_threadpool(fp.detect_pores, service, stored_image)
        result, parts = await run_in_threadpool(engine.request, {"op": "compare", "view": True},
                                                [native, best_template, probe_pores, reference_pores])
        if fp.comparison_score(result) != best_score:
            raise EngineError("the repeated comparison changed its score")
        best_pairs = _match_bytes(result, parts, best_score)
    match_view = {"placement": best_placement, "reference_image": base64.b64encode(stored_image).decode("ascii"),
                  "count": score, "pairs": base64.b64encode(best_pairs).decode("ascii")}
    yield {"type": "saving"}
    attempt = await run_in_threadpool(_save, databases, keys, subject, reference, png, at, score, duration_ms)
    yield {"type": "verified", "attempt_id": str(attempt.id), "at": attempt.at.isoformat(),
           "finger": finger, "algorithm": algorithm, "score": score, "threshold": attempt.threshold,
           "threshold_provisional": reference.provisional,
           "threshold_origin": reference.origin, "accepted": attempt.accepted, "duration_ms": duration_ms,
           "comparisons": comparisons, "match_view": match_view}
