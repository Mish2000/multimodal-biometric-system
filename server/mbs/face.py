"""Face enrolment (H17, H25, H48).

The camera belongs to the client: the page shows its live view, asks the server where the faces are
(`detect`), and sends the images the user takes. Every image passes the same checks here: exactly one face,
found by YuNet at its threshold, wholly inside the image and at least as wide as SFace's 112-pixel input.
Of the images that pass, the enrolment keeps three whose three pairs are all above SFace's threshold, as
H15 does for fingerprints; when no three do, the client takes another image, up to six. The images are
sealed like fingerprint captures, each bound to its row and its subject (H25); the embeddings are pgvector
values (H14), and every face score is pgvector's cosine similarity, the same computation for every face
comparison of the system.

The server keeps nothing between requests: the enrolment request carries the images again, and every
check is made anew on them.
"""

from __future__ import annotations

import base64
import itertools
import logging
import math
import struct
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import CursorResult, delete, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from . import keys as keyring
from .config import REPOSITORY, Config
from .db import Databases
from .engines import Engine, EngineError, conda_environment
from .fingerprint import best_three
from .keys import Keys
from .models import Algorithm, Attempt, Enrolment, Sample, Template, vector_text, vector_values

logger = logging.getLogger("mbs.face")
FACE = "face"
SFACE = "sface"
YUNET_MODEL = "face_detection_yunet_2023mar.onnx"
SFACE_MODEL = "face_recognition_sface_2021dec.onnx"
IMAGES = 3  # H17
MOST_KEPT = 6  # images that pass the checks, while looking for three that match each other (as H33)
SCORE_MINIMUM = 0.9  # YuNet's threshold in OpenCV Zoo's demo; the engine reports no weaker face
WIDTH_MINIMUM = 112  # SFace's aligned input, so no face is enlarged
EMBEDDING_LENGTH = 128  # read from the model by the engine (specification 5.2)
LIVE_BYTES = 1 << 20  # a frame of the live view, made small by the page
IMAGE_BYTES = 8 << 20  # a taken image: a PNG of the camera's frame
CAPTURE_AGE = timedelta(minutes=30)  # an enrolment's images were taken in the last half hour
CLOCK_SKEW = timedelta(minutes=1)


class FaceError(Exception):
    """A refused face request, answered as {"error": code, ...}."""

    def __init__(self, code: str, status: int = 422, **extra):
        super().__init__(code)
        self.code, self.status, self.extra = code, status, extra


@dataclass
class FaceService:
    engine: Engine

    def warm_up(self) -> None:
        """Start the engine in the background, so the first view of the camera does not wait for it."""
        def start():
            try:
                self.engine.start()
            except EngineError:
                pass  # reported when a request needs it
        threading.Thread(target=start, daemon=True).start()

    def close(self) -> None:
        self.engine.close()


def from_config(config: Config) -> tuple[FaceService | None, str]:
    """The service with this machine's face environment and models, or None and what is missing."""
    python, models = config.face_python, config.face_models
    missing = [name for name, ok in (
        ("face_python (the multimodal-face environment)", python and python.exists()),
        ("face_models with the two OpenCV Zoo models",
         models and (models / YUNET_MODEL).exists() and (models / SFACE_MODEL).exists()),
    ) if not ok]
    if missing:
        return None, "missing: " + ", ".join(missing)
    command = [str(python), "-I", str(REPOSITORY / "engines" / "face.py"), str(models)]
    return FaceService(Engine(FACE, command, conda_environment(python))), ""


def _db(engine) -> DbSession:
    return DbSession(engine, expire_on_commit=False)


def decode_image(data: str, limit: int) -> bytes:
    """An image sent in base64; its kind is decided by the engine from its content."""
    try:
        image = base64.b64decode(data, validate=True)
    except ValueError:
        raise FaceError("invalid_image") from None
    if not image or len(image) > limit:
        raise FaceError("invalid_image")
    return image


def _number(value, low: float = -math.inf, high: float = math.inf) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise EngineError("invalid face geometry")
    return float(value)


def _faces(reply: dict) -> tuple[int, int, list[dict]]:
    """The engine's answer, checked before anything uses it."""
    if "invalid" in reply:
        raise FaceError("invalid_image")  # not an image, or too many pixels
    width, height, faces = reply.get("width"), reply.get("height"), reply.get("faces")
    if type(width) is not int or type(height) is not int or width < 1 or height < 1 or not isinstance(faces, list):
        raise EngineError("invalid face reply")
    checked = []
    for face in faces:
        if not isinstance(face, dict) or len(face.get("box", ())) != 4 or len(face.get("landmarks", ())) != 5:
            raise EngineError("invalid face reply")
        checked.append({"box": [_number(v) for v in face["box"]],
                        "landmarks": [[_number(x), _number(y)] for x, y in face["landmarks"]],
                        "score": _number(face.get("score"), 0, 1)})
    return width, height, checked


def _check(name: str, passed: bool, detail: str, **extra) -> dict:
    return {"name": name, "passed": passed, "detail": detail, **extra}


def checks_for(width: int, height: int, faces: list[dict]) -> list[dict]:
    """The checks of one image (H48); the later ones need exactly one face."""
    count = len(faces)
    found = [_check("one_face", count == 1, f"{count} faces found, exactly 1 needed", count=count)]
    if count != 1:
        return found
    x, y, w, h = faces[0]["box"]
    score = faces[0]["score"]
    inside = x >= 0 and y >= 0 and x + w <= width and y + h <= height
    return found + [
        _check("detector_score", score >= SCORE_MINIMUM, f"YuNet score {score:.3f}, at least {SCORE_MINIMUM}",
               score=round(score, 4), minimum=SCORE_MINIMUM),
        _check("inside", inside, "the whole face is inside the image" if inside else "part of the face is outside the image"),
        _check("face_size", w >= WIDTH_MINIMUM, f"the face is {w:.0f} pixels wide, at least {WIDTH_MINIMUM}",
               width=round(w, 1), minimum=WIDTH_MINIMUM),
    ]


@dataclass
class Extracted:
    width: int
    height: int
    faces: list[dict]
    checks: list[dict]
    png: bytes | None = None  # the image again, made by the engine from its pixels alone
    aligned: bytes | None = None  # SFace's 112 x 112 input
    embedding: list[float] | None = None

    @property
    def passed(self) -> bool:
        return all(check["passed"] for check in self.checks)


def _extract(service: FaceService, image: bytes) -> Extracted:
    reply, parts = service.engine.request({"op": "extract"}, [image])
    width, height, faces = _faces(reply)
    found = Extracted(width, height, faces, checks_for(width, height, faces))
    if len(faces) != 1:
        return found
    if reply.get("embedding_length") != EMBEDDING_LENGTH or len(parts) != 3 or len(parts[2]) != 4 * EMBEDDING_LENGTH:
        raise EngineError("invalid face embedding")
    embedding = list(struct.unpack(f"<{EMBEDDING_LENGTH}f", parts[2]))
    if not all(math.isfinite(v) for v in embedding) or not any(embedding) or not parts[0] or not parts[1]:
        raise EngineError("invalid face embedding")
    found.png, found.aligned, found.embedding = parts[0], parts[1], embedding
    return found


def _b64(data: bytes | None) -> str | None:
    return None if data is None else base64.b64encode(data).decode("ascii")


def detect(service: FaceService, image: bytes) -> dict:
    """Where the faces of one live frame are, for the box drawn over the camera's view; nothing is kept."""
    reply, _ = service.engine.request({"op": "detect"}, [image])
    width, height, faces = _faces(reply)
    return {"width": width, "height": height, "faces": faces}


def check(service: FaceService, image: bytes) -> dict:
    """One taken image's checks and its aligned face, for the page to show at once; nothing is kept."""
    found = _extract(service, image)
    return {"width": found.width, "height": found.height, "faces": found.faces, "checks": found.checks,
            "passed": found.passed, "aligned": _b64(found.aligned) if found.passed else None}


def method(databases: Databases, service: FaceService | None) -> dict:
    """SFace's card and the rules of a face enrolment."""
    with _db(databases.biometric) as db:
        algorithm = db.get(Algorithm, SFACE)
    return {"code": SFACE, "threshold": algorithm.threshold, "threshold_provisional": algorithm.threshold_provisional,
            "threshold_origin": algorithm.threshold_origin, "available": service is not None,
            "images": IMAGES, "most_kept": MOST_KEPT, "score_minimum": SCORE_MINIMUM, "width_minimum": WIDTH_MINIMUM,
            "embedding_length": EMBEDDING_LENGTH}


def similarity(db: DbSession, a: list[float], b: list[float]) -> float:
    """pgvector's cosine similarity of two embeddings: one minus its cosine distance."""
    return float(db.scalar(text("SELECT 1 - (CAST(:a AS vector) <=> CAST(:b AS vector))"),
                           {"a": vector_text(a), "b": vector_text(b)}))


def current_enrolment(databases: Databases, subject: uuid.UUID) -> Enrolment | None:
    with _db(databases.biometric) as db:
        return db.scalar(select(Enrolment).where(Enrolment.subject_id == subject, Enrolment.modality == FACE,
                                                 Enrolment.replaced_at.is_(None)))


def enrol(service: FaceService, databases: Databases, keys: Keys, subject: uuid.UUID,
          images: list[tuple[bytes, datetime]]) -> dict:
    """The images taken so far, in the order they were taken: saved when three of them match each other,
    otherwise the client is asked for another image, until six have passed the checks."""
    if not IMAGES <= len(images) <= MOST_KEPT:
        raise FaceError("invalid_request")
    now = datetime.now(timezone.utc)
    times = [taken for _, taken in images]
    if any(taken.tzinfo is None or not now - CAPTURE_AGE <= taken <= now + CLOCK_SKEW for taken in times) \
            or times != sorted(times):
        raise FaceError("invalid_request")
    with _db(databases.biometric) as db:
        algorithm = db.get(Algorithm, SFACE)
        version, threshold = algorithm.version, algorithm.threshold
    if service.engine.start().get("sface_sha256") != version:
        raise FaceError("method_version_differs", 503)
    found = []
    for index, (image, _) in enumerate(images):
        extracted = _extract(service, image)
        if not extracted.passed:
            raise FaceError("image_rejected", index=index, checks=extracted.checks)
        found.append(extracted)
    scores: dict[tuple[int, int], float] = {}
    with _db(databases.biometric) as db:
        for a, b in itertools.combinations(range(len(found)), 2):
            scores[(a, b)] = similarity(db, found[b].embedding, found[a].embedding)
    pairs = [{"probe": b + 1, "reference": a + 1, "score": score, "accepted": score > threshold}
             for (a, b), score in scores.items()]
    trio = best_three(found, scores, threshold)
    if trio is None:
        status = "failed" if len(found) >= MOST_KEPT else "another"
        return {"status": status, **({"error": "images_do_not_match"} if status == "failed" else {}),
                "pairs": pairs, "threshold": threshold, "kept": len(found)}
    chosen = [(index + 1, found[index], times[index]) for index in trio]
    enrolment, replaced, samples, templates = _save(databases, keys, subject, chosen, version)
    return {
        "status": "saved",
        "enrolment": {"id": str(enrolment.id), "created_at": enrolment.created_at.isoformat(),
                      "replaced_previous": replaced},
        "samples": [{"id": str(sample.id), "placement": sample.placement, "captured_at": sample.captured_at.isoformat(),
                     "width": sample.width, "height": sample.height, "sealed_length": len(sample.data),
                     "aligned": _b64(extracted.aligned)}
                    for sample, (_, extracted, _) in zip(samples, chosen)],
        "templates": [{"id": str(template.id), "sample_id": str(template.sample_id), "algorithm": SFACE,
                       "version": version, "embedding_length": EMBEDDING_LENGTH} for template in templates],
        "pairs": [pair for pair in pairs if pair["reference"] - 1 in trio and pair["probe"] - 1 in trio],
        "threshold": threshold,
        "not_kept": [index + 1 for index in range(len(found)) if index not in trio],
    }


def _save(databases: Databases, keys: Keys, subject: uuid.UUID, chosen: list[tuple[int, Extracted, datetime]],
          version: str) -> tuple[Enrolment, bool, list[Sample], list[Template]]:
    now = datetime.now(timezone.utc)
    try:
        with _db(databases.biometric) as db, db.begin():
            result: CursorResult = db.execute(update(Enrolment).where(
                Enrolment.subject_id == subject, Enrolment.modality == FACE, Enrolment.replaced_at.is_(None)
            ).values(replaced_at=now))
            enrolment = Enrolment(id=uuid.uuid4(), subject_id=subject, modality=FACE, finger=None, created_at=now)
            db.add(enrolment)
            db.flush()
            samples, templates = [], []
            for placement, extracted, taken in chosen:
                sample = Sample(id=uuid.uuid4(), enrolment_id=enrolment.id, placement=placement, captured_at=taken,
                                media_type="image/png", width=extracted.width, height=extracted.height,
                                checks=extracted.checks)
                sample.data = keyring.seal(keys, keyring.SAMPLE, sample.id.bytes + subject.bytes, extracted.png)
                db.add(sample)
                db.flush()
                template = Template(id=uuid.uuid4(), sample_id=sample.id, algorithm=SFACE, version=version,
                                    created_at=now, embedding=extracted.embedding)
                db.add(template)
                samples.append(sample)
                templates.append(template)
    except IntegrityError:
        raise FaceError("enrolment_busy", 409) from None  # another face enrolment of this person ended first
    return enrolment, result.rowcount > 0, samples, templates


def delete_face(databases: Databases, subject: uuid.UUID) -> bool:
    """As H34 for a finger: the face enrolment and those it replaced are erased with their sealed images and
    embeddings; False when the face is not enrolled."""
    with _db(databases.biometric) as db, db.begin():
        rows = db.execute(select(Enrolment.id, Enrolment.replaced_at).where(
            Enrolment.subject_id == subject, Enrolment.modality == FACE
        ).order_by(Enrolment.id).with_for_update()).all()
        if not any(replaced_at is None for _, replaced_at in rows):
            return False
        enrolments = [enrolment_id for enrolment_id, _ in rows]
        samples = select(Sample.id).where(Sample.enrolment_id.in_(enrolments))
        db.execute(delete(Template).where(Template.sample_id.in_(samples)))
        db.execute(delete(Sample).where(Sample.enrolment_id.in_(enrolments)))
        db.execute(delete(Enrolment).where(Enrolment.id.in_(enrolments)))
    return True


# Face verification (H49): one taken image against the caller's current face enrolment, as H35 does for a
# finger. The highest of the three cosine similarities decides, strictly above the threshold, and equal
# scores go to the earliest image (H43). A rejected image makes no attempt; a completed comparison is saved,
# match or not, with its image sealed, and the answer is sent only after that.

COMPARISONS = """
SELECT s.id AS sample_id, s.placement, t.version, t.embedding::text AS embedding,
       1 - (t.embedding <=> CAST(:probe AS vector)) AS score
FROM template t JOIN sample s ON s.id = t.sample_id
WHERE s.enrolment_id = :enrolment AND t.algorithm = 'sface'
ORDER BY s.placement
"""


def _repeat_view(service: FaceService, keys: Keys, databases: Databases, subject: uuid.UUID, sample_id: uuid.UUID,
                 stored: list[float]) -> bytes:
    """The aligned face of the caller's own winning image, for the result screen: the sealed image is opened for
    its owner only and extracted again, and the repeated embedding must equal the stored one."""
    with _db(databases.biometric) as db:
        sample = db.get(Sample, sample_id)
    png = keyring.open_sealed(keys, keyring.SAMPLE, sample.id.bytes + subject.bytes, sample.data)
    again = _extract(service, png)
    if not again.passed or again.embedding is None or vector_values(vector_text(again.embedding)) != stored:
        raise EngineError("the stored face did not give its stored embedding again")
    return again.aligned


def verify(service: FaceService, databases: Databases, keys: Keys, subject: uuid.UUID, image: bytes) -> dict:
    at = datetime.now(timezone.utc)
    started = time.perf_counter()
    with _db(databases.biometric) as db:
        algorithm = db.get(Algorithm, SFACE)
        version, threshold = algorithm.version, algorithm.threshold
        origin, provisional = algorithm.threshold_origin, algorithm.threshold_provisional
    enrolment = current_enrolment(databases, subject)
    if enrolment is None:
        raise FaceError("not_enrolled", 409)  # H15: the client offers the enrolment
    if service.engine.start().get("sface_sha256") != version:
        raise FaceError("method_version_differs", 503)
    probe = _extract(service, image)
    if not probe.passed:
        return {"status": "rejected", "width": probe.width, "height": probe.height, "faces": probe.faces,
                "checks": probe.checks}
    with _db(databases.biometric) as db:
        rows = db.execute(text(COMPARISONS), {"probe": vector_text(probe.embedding), "enrolment": enrolment.id}).all()
    if len(rows) != IMAGES:
        raise FaceError("enrolment_changed", 409)
    if any(row.version != version for row in rows):
        raise FaceError("method_version_differs", 503)
    comparisons = [{"placement": row.placement, "score": float(row.score), "accepted": float(row.score) > threshold}
                   for row in rows]
    best = sorted(rows, key=lambda row: (-float(row.score), row.placement))[0]
    score = float(best.score)
    duration_ms = round((time.perf_counter() - started) * 1000)  # receipt through the comparisons (H35)
    reference = _repeat_view(service, keys, databases, subject, best.sample_id, vector_values(best.embedding))
    attempt = Attempt(id=uuid.uuid4(), at=at, subject_id=subject, modality=FACE, mode="verify", algorithm=SFACE,
                      enrolment_id=enrolment.id, score=score, threshold=threshold, accepted=score > threshold,
                      duration_ms=duration_ms, source="device")
    attempt.probe = keyring.seal(keys, keyring.PROBE, attempt.id.bytes + subject.bytes, probe.png)
    with _db(databases.biometric) as db, db.begin():
        # A deletion or a new enrolment since the comparison invalidates it (H35); a later deletion cascades.
        locked = db.scalar(select(Enrolment).where(Enrolment.id == enrolment.id, Enrolment.subject_id == subject)
                           .with_for_update())
        if locked is None or locked.replaced_at is not None:
            raise FaceError("enrolment_changed", 409)
        db.add(attempt)
    return {"status": "verified", "attempt_id": str(attempt.id), "at": at.isoformat(), "score": score,
            "threshold": threshold, "threshold_origin": origin, "threshold_provisional": provisional,
            "accepted": attempt.accepted, "duration_ms": duration_ms, "comparisons": comparisons,
            "view": {"placement": best.placement, "probe": _b64(probe.aligned), "reference": _b64(reference)}}
