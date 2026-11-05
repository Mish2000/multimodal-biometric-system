"""Fingerprint enrolment (H6, H7, H15, H25, H33).

The user chooses a finger and places it on the scanner, lifting it between placements. Every capture
passes H7's checks in the scanner and NFIQ 2's quality minimum here; a capture below it is not kept and
the finger is placed again. A kept capture gets its OpenCV SIFT template, and every pair of kept captures
is compared (the later one as probe, the earlier as reference, as in H10). The enrolment keeps three
captures whose three pairs are all above OpenCV SIFT's threshold (H15); when no three do, one more
placement is asked for. The kept captures and their templates are sealed, each bound to its row and its
subject (H25); a new enrolment of the same finger replaces the old one, which stays.

The data the template screen shows is sent once, from memory, to the user who enrols; no stored template
is opened for it, since only the engines read templates (H14).
"""

from __future__ import annotations

import base64
import itertools
import json
import logging
import threading
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session as DbSession
from starlette.concurrency import run_in_threadpool

from . import keys as keyring
from .config import Config, REPOSITORY, research_python
from .db import Databases
from .engines import Engine, EngineError, Scanner, ScannerError, ScannerRun, conda_environment
from .keys import Keys
from .models import Algorithm, Enrolment, Sample, Template

logger = logging.getLogger("mbs.fingerprint")
FINGERPRINT = "fingerprint"
OPENCV_SIFT = "opencv-sift"
PLACEMENTS = 3  # H6, H9, H15
QUALITY_MINIMUM = 35  # NFIQ 2.3, provisional (H33): none of the researcher's 40 captures scored below it
MOST_KEPT = 6  # placements kept while looking for three that match each other (H33)
MOST_CAPTURES = 12  # captures, kept or not, in one enrolment (H33)
FINGER_WAIT_S = 60
LIFT_WAIT_S = 30
PENDING_METHODS = ("pore-sift", "learned-pore")  # increment 3 makes their templates from the same captures (H6)


@dataclass
class Kept:
    placement: int
    captured_at: datetime
    png: bytes
    checks: list
    quality: int
    template: bytes
    keypoints: int
    points: bytes  # float32 x, y per keypoint, for the template screen
    descriptors: bytes  # uint8, 128 per keypoint


@dataclass
class FingerprintService:
    scanner: Scanner
    quality: Engine
    sift: Engine
    quality_minimum: int = QUALITY_MINIMUM
    _busy: threading.Lock = field(default_factory=threading.Lock)

    def warm_up(self) -> None:
        """Start both engines in the background, so the first enrolment does not wait for them."""
        def start():
            for engine in (self.quality, self.sift):
                try:
                    engine.start()
                except EngineError:
                    pass  # reported when an enrolment needs it
        threading.Thread(target=start, daemon=True).start()

    def close(self) -> None:
        self.quality.close()
        self.sift.close()


def from_config(config: Config) -> tuple[FingerprintService | None, str]:
    """The service with this machine's scanner, engines and NFIQ 2 build, or None and what is missing."""
    python = research_python()
    missing = [name for name, ok in (
        ("scanner_driver_dir in local/server.toml", config.scanner_driver_dir and config.scanner_driver_dir.exists()),
        ("the built ScannerCapture.exe", config.scanner_exe.exists()),
        ("nfiq2_bin in local/server.toml", config.nfiq2_bin and (config.nfiq2_bin / "Nfiq2Api.dll").exists()),
        ("project_python in local/research.toml", python and python.exists()),
    ) if not ok]
    if missing:
        return None, "missing: " + ", ".join(missing)
    env = conda_environment(python)
    engines = REPOSITORY / "engines"
    return FingerprintService(
        scanner=Scanner([str(config.scanner_exe), "oem-acquire", "--driver-dir", str(config.scanner_driver_dir)]),
        quality=Engine("nfiq2", [str(python), "-I", str(engines / "nfiq2_quality.py"), str(config.nfiq2_bin)], env),
        sift=Engine(OPENCV_SIFT, [str(python), "-I", str(engines / "opencv_sift.py")], env),
    ), ""


def _db(engine) -> DbSession:
    return DbSession(engine, expire_on_commit=False)


def enrolled_fingers(databases: Databases, subject: uuid.UUID) -> list[int]:
    with _db(databases.biometric) as db:
        rows = db.scalars(select(Enrolment.finger).where(Enrolment.subject_id == subject, Enrolment.modality == FINGERPRINT,
                                                         Enrolment.replaced_at.is_(None)).order_by(Enrolment.finger))
        return list(rows)


def delete_finger(databases: Databases, subject: uuid.UUID, finger: int) -> bool:
    """H34: the user deletes a finger's enrolment. Every enrolment of that finger, the current one and those
    it replaced, is erased with its sealed captures and templates; False when the finger is not enrolled."""
    with _db(databases.biometric) as db, db.begin():
        rows = db.execute(select(Enrolment.id, Enrolment.replaced_at).where(
            Enrolment.subject_id == subject, Enrolment.modality == FINGERPRINT, Enrolment.finger == finger)).all()
        if not any(replaced_at is None for _, replaced_at in rows):
            return False
        enrolments = [enrolment_id for enrolment_id, _ in rows]
        samples = select(Sample.id).where(Sample.enrolment_id.in_(enrolments))
        db.execute(delete(Template).where(Template.sample_id.in_(samples)))
        db.execute(delete(Sample).where(Sample.enrolment_id.in_(enrolments)))
        db.execute(delete(Enrolment).where(Enrolment.id.in_(enrolments)))
    return True


def best_three(kept: list[Kept], scores: dict[tuple[int, int], int | None], threshold: float) -> tuple[int, int, int] | None:
    """Three kept captures whose three pairs are all above the threshold (H15): of those, the three with the
    highest lowest score, and the earliest when equal. `scores` holds (earlier, later) indexes into `kept`."""
    best, best_low = None, None
    for trio in itertools.combinations(range(len(kept)), 3):
        values = [scores.get(pair) for pair in itertools.combinations(trio, 2)]
        if any(v is None or v <= threshold for v in values):
            continue
        if best_low is None or min(values) > best_low:
            best, best_low = trio, min(values)
    return best


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _check(name: str, passed: bool, detail: str, **extra) -> dict:
    return {"name": name, "passed": passed, "detail": detail, **extra}


async def enrol(service: FingerprintService, databases: Databases, keys: Keys, subject: uuid.UUID,
                finger: int) -> AsyncIterator[dict]:
    """The enrolment as a series of events for the client; it ends with `saved` or `failed`."""
    if not service._busy.acquire(blocking=False):
        yield {"type": "failed", "error": "scanner_busy"}
        return
    run = ScannerRun()
    try:
        async for event in _enrol(service, databases, keys, subject, finger, run):
            yield event
    except Exception:
        logger.exception("fingerprint enrolment failed")
        yield {"type": "failed", "error": "unexpected"}
    finally:
        run.cancel()  # the client went away or the enrolment ended: no scanner run outlives it
        service._busy.release()


def _quiet(_header: dict) -> None:
    """The scanner's own progress (frames without a finger) is not forwarded."""


async def _enrol(service, databases, keys, subject, finger, run) -> AsyncIterator[dict]:
    threshold = await run_in_threadpool(_threshold, databases)
    scanner_event = _quiet
    yield {"type": "started", "finger": finger, "placements": PLACEMENTS, "quality_minimum": service.quality_minimum,
           "threshold": threshold, "most_kept": MOST_KEPT}
    try:
        await run_in_threadpool(service.quality.start)
        ready = await run_in_threadpool(service.sift.start)
    except EngineError:
        yield {"type": "failed", "error": "engine_unavailable"}
        return
    version = ready["version"]
    kept: list[Kept] = []
    scores: dict[tuple[int, int], int | None] = {}
    placement = captures = 0
    while True:
        if captures >= MOST_CAPTURES:
            yield {"type": "failed", "error": "too_many_captures"}
            return
        yield {"type": "place", "placement": placement + 1, "kept": len(kept)}
        try:
            header, png = await run_in_threadpool(service.scanner.acquire, "finger", FINGER_WAIT_S, scanner_event, run)
        except ScannerError as error:
            yield {"type": "failed", "error": error.code}
            return
        captures += 1
        captured_at = datetime.now(timezone.utc)
        try:
            reply, _ = await run_in_threadpool(service.quality.request, {"op": "quality"}, [png])
        except EngineError:
            yield {"type": "failed", "error": "engine_unavailable"}
            return
        score = reply.get("score")
        passed = bool(reply.get("valid")) and score >= service.quality_minimum
        quality = _check("quality", passed, f"NFIQ 2 score {score if score is not None else 'not computed'} "
                                            f"(at least {service.quality_minimum})", score=score)
        checks = [*header.get("checks", []), quality]
        if not passed:
            yield {"type": "rejected", "reason": "quality", "image": _b64(png), "checks": checks, "score": score,
                   "minimum": service.quality_minimum}
        else:
            placement += 1
            try:
                reply, parts = await run_in_threadpool(service.sift.request, {"op": "extract"}, [png])
            except EngineError:
                yield {"type": "failed", "error": "engine_unavailable"}
                return
            new = Kept(placement, captured_at, png, checks, score, parts[0], reply["keypoints"], parts[1], parts[2])
            pairs = []
            for index, earlier in enumerate(kept):
                try:
                    result, _ = await run_in_threadpool(service.sift.request, {"op": "compare"}, [new.template, earlier.template])
                except EngineError:
                    yield {"type": "failed", "error": "engine_unavailable"}
                    return
                scores[(index, len(kept))] = result.get("score")
                pairs.append({"probe": new.placement, "reference": earlier.placement, "score": result.get("score"),
                              "accepted": (result.get("score") or 0) > threshold})
            kept.append(new)
            yield {"type": "kept", "placement": placement, "image": _b64(png), "checks": checks,
                   "keypoints": new.keypoints, "pairs": pairs}
            if len(kept) >= PLACEMENTS:
                trio = best_three(kept, scores, threshold)
                if trio is not None:
                    chosen = [kept[i] for i in trio]
                    saved = await run_in_threadpool(_save, databases, keys, subject, finger, chosen, version)
                    yield _saved_event(saved, chosen, kept, scores, trio, threshold)
                    return
                if len(kept) >= MOST_KEPT:
                    yield {"type": "failed", "error": "placements_do_not_match"}
                    return
                yield {"type": "another_placement", "kept": len(kept)}
        yield {"type": "lift"}
        try:
            await run_in_threadpool(service.scanner.acquire, "lift", LIFT_WAIT_S, scanner_event, run)
        except ScannerError as error:
            yield {"type": "failed", "error": error.code}
            return


def _threshold(databases: Databases) -> float:
    with _db(databases.biometric) as db:
        return db.get(Algorithm, OPENCV_SIFT).threshold


@dataclass
class Saved:
    enrolment: Enrolment
    replaced: bool
    samples: list[Sample]
    templates: list[Template]


def _save(databases: Databases, keys: Keys, subject: uuid.UUID, finger: int, chosen: list[Kept], version: str) -> Saved:
    now = datetime.now(timezone.utc)
    with _db(databases.biometric) as db, db.begin():
        replaced = db.execute(update(Enrolment).where(
            Enrolment.subject_id == subject, Enrolment.modality == FINGERPRINT, Enrolment.finger == finger,
            Enrolment.replaced_at.is_(None)).values(replaced_at=now)).rowcount
        enrolment = Enrolment(id=uuid.uuid4(), subject_id=subject, modality=FINGERPRINT, finger=finger, created_at=now)
        db.add(enrolment)
        db.flush()
        samples, templates = [], []
        for capture in chosen:
            sample = Sample(id=uuid.uuid4(), enrolment_id=enrolment.id, placement=capture.placement,
                            captured_at=capture.captured_at, media_type="image/png", width=1000, height=1000, ppi=1000,
                            checks=capture.checks)
            sample.data = keyring.seal(keys, keyring.SAMPLE, sample.id.bytes + subject.bytes, capture.png)
            template = Template(id=uuid.uuid4(), sample_id=sample.id, algorithm=OPENCV_SIFT, version=version, created_at=now)
            template.data = keyring.seal(keys, keyring.TEMPLATE, template.id.bytes + subject.bytes + OPENCV_SIFT.encode("ascii"),
                                         capture.template)
            db.add(sample)
            db.flush()
            db.add(template)
            samples.append(sample)
            templates.append(template)
    return Saved(enrolment, replaced > 0, samples, templates)


def _sealed_parts(sealed: bytes) -> dict:
    """How a sealed value is laid out (H14): MBS1, the key version, the salt, the nonce, the ciphertext, the tag."""
    header = keyring.HEADER_BYTES
    return {"length": len(sealed), "head": _b64(sealed[:header + 48]), "tag": _b64(sealed[-16:]),
            "magic": 4, "version": 2, "salt": keyring.SALT_BYTES, "nonce": keyring.NONCE_BYTES,
            "ciphertext": len(sealed) - header - 16, "tag_bytes": 16}


def _saved_event(saved: Saved, chosen: list[Kept], kept: list[Kept], scores: dict, trio: tuple, threshold: float) -> dict:
    pairs = []
    for a, b in itertools.combinations(trio, 2):
        score = scores.get((a, b))
        pairs.append({"probe": kept[b].placement, "reference": kept[a].placement, "score": score,
                      "accepted": score is not None and score > threshold})
    return {
        "type": "saved",
        "enrolment": {"id": str(saved.enrolment.id), "finger": saved.enrolment.finger,
                      "created_at": saved.enrolment.created_at.isoformat(), "replaced_previous": saved.replaced},
        "samples": [{"id": str(s.id), "placement": s.placement, "captured_at": s.captured_at.isoformat(),
                     "media_type": s.media_type, "sealed_length": len(s.data), "quality": c.quality}
                    for s, c in zip(saved.samples, chosen)],
        "templates": [{"id": str(t.id), "sample_id": str(t.sample_id), "placement": c.placement, "algorithm": t.algorithm,
                       "version": t.version, "created_at": t.created_at.isoformat(), "keypoints": c.keypoints,
                       "points": _b64(c.points), "descriptors": _b64(c.descriptors), "template_length": len(c.template),
                       "sealed": _sealed_parts(t.data)}
                      for t, c in zip(saved.templates, chosen)],
        "pairs": pairs, "threshold": threshold, "pending_methods": list(PENDING_METHODS),
        "not_kept": [k.placement for i, k in enumerate(kept) if i not in trio],
    }


def ndjson(events: AsyncIterator[dict]) -> AsyncIterator[bytes]:
    async def lines():
        async for event in events:
            yield (json.dumps(event, separators=(",", ":")) + "\n").encode("utf-8")
    return lines()
