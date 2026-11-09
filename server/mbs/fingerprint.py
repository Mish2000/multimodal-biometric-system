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
import math
import struct
import threading
import uuid
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import anyio
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session as DbSession
from starlette.concurrency import run_in_threadpool

from . import keys as keyring
from .config import Config, REPOSITORY, research_python, pore_python, learned_python
from .db import Databases
from .engines import Engine, EngineError, Scanner, ScannerError, ScannerRun, conda_environment
from .keys import Keys
from .models import Algorithm, Enrolment, Sample, Template

logger = logging.getLogger("mbs.fingerprint")
FINGERPRINT = "fingerprint"
OPENCV_SIFT = "opencv-sift"
PORE_SIFT = "pore-sift"
LEARNED_PORE = "learned-pore"
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
    pore: Engine | None = None  # H38: the research's separate Pore SIFT runtime
    learned: Engine | None = None  # H39: Pore CNN, in its research runtime
    _busy: threading.Lock = field(default_factory=threading.Lock)
    _search_peers: dict[str, list[Engine]] = field(default_factory=dict)

    def search_engines(self, algorithm: str = OPENCV_SIFT) -> list[Engine]:
        """H41, H42: four CPU workers or one GPU runtime, under the shared capture lock."""
        engine = engine_for(self, algorithm)
        if engine is None:
            raise EngineError("method is unavailable")
        if algorithm == LEARNED_PORE:
            return [engine]
        if algorithm not in self._search_peers:
            self._search_peers[algorithm] = [engine.peer() for _ in range(3)]
        return [engine, *self._search_peers[algorithm]]

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
        if self.pore is not None:
            self.pore.close()
        if self.learned is not None:
            self.learned.close()
        for peers in self._search_peers.values():
            for engine in peers:
                engine.close()


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
    pore = pore_python()
    learned = learned_python()
    return FingerprintService(
        scanner=Scanner([str(config.scanner_exe), "oem-acquire", "--driver-dir", str(config.scanner_driver_dir)]),
        quality=Engine("nfiq2", [str(python), "-I", str(engines / "nfiq2_quality.py"), str(config.nfiq2_bin)], env),
        sift=Engine(OPENCV_SIFT, [str(python), "-I", str(engines / "opencv_sift.py")], env),
        pore=Engine(PORE_SIFT, [str(pore), "-I", "-B", str(engines / "pore_sift.py"), str(python)], conda_environment(pore))
             if pore and pore.exists() else None,
        learned=Engine(LEARNED_PORE, [str(learned), "-I", "-B", str(engines / "learned_pore.py")],
                       conda_environment(learned)) if pore and pore.exists() and learned and learned.exists() else None,
    ), ""


def _db(engine) -> DbSession:
    return DbSession(engine, expire_on_commit=False)


def enrolled_fingers(databases: Databases, subject: uuid.UUID) -> list[int]:
    with _db(databases.biometric) as db:
        rows = db.scalars(select(Enrolment.finger).where(Enrolment.subject_id == subject, Enrolment.modality == FINGERPRINT,
                                                         Enrolment.replaced_at.is_(None)).order_by(Enrolment.finger))
        return list(rows)


def methods(databases: Databases, service: FingerprintService | None) -> list[dict]:
    """H38: only implemented methods are offered. Their decision settings come from the database."""
    with _db(databases.biometric) as db:
        catalog = []
        for code in (OPENCV_SIFT, LEARNED_PORE, PORE_SIFT):
            algorithm = db.get(Algorithm, code)
            if algorithm is not None:
                catalog.append({"code": code, "threshold": algorithm.threshold,
                                "threshold_provisional": algorithm.threshold_provisional,
                                "threshold_origin": algorithm.threshold_origin,
                                "available": service is not None and engine_for(service, code) is not None})
        return catalog


def engine_for(service: FingerprintService, code: str) -> Engine | None:
    """H39: the selected descriptor's runtime; Pore CNN extraction also needs the shared detector."""
    if code == OPENCV_SIFT:
        return service.sift
    if code == PORE_SIFT:
        return service.pore
    if code == LEARNED_PORE and service.pore is not None:
        return service.learned
    return None


def detect_pores(service: FingerprintService, png: bytes) -> bytes:
    """H39: the shared detector's points for one capture, without computing SIFT descriptors."""
    engine = engine_for(service, LEARNED_PORE)
    if engine is None:
        raise EngineError("method is unavailable")
    if service.pore.start()["version"] != engine.start()["version"]:
        raise EngineError("detector and descriptor versions differ")
    _, detected = service.pore.request({"op": "detect"}, [png])
    if not detected or not detected[0]:
        raise EngineError("missing pore coordinates")
    return detected[0]


def extract_native(service: FingerprintService, code: str, png: bytes, pores: bytes | None = None) -> bytes:
    """H39: reuse Pore SIFT's points when present, otherwise detect once without computing SIFT."""
    engine = engine_for(service, code)
    if engine is None:
        raise EngineError("method is unavailable")
    parts = [png]
    if code == LEARNED_PORE:
        if pores is None:
            pores = detect_pores(service, png)
        parts.append(pores)
    _, native = engine.request({"op": "extract"}, parts)
    if not native or not native[0]:
        raise EngineError("missing native template")
    return native[0]


def match_pairs(reply: dict, parts: list[bytes], score: int) -> bytes:
    """H43, H44, H45: exactly one native-coordinate pair per point or pore counted in the score."""
    if type(reply.get("matches")) is not int or reply["matches"] != score or len(parts) != 1 or len(parts[0]) != score * 16:
        raise EngineError("invalid match illustration")
    if any(not math.isfinite(value) or not 0 <= value < 1000
           for pair in struct.iter_unpack("<4f", parts[0]) for value in pair):
        raise EngineError("invalid match coordinates")
    return parts[0]


def comparison_score(result: dict) -> int:
    """H10, H35, H39: defined comparison failures score zero; invalid replies are technical errors."""
    if result.get("status") not in ("ok", "failure"):
        raise EngineError("invalid comparison status")
    value = 0 if result["status"] == "failure" else result.get("score")
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or int(value) != value:
        raise EngineError("invalid comparison score")
    return int(value)


def delete_finger(databases: Databases, subject: uuid.UUID, finger: int) -> bool:
    """H34: the user deletes a finger's enrolment. Every enrolment of that finger, the current one and those
    it replaced, is erased with its sealed captures and templates; False when the finger is not enrolled."""
    with _db(databases.biometric) as db, db.begin():
        # H42: preparation holds the enrolment before writing templates. Take the same lock before deleting samples.
        rows = db.execute(select(Enrolment.id, Enrolment.replaced_at).where(
            Enrolment.subject_id == subject, Enrolment.modality == FINGERPRINT, Enrolment.finger == finger
        ).order_by(Enrolment.id).with_for_update()).all()
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


async def acquire(service: FingerprintService, wait: str, run: ScannerRun) -> tuple[dict, bytes | None]:
    """H35: a disconnect must interrupt a blocking scanner wait, then finish its cleanup before another
    operation takes the scanner. Used by both enrolment and verification."""
    started, finished = threading.Event(), threading.Event()

    def capture():
        started.set()
        try:
            seconds = FINGER_WAIT_S if wait == "finger" else LIFT_WAIT_S
            return service.scanner.acquire(wait, seconds, _quiet, run)
        finally:
            finished.set()

    try:
        return await anyio.to_thread.run_sync(capture, abandon_on_cancel=True)
    finally:
        if not finished.is_set():
            run.cancel()
            if started.is_set():
                with anyio.CancelScope(shield=True):
                    await anyio.to_thread.run_sync(finished.wait)


def capture_quality(service: FingerprintService, header: dict, png: bytes) -> tuple[int | None, list[dict]]:
    """H33, H35: the same quality gate for every capture. Invalid NFIQ values never pass."""
    reply, _ = service.quality.request({"op": "quality"}, [png])
    score = reply.get("score")
    valid = reply.get("valid") is True and type(score) is int and 0 <= score <= 100
    score = score if valid else None
    quality = _check("quality", valid and score >= service.quality_minimum,
                     f"NFIQ 2 score {score if score is not None else 'not computed'} "
                     f"(at least {service.quality_minimum})", score=score)
    return score, [*header.get("checks", []), quality]


async def _enrol(service, databases, keys, subject, finger, run) -> AsyncIterator[dict]:
    threshold = await run_in_threadpool(_threshold, databases)
    catalog = {method["code"]: method for method in await run_in_threadpool(methods, databases, service)}
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
            header, png = await acquire(service, "finger", run)
        except ScannerError as error:
            yield {"type": "failed", "error": error.code}
            return
        captures += 1
        captured_at = datetime.now(timezone.utc)
        try:
            score, checks = await run_in_threadpool(capture_quality, service, header, png)
        except EngineError:
            yield {"type": "failed", "error": "engine_unavailable"}
            return
        if not checks[-1]["passed"]:
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
                    extra: dict[str, list[bytes]] = {}
                    comparisons = []
                    for code in (PORE_SIFT, LEARNED_PORE):
                        engine = engine_for(service, code)
                        if engine is None:
                            continue
                        extra[code] = []
                        yield {"type": "templates", "algorithm": code, "completed": 0, "total": PLACEMENTS}
                        try:
                            method_ready = await run_in_threadpool(engine.start)
                            if method_ready["version"] != version:
                                raise EngineError("method version differs from the research pin")
                            for index, capture in enumerate(chosen):
                                pores = extra[PORE_SIFT][index] if code == LEARNED_PORE else None
                                native = await run_in_threadpool(extract_native, service, code, capture.png, pores)
                                extra[code].append(native)
                                yield {"type": "templates", "algorithm": code,
                                       "completed": len(extra[code]), "total": PLACEMENTS}
                            pairs = []
                            for a, b in itertools.combinations(range(PLACEMENTS), 2):
                                reply, _ = await run_in_threadpool(engine.request, {"op": "compare"},
                                                                  [extra[code][b], extra[code][a]])
                                value = comparison_score(reply)
                                pairs.append({"probe": chosen[b].placement, "reference": chosen[a].placement,
                                              "score": value, "accepted": value > catalog[code]["threshold"]})
                            comparisons.append({"algorithm": code, "threshold": catalog[code]["threshold"],
                                                "threshold_provisional": catalog[code]["threshold_provisional"], "pairs": pairs})
                        except EngineError:
                            yield {"type": "failed", "error": "engine_unavailable"}
                            return
                    saved = await run_in_threadpool(_save, databases, keys, subject, finger, chosen, version,
                                                    extra.get(PORE_SIFT), extra.get(LEARNED_PORE))
                    yield _saved_event(saved, chosen, kept, scores, trio, threshold, comparisons)
                    return
                if len(kept) >= MOST_KEPT:
                    yield {"type": "failed", "error": "placements_do_not_match"}
                    return
                yield {"type": "another_placement", "kept": len(kept)}
        yield {"type": "lift"}
        try:
            await acquire(service, "lift", run)
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
    pore_templates: list[Template] = field(default_factory=list)
    learned_templates: list[Template] = field(default_factory=list)


def _save(databases: Databases, keys: Keys, subject: uuid.UUID, finger: int, chosen: list[Kept], version: str,
          pore_data: list[bytes] | None = None, learned_data: list[bytes] | None = None) -> Saved:
    now = datetime.now(timezone.utc)
    with _db(databases.biometric) as db, db.begin():
        replaced = db.execute(update(Enrolment).where(
            Enrolment.subject_id == subject, Enrolment.modality == FINGERPRINT, Enrolment.finger == finger,
            Enrolment.replaced_at.is_(None)).values(replaced_at=now)).rowcount
        enrolment = Enrolment(id=uuid.uuid4(), subject_id=subject, modality=FINGERPRINT, finger=finger, created_at=now)
        db.add(enrolment)
        db.flush()
        samples, templates, pore_templates, learned_templates = [], [], [], []
        for index, capture in enumerate(chosen):
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
            for code, data, rows in ((PORE_SIFT, pore_data, pore_templates), (LEARNED_PORE, learned_data, learned_templates)):
                if data:
                    native = Template(id=uuid.uuid4(), sample_id=sample.id, algorithm=code, version=version, created_at=now)
                    native.data = keyring.seal(keys, keyring.TEMPLATE,
                        native.id.bytes + subject.bytes + code.encode("ascii"), data[index])
                    db.add(native)
                    rows.append(native)
            samples.append(sample)
            templates.append(template)
    return Saved(enrolment, replaced > 0, samples, templates, pore_templates, learned_templates)


def _sealed_parts(sealed: bytes) -> dict:
    """How a sealed value is laid out (H14): MBS1, the key version, the salt, the nonce, the ciphertext, the tag."""
    header = keyring.HEADER_BYTES
    return {"length": len(sealed), "head": _b64(sealed[:header + 48]), "tag": _b64(sealed[-16:]),
            "magic": 4, "version": 2, "salt": keyring.SALT_BYTES, "nonce": keyring.NONCE_BYTES,
            "ciphertext": len(sealed) - header - 16, "tag_bytes": 16}


def _saved_event(saved: Saved, chosen: list[Kept], kept: list[Kept], scores: dict, trio: tuple, threshold: float,
                 comparisons: list[dict] | None = None) -> dict:
    pairs = []
    for a, b in itertools.combinations(trio, 2):
        score = scores.get((a, b))
        pairs.append({"probe": kept[b].placement, "reference": kept[a].placement, "score": score,
                      "accepted": score is not None and score > threshold})
    prepared = [{"algorithm": code, "templates": len(rows)} for code, rows in (
        (PORE_SIFT, saved.pore_templates), (LEARNED_PORE, saved.learned_templates)) if rows]
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
        "pairs": pairs, "threshold": threshold,
        "pending_methods": [code for code in PENDING_METHODS if code not in {method["algorithm"] for method in prepared}],
        "prepared_methods": prepared,
        "referee": OPENCV_SIFT,
        "method_comparisons": [{"algorithm": OPENCV_SIFT, "threshold": threshold,
                                "threshold_provisional": False, "pairs": pairs}, *(comparisons or [])],
        "not_kept": [k.placement for i, k in enumerate(kept) if i not in trio],
    }


def ndjson(events: AsyncIterator[dict]) -> AsyncIterator[bytes]:
    async def lines():
        async with aclosing(events):
            async for event in events:
                yield (json.dumps(event, separators=(",", ":")) + "\n").encode("utf-8")
    return lines()
