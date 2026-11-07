"""Fingerprint 1:1 verification (H15, H25, H35). Compare one quality-checked capture with the three
stored templates of the signed-in user's selected finger. The highest score decides, strictly above the
threshold. A result is sent only after its attempt and sealed probe have committed."""

from __future__ import annotations

import base64
import logging
import math
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
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


def _load(databases: Databases, keys: Keys, subject: uuid.UUID, finger: int) -> Reference:
    with Session(databases.biometric) as db:
        enrolment = db.scalar(select(Enrolment).where(
            Enrolment.subject_id == subject, Enrolment.modality == fp.FINGERPRINT,
            Enrolment.finger == finger, Enrolment.replaced_at.is_(None)))
        if enrolment is None:
            raise VerificationError("not_enrolled")
        algorithm = db.get(Algorithm, fp.OPENCV_SIFT)
        rows = db.execute(select(Sample.placement, Template).join(Template, Template.sample_id == Sample.id).where(
            Sample.enrolment_id == enrolment.id, Template.algorithm == fp.OPENCV_SIFT).order_by(Sample.placement)).all()
        if len(rows) != fp.PLACEMENTS or any(template.data is None for _, template in rows):
            raise VerificationError("templates_unavailable")
        if any(template.version != algorithm.version for _, template in rows):
            raise VerificationError("template_version_mismatch")
        templates = [(placement, keyring.open_sealed(
            keys, keyring.TEMPLATE, template.id.bytes + subject.bytes + fp.OPENCV_SIFT.encode("ascii"), template.data))
            for placement, template in rows]
        return Reference(enrolment.id, algorithm.threshold, algorithm.threshold_origin, algorithm.version, templates)


def _save(databases: Databases, keys: Keys, subject: uuid.UUID, reference: Reference, png: bytes,
          at: datetime, score: int, duration_ms: int) -> Attempt:
    attempt = Attempt(id=uuid.uuid4(), at=at, subject_id=subject, modality=fp.FINGERPRINT, mode="verify",
                      algorithm=fp.OPENCV_SIFT, enrolment_id=reference.enrolment_id, score=score,
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


async def verify(service: fp.FingerprintService, databases: Databases, keys: Keys, subject: uuid.UUID,
                 finger: int) -> AsyncIterator[dict]:
    if not service._busy.acquire(blocking=False):
        yield {"type": "failed", "error": "scanner_busy"}
        return
    run = ScannerRun()
    try:
        async for event in _verify(service, databases, keys, subject, finger, run):
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
        service._busy.release()


async def _verify(service, databases, keys, subject, finger, run) -> AsyncIterator[dict]:
    reference = await run_in_threadpool(_load, databases, keys, subject, finger)
    yield {"type": "started", "finger": finger, "threshold": reference.threshold,
           "quality_minimum": service.quality_minimum, "references": len(reference.templates)}
    await run_in_threadpool(service.quality.start)
    ready = await run_in_threadpool(service.sift.start)
    if ready["version"] != reference.version:
        raise VerificationError("template_version_mismatch")
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
    _, parts = await run_in_threadpool(service.sift.request, {"op": "extract"}, [png])
    comparisons = []
    for placement, template in reference.templates:
        result, _ = await run_in_threadpool(service.sift.request, {"op": "compare"}, [parts[0], template])
        # H10 counts the research's defined comparison failures as zero. Process/protocol failures
        # raise EngineError and never become a non-match decision.
        if result.get("status") not in ("ok", "failure"):
            raise EngineError("invalid comparison status")
        value = 0 if result["status"] == "failure" else result.get("score")
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or int(value) != value:
            raise EngineError("invalid comparison score")
        comparisons.append({"placement": placement, "score": int(value),
                            "accepted": value > reference.threshold, "computed": result.get("status") == "ok"})
        yield {"type": "comparing", "completed": len(comparisons), "total": len(reference.templates)}
    score = max(item["score"] for item in comparisons)
    duration_ms = round((time.perf_counter() - started) * 1000)
    yield {"type": "saving"}
    attempt = await run_in_threadpool(_save, databases, keys, subject, reference, png, at, score, duration_ms)
    yield {"type": "verified", "attempt_id": str(attempt.id), "at": attempt.at.isoformat(),
           "finger": finger, "algorithm": fp.OPENCV_SIFT, "score": score, "threshold": attempt.threshold,
           "threshold_origin": reference.origin, "accepted": attempt.accepted, "duration_ms": duration_ms,
           "comparisons": comparisons}
