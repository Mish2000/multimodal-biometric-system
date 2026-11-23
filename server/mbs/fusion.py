"""The combined test of every enrolled modality (H60), in 1:1 and in 1:N.

Each modality compares as it does alone: OpenCV SIFT for the fingerprint (H35, H41), SFace for the face (H49, H50) and
ECAPA-TDNN for the voice (H55, H56), each taking its best comparison. Its score becomes evidence: the log10 of the
likelihood ratio, how many times more likely the score is for the same person than for another, through the policy's
calibration (the fingerprint's fitted on SD302's plain vs plain development pairs, the face's and the voice's
provisional, from the accuracy their models published). The best of k comparisons counts the ratio divided by k, so
taking the best does not add evidence, and each modality's evidence is capped at its share of the policy's budget
(0.06 x its weight for the first policy). A modality earns weight x (1 + evidence / cap) / 2 points, half of its weight
when it says nothing either way, and the score out of 100 is their sum: 50 + 50 x the total evidence / the budget. A
test is accepted above the policy's threshold, 75, which is a combined likelihood ratio above 1,000: if the curves are
calibrated and the modalities independent, at most one impostor test in 1,000 passes.

A test needs a fingerprint enrolment and at least one more modality, and takes every modality the person enrolled. The
face and the voice are taken by the page first and checked here before the scanner starts; the scan comes last, and
the test is compared, fused and saved in this one request, so nothing is kept between requests. Each comparison is
saved as an attempt of its own, with its sealed sample and its own decision, pointing to the combined test. 1:N searches
the active users enrolled in every modality of the test and ranks them by their combined score; only the caller's own
finger is named (H18).
"""

from __future__ import annotations

import logging
import math
import time
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from . import embeddings, identification, verification
from . import fingerprint as fp
from . import keys as keyring
from .db import Databases
from .embeddings import COMPARISONS, EngineService, Modality, ModalityError
from .engines import EngineError, ScannerError, ScannerRun
from .face import FACES
from .identification import SHOWN_CANDIDATES, IdentificationError, owners_unchanged
from .keys import Keys
from .models import Algorithm, Attempt, Enrolment, FusedAttempt, FusionPolicy, threshold_of, vector_text
from .verification import VerificationError
from .voice import VOICES

logger = logging.getLogger("mbs.fusion")
MODALITIES = ("fingerprint", "face", "voice")
OTHERS: dict[str, Modality] = {"face": FACES, "voice": VOICES}
SAMPLE_AGE = timedelta(minutes=10)  # the face and the voice are taken for this test, as H59's one session


class FusionError(Exception):
    """An expected refusal of a combined test, answered as its code."""


@dataclass(frozen=True)
class Policy:
    id: int
    weights: dict[str, int]
    budget: float
    threshold: float
    calibration: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class Taken:
    """A face image or a voice recording the page took for this test, with when it was taken."""
    data: bytes
    at: datetime


def current_policy(databases: Databases) -> Policy:
    with Session(databases.biometric) as db:
        row = db.scalar(select(FusionPolicy).order_by(FusionPolicy.id.desc()).limit(1))
    if row is None:
        raise FusionError("policy_unavailable")
    return Policy(row.id, {"fingerprint": row.weight_fingerprint, "face": row.weight_face, "voice": row.weight_voice},
                  row.budget, row.threshold, row.calibration)


def cap(policy: Policy, modality: str) -> float:
    return policy.budget * policy.weights[modality] / 100


def log_ratio(calibration: dict[str, Any], score: float) -> float:
    """The natural log of a score's likelihood ratio: logistic in ln(1 + pairs) for the fingerprint, linear in the
    cosine similarity for the face and the voice."""
    if calibration["form"] == "log1p":
        return calibration["a"] + calibration["b"] * math.log1p(max(score, 0.0))
    if calibration["form"] == "linear":
        return calibration["k"] * (score - calibration["t"])
    raise ValueError(f"unknown calibration {calibration['form']}")


def evidence(policy: Policy, modality: str, score: float, compared: int) -> float:
    """log10 of the likelihood ratio of the best of `compared` comparisons, divided by `compared`, capped."""
    limit = cap(policy, modality)
    value = log_ratio(policy.calibration[modality], score) / math.log(10) - math.log10(compared)
    return max(-limit, min(limit, value))


def points(policy: Policy, modality: str, value: float) -> float:
    limit = cap(policy, modality)
    return policy.weights[modality] * (1 + value / limit) / 2 if limit > 0 else policy.weights[modality] / 2


def score_of(policy: Policy, values: dict[str, float]) -> float:
    """The points out of 100: a modality not in the test counts as saying nothing, half of its weight."""
    return 50 + 50 * sum(values.values()) / policy.budget


@dataclass(frozen=True)
class Part:
    modality: str
    algorithm: str
    score: float
    threshold: float
    compared: int
    evidence: float
    points: float

    def json(self, policy: Policy) -> dict:
        return {"modality": self.modality, "algorithm": self.algorithm, "score": self.score,
                "threshold": self.threshold, "accepted": self.score > self.threshold, "compared": self.compared,
                "evidence": self.evidence, "points": self.points, "weight": policy.weights[self.modality],
                "provisional": bool(policy.calibration[self.modality].get("provisional"))}


def _shown(piece: Part, policy: Policy, probes: dict[str, Any]) -> dict:
    """A part as the answer shows it, with the face's or the voice's new embedding for the result's rings: the
    caller's own sample, as the page that took it already holds it."""
    shown = piece.json(policy)
    if piece.modality in probes:
        shown["values"] = list(probes[piece.modality].embedding)
    return shown


def part(policy: Policy, modality: str, algorithm: str, score: float, threshold: float, compared: int) -> Part:
    value = evidence(policy, modality, score, compared)
    return Part(modality, algorithm, score, threshold, compared, value, points(policy, modality, value))


def method(databases: Databases, fingerprints, faces, voices) -> dict:
    """The combined test's card: its policy, where each calibration comes from, and which engines are set up."""
    policy = current_policy(databases)
    return {"policy": {"id": policy.id, "weights": policy.weights, "budget": policy.budget, "threshold": policy.threshold,
                       "calibration": {m: {"provisional": bool(c.get("provisional")), "origin": c.get("origin", "")}
                                       for m, c in policy.calibration.items()}},
            "available": {"fingerprint": fingerprints is not None, "face": faces is not None, "voice": voices is not None}}


def _others(databases: Databases, subject: uuid.UUID) -> dict[str, Enrolment | None]:
    return {name: embeddings.current_enrolment(databases, subject, name) for name in OTHERS}


def _check_samples(enrolled: dict[str, Enrolment | None], samples: dict[str, Taken | None]) -> list[str]:
    """The test's other modalities: every one the person enrolled, at least one, each with its sample, taken for
    this test."""
    names = [name for name in OTHERS if enrolled[name] is not None]
    if not names:
        raise FusionError("not_enough_modalities")  # H15: the client offers the enrolment
    now = datetime.now(UTC)
    for name in OTHERS:
        taken = samples[name]
        if (enrolled[name] is None) != (taken is None):
            raise FusionError("invalid_request")
        if taken is not None and (taken.at.tzinfo is None
                                  or not now - SAMPLE_AGE <= taken.at <= now + embeddings.CLOCK_SKEW):
            raise FusionError("sample_too_old")
    return names


def _take(modality: Modality, service: EngineService, databases: Databases, data: bytes) -> Any:
    """The new finding, checked and described by its engine of the pinned version (H48, H54)."""
    with Session(databases.biometric) as db:
        version = db.get_one(Algorithm, modality.algorithm).version
    if service.engine.start().get(modality.version_key) != version:
        raise modality.refusal("method_version_differs", 503)
    return modality.take(service, data, "device")


def _compare(modality: Modality, databases: Databases, enrolment_id: uuid.UUID, embedding: list[float]) -> tuple[float, float]:
    """The best of the enrolment's comparisons and the method's threshold, as verification compares (H49, H55)."""
    with Session(databases.biometric) as db:
        algorithm = db.get_one(Algorithm, modality.algorithm)
        rows = db.execute(COMPARISONS, {"probe": vector_text(embedding), "enrolment": enrolment_id,
                                        "algorithm": modality.algorithm}).all()
    if len(rows) != modality.per_enrolment:
        raise FusionError("enrolment_changed")
    if any(row.version != algorithm.version for row in rows):
        raise modality.refusal("method_version_differs", 503)
    return max(float(row.score) for row in rows), threshold_of(algorithm)


async def _samples(services: dict[str, EngineService | None], databases: Databases, names: list[str],
                   samples: dict[str, Taken | None], probes: dict[str, Any]) -> AsyncGenerator[dict, None]:
    """The face and the voice, checked before the scanner starts; a refused one ends the test unsaved."""
    for name in names:
        service, modality, taken = services[name], OTHERS[name], samples[name]
        if service is None:
            raise FusionError(f"{name}_unavailable")
        assert taken is not None  # _check_samples pairs every enrolled modality with its sample
        yield {"type": "checking_sample", "modality": name}
        probe = await run_in_threadpool(_take, modality, service, databases, taken.data)
        if not probe.passed:
            yield {"type": "sample_rejected", "modality": name, **modality.rejected(probe, "device")}
            return
        probes[name] = probe


def _component(subject: uuid.UUID, keys: Keys, fused: FusedAttempt, piece: Part, sealed: bytes, at: datetime,
               duration_ms: int, **target) -> Attempt:
    attempt = Attempt(id=uuid.uuid4(), at=at, subject_id=subject, modality=piece.modality, mode=fused.mode,
                      algorithm=piece.algorithm, score=piece.score, threshold=piece.threshold,
                      accepted=piece.score > piece.threshold, duration_ms=duration_ms, source="device",
                      fused_attempt_id=fused.id, evidence=piece.evidence, **target)
    attempt.probe = keyring.seal(keys, keyring.PROBE, attempt.id.bytes + subject.bytes, sealed)
    return attempt


async def _guarded(fingerprints: fp.FingerprintService, flow) -> AsyncGenerator[dict, None]:
    """The scanner's lock and the failures every combined test answers with, as fingerprint verification has them."""
    if not fingerprints.scanner_lock.acquire(blocking=False):
        yield {"type": "failed", "error": "scanner_busy"}
        return
    run = ScannerRun()
    try:
        async for event in flow(run):
            yield event
    except (FusionError, VerificationError, IdentificationError) as error:
        yield {"type": "failed", "error": str(error)}
    except ModalityError as error:
        yield {"type": "failed", "error": error.code}
    except ScannerError as error:
        yield {"type": "failed", "error": error.code}
    except EngineError:
        yield {"type": "failed", "error": "engine_unavailable"}
    except keyring.KeysError:
        yield {"type": "failed", "error": "stored_template_unreadable"}
    except Exception as error:
        logger.error("a combined test failed (%s)", type(error).__name__)
        yield {"type": "failed", "error": "unexpected"}
    finally:
        run.cancel()
        fingerprints.scanner_lock.release()


def verify(fingerprints: fp.FingerprintService, services: dict[str, EngineService | None], databases: Databases,
           keys: Keys, subject: uuid.UUID, finger: int, samples: dict[str, Taken | None]) -> AsyncGenerator[dict, None]:
    return _guarded(fingerprints, partial(_verify, fingerprints, services, databases, keys, subject, finger, samples))


async def _verify(fingerprints, services, databases, keys, subject, finger, samples, run) -> AsyncGenerator[dict, None]:
    policy = await run_in_threadpool(current_policy, databases)
    reference = await run_in_threadpool(verification._load, databases, keys, subject, finger, fp.OPENCV_SIFT)
    enrolled = await run_in_threadpool(_others, databases, subject)
    names = _check_samples(enrolled, samples)
    ids = {name: found.id for name, found in enrolled.items() if found is not None}
    yield {"type": "started", "mode": "verify", "finger": finger, "modalities": ["fingerprint", *names],
           "weights": policy.weights, "threshold": policy.threshold, "quality_minimum": fingerprints.quality_minimum}
    probes: dict[str, Any] = {}
    async for event in _samples(services, databases, names, samples, probes):
        yield event
    if len(probes) != len(names):
        return  # a refused face or voice: nothing is scanned or saved
    engine = fp.engine_for(fingerprints, fp.OPENCV_SIFT)
    assert engine is not None  # OpenCV SIFT is the fingerprint service's own engine
    if (await run_in_threadpool(engine.start))["version"] != reference.version:
        raise FusionError("template_version_mismatch")
    await run_in_threadpool(fingerprints.quality.start)
    capture = fp.NewCapture()
    async for event in fp.capture_new(fingerprints, run, capture, FusionError,
                                      lambda header, png: run_in_threadpool(fp.capture_quality, fingerprints, header, png)):
        yield event
    yield {"type": "comparing"}
    native = await run_in_threadpool(fp.extract_native, fingerprints, fp.OPENCV_SIFT, capture.png)
    scores = []
    for _, template in reference.templates:
        result, _ = await run_in_threadpool(engine.request, {"op": "compare"}, [native, template])
        scores.append(fp.comparison_score(result))
    parts = [part(policy, "fingerprint", fp.OPENCV_SIFT, max(scores), reference.threshold, len(scores))]
    for name in names:
        modality = OTHERS[name]
        best, threshold = await run_in_threadpool(_compare, modality, databases, ids[name], probes[name].embedding)
        parts.append(part(policy, name, modality.algorithm, best, threshold, modality.per_enrolment))
    values = {piece.modality: piece.evidence for piece in parts}
    score = score_of(policy, values)
    duration_ms = round((time.perf_counter() - capture.started) * 1000)
    yield {"type": "saving"}
    fused = await run_in_threadpool(_save_verification, databases, keys, subject, policy, reference.enrolment_id,
                                    ids, parts, score, capture,
                                    {name: OTHERS[name].sealed(probes[name]) for name in names}, duration_ms)
    yield {"type": "verified", "attempt_id": str(fused.id), "at": fused.at.isoformat(), "mode": "verify",
           "finger": finger, "score": score, "threshold": policy.threshold, "accepted": fused.accepted,
           "evidence": fused.evidence, "duration_ms": duration_ms, "policy": policy.id,
           "parts": [_shown(piece, policy, probes) for piece in parts]}


def _save_verification(databases: Databases, keys: Keys, subject: uuid.UUID, policy: Policy, finger_enrolment: uuid.UUID,
                       others: dict[str, uuid.UUID], parts: list[Part], score: float, capture: fp.NewCapture,
                       sealed: dict[str, bytes], duration_ms: int) -> FusedAttempt:
    at = capture.at
    total = sum(piece.evidence for piece in parts)
    fused = FusedAttempt(id=uuid.uuid4(), at=at, subject_id=subject, mode="verify", policy_id=policy.id,
                         fingerprint_enrolment_id=finger_enrolment, face_enrolment_id=others.get("face"),
                         voice_enrolment_id=others.get("voice"), score=score, threshold=policy.threshold,
                         accepted=score > policy.threshold, evidence=total, duration_ms=duration_ms)
    enrolments = {"fingerprint": finger_enrolment, **others}
    with Session(databases.biometric, expire_on_commit=False) as db, db.begin():
        # As H35: a deletion or a new enrolment of any compared modality since the start invalidates the test.
        locked = db.execute(select(Enrolment.id, Enrolment.subject_id, Enrolment.replaced_at).where(
            Enrolment.id.in_(list(enrolments.values()))).order_by(Enrolment.id).with_for_update()).all()
        if sorted(tuple(row) for row in locked) != sorted((e, subject, None) for e in enrolments.values()):
            raise FusionError("enrolment_changed")
        db.add(fused)
        db.flush()
        for piece in parts:
            data = capture.png if piece.modality == "fingerprint" else sealed[piece.modality]
            db.add(_component(subject, keys, fused, piece, data, at, duration_ms,
                              enrolment_id=enrolments[piece.modality]))
    return fused


def identify(fingerprints: fp.FingerprintService, services: dict[str, EngineService | None], databases: Databases,
             keys: Keys, subject: uuid.UUID, samples: dict[str, Taken | None]) -> AsyncGenerator[dict, None]:
    return _guarded(fingerprints, partial(_identify, fingerprints, services, databases, keys, subject, samples))


@dataclass(frozen=True)
class Galleries:
    fingerprint: identification.Gallery
    others: dict[str, embeddings.Gallery]
    people: list[uuid.UUID]  # the subjects enrolled in every modality of the test, in order


def _galleries(databases: Databases, keys: Keys, subject: uuid.UUID, names: list[str]) -> Galleries:
    """As H41 and H50 fix theirs, then kept to the people enrolled in every modality of the test."""
    prints = identification._load_gallery(databases, keys, subject, fp.OPENCV_SIFT)
    others = {}
    for name in names:
        modality = OTHERS[name]
        with Session(databases.biometric) as db:
            version = db.get_one(Algorithm, modality.algorithm).version
        others[name] = modality.search.gallery(databases, keys, subject, version)
    people = {candidate.subject_id for candidate in prints.candidates}
    for gallery in others.values():
        people &= {owner for _, owner in gallery.enrolments}
    kept = sorted(people)
    prints = replace(prints, owners=[o for o in prints.owners if o.subject_id in people],
                     candidates=[c for c in prints.candidates if c.subject_id in people])
    ids = {candidate.id for candidate in prints.candidates}
    prints.references = [r for r in prints.references if r.enrolment_id in ids]
    for name, gallery in others.items():
        enrolments = [(e, owner) for e, owner in gallery.enrolments if owner in people]
        chosen = {e for e, _ in enrolments}
        others[name] = embeddings.Gallery([o for o in gallery.owners if o.subject_id in people], enrolments,
                                          [row for row in gallery.rows if row[0] in chosen])
    return Galleries(prints, others, kept)


async def _identify(fingerprints, services, databases, keys, subject, samples, run) -> AsyncGenerator[dict, None]:
    policy = await run_in_threadpool(current_policy, databases)
    enrolled = await run_in_threadpool(_others, databases, subject)
    names = _check_samples(enrolled, samples)
    galleries = await run_in_threadpool(_galleries, databases, keys, subject, names)
    prints = galleries.fingerprint
    yield {"type": "started", "mode": "identify", "modalities": ["fingerprint", *names], "weights": policy.weights,
           "threshold": policy.threshold, "quality_minimum": fingerprints.quality_minimum,
           "people": len(galleries.people)}
    probes: dict[str, Any] = {}
    async for event in _samples(services, databases, names, samples, probes):
        yield event
    if len(probes) != len(names):
        return
    engines = fingerprints.search_engines(fp.OPENCV_SIFT)[:len(prints.references)]
    for engine in engines:
        if (await identification._engine_call(engine, engine.start))["version"] != prints.version:
            raise FusionError("template_version_mismatch")
    await identification._engine_call(fingerprints.quality, fingerprints.quality.start)
    capture = fp.NewCapture()
    async for event in fp.capture_new(fingerprints, run, capture, FusionError,
                                      partial(identification._quality, fingerprints)):
        yield event
    yield {"type": "searching"}
    probe = await identification._extract(fingerprints, fp.OPENCV_SIFT, capture.png)
    candidates = {candidate.id: candidate for candidate in prints.candidates}
    best_print = dict.fromkeys(candidates, 0)
    for offset in range(0, len(prints.references), len(engines)):
        batch = prints.references[offset:offset + len(engines)]
        results = await identification._compare_batch(engines, databases, keys, candidates, batch, probe)
        for reference, value in zip(batch, results, strict=True):
            best_print[reference.enrolment_id] = max(best_print[reference.enrolment_id], value)
    ranked_others = {}
    for name in names:
        modality = OTHERS[name]
        ranked = await run_in_threadpool(modality.search.rank, databases, galleries.others[name], probes[name].embedding)
        ranked_others[name] = {ranked.owner_of[row.enrolment_id]: row for row in ranked.rows}
    thresholds = await run_in_threadpool(_thresholds, databases, names)
    people = []
    for person in galleries.people:
        fingers = sorted((c for c in prints.candidates if c.subject_id == person),
                         key=lambda c: (-best_print[c.id], c.id))
        parts = [part(policy, "fingerprint", fp.OPENCV_SIFT, best_print[fingers[0].id], prints.threshold,
                      fp.PLACEMENTS * len(fingers))]
        tops = {"fingerprint": fingers[0].id}
        for name in names:
            row = ranked_others[name][person]
            parts.append(part(policy, name, OTHERS[name].algorithm, float(row.score), thresholds[name],
                              OTHERS[name].per_enrolment))
            tops[name] = row.enrolment_id
        people.append((score_of(policy, {p.modality: p.evidence for p in parts}), person, fingers[0], parts, tops))
    people.sort(key=lambda entry: (-entry[0], entry[1]))
    score, leader, finger, parts, tops = people[0]
    duration_ms = round((time.perf_counter() - capture.started) * 1000)
    yield {"type": "saving"}
    fused = await run_in_threadpool(_save_identification, databases, keys, subject, policy, galleries, parts, tops,
                                    score, capture, {name: OTHERS[name].sealed(probes[name]) for name in names},
                                    duration_ms)
    shown = people[:SHOWN_CANDIDATES]
    yield {"type": "identified", "attempt_id": str(fused.id), "at": fused.at.isoformat(), "mode": "identify",
           "score": score, "threshold": policy.threshold, "accepted": fused.accepted, "evidence": fused.evidence,
           "duration_ms": duration_ms, "policy": policy.id, "people": len(people),
           "tied_leaders": sum(entry[0] == score for entry in people),
           "leader": {"own": leader == subject, **({"finger": finger.finger} if leader == subject else {})},
           "parts": [_shown(piece, policy, probes) for piece in parts],
           "candidates": [{"rank": rank, "own": person == subject, "score": value, "accepted": value > policy.threshold,
                           **({"finger": top.finger} if person == subject else {}),
                           "points": {piece.modality: piece.points for piece in pieces}}
                          for rank, (value, person, top, pieces, _) in enumerate(shown, 1)]}


def _thresholds(databases: Databases, names: list[str]) -> dict[str, float]:
    with Session(databases.biometric) as db:
        return {name: threshold_of(db.get_one(Algorithm, OTHERS[name].algorithm)) for name in names}


def _save_identification(databases: Databases, keys: Keys, subject: uuid.UUID, policy: Policy, galleries: Galleries,
                         parts: list[Part], tops: dict[str, uuid.UUID], score: float, capture: fp.NewCapture,
                         sealed: dict[str, bytes], duration_ms: int) -> FusedAttempt:
    at = capture.at
    prints = galleries.fingerprint
    fused = FusedAttempt(id=uuid.uuid4(), at=at, subject_id=subject, mode="identify", policy_id=policy.id,
                         gallery_size=len(galleries.people), score=score, threshold=policy.threshold,
                         accepted=score > policy.threshold, evidence=sum(p.evidence for p in parts),
                         duration_ms=duration_ms)
    sizes = {"fingerprint": len(prints.references), **{n: len(g.rows) for n, g in galleries.others.items()}}
    # As H41 and H50: the accounts are locked first, then every enrolment of the galleries, and the test is saved only
    # while they are what they were at the start.
    with Session(databases.accounts) as accounts_db, accounts_db.begin():
        if not owners_unchanged(accounts_db, prints.owners):
            raise FusionError("gallery_changed")
        with Session(databases.biometric, expire_on_commit=False) as db, db.begin():
            expected = {(c.id, c.subject_id, None) for c in prints.candidates}
            for gallery in galleries.others.values():
                expected |= {(e, owner, None) for e, owner in gallery.enrolments}
            locked = db.execute(select(Enrolment.id, Enrolment.subject_id, Enrolment.replaced_at).where(
                Enrolment.id.in_([row[0] for row in expected])).order_by(Enrolment.id).with_for_update()).all()
            if {tuple(row) for row in locked} != expected or len(locked) != len(expected):
                raise FusionError("gallery_changed")
            if identification._reference_rows(db, [c.id for c in prints.candidates]) != prints.references:
                raise FusionError("gallery_changed")
            for name, gallery in galleries.others.items():
                if OTHERS[name].search._rows(db, [e for e, _ in gallery.enrolments]) != gallery.rows:
                    raise FusionError("gallery_changed")
            db.add(fused)
            db.flush()
            for piece in parts:
                data = capture.png if piece.modality == "fingerprint" else sealed[piece.modality]
                db.add(_component(subject, keys, fused, piece, data, at, duration_ms,
                                  top_enrolment_id=tops[piece.modality], gallery_size=sizes[piece.modality]))
    return fused
