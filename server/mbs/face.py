"""Face enrolment (H17, H25, H48), verification (H49) and identification (H50).

The camera belongs to the client: the page shows its live view, asks the server where the faces are
(`detect`), and sends the images the user takes. Every image passes the same checks here: exactly one face,
found by YuNet at its threshold, wholly inside the image and at least as wide as SFace's 112-pixel input.
Of the images that pass, the enrolment keeps three whose three pairs are all above SFace's threshold, as
H15 does for fingerprints; when no three do, the client takes another image, up to six. The images are
sealed like fingerprint captures, each bound to its row and its subject (H25); the embeddings are pgvector
values (H14), and every face score is pgvector's cosine similarity, the same computation for every face
comparison of the system.

The server keeps nothing between requests: the enrolment request carries the images again, and every
check is made anew on them. Enrolment, verification, identification and deletion are the flows the face
shares with the voice (mbs/embeddings.py); this module holds the face's own steps: the engine's answers,
the checks of an image and of an image file, and what of an image is sealed and shown.
"""

from __future__ import annotations

import logging
import math
import struct
import uuid
from dataclasses import dataclass
from datetime import datetime

from . import embeddings
from .config import REPOSITORY, Config
from .db import Databases
from .embeddings import EngineService, Modality, ModalityError, base64_text, card, decode
from .embeddings import check as _check
from .engines import Engine, EngineError, conda_environment
from .keys import Keys
from .models import Enrolment, Sample

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
FILE_BYTES = 10 << 20  # H27: an image file, for 1:1 and 1:N only
SHORT_SIDE_MINIMUM = 240  # H27: a file's shorter side, in pixels
MAX_PIXELS = 50_000_000  # H27: a file's largest image; the engine refuses more too
SOURCES = ("device", "file")


class FaceError(ModalityError):
    """A refused face request, answered as {"error": code, ...}."""


class FaceService(EngineService):
    """The face engine (H48), started in the background, so the first view of the camera does not wait for it."""


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


def decode_image(data: str, limit: int) -> bytes:
    """An image sent in base64; its kind is decided by the engine from its content."""
    return decode(data, limit, FaceError, "invalid_image")


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
    decoded: list[int] | None = None  # the image's own size, the frame of its boxes (H51, H52)
    stored: list[int] | None = None  # the copy that is stored: the image, or one scaled down to 1920 (H51)

    @property
    def passed(self) -> bool:
        return all(check["passed"] for check in self.checks)


JPEG_START, PNG_START = b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n"
JPEG_FRAMES = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def file_header(data: bytes) -> tuple[str, int, int] | None:
    """A file's kind and its width and height, read from its header alone, before anything decodes it (H27,
    H51): a JPEG's frame header or a PNG's IHDR chunk. Anything else, or a header that cannot be read, is None."""
    if data.startswith(PNG_START) and len(data) >= 24 and data[12:16] == b"IHDR":
        return "PNG", int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if not data.startswith(JPEG_START):
        return None
    index = 2
    while index + 4 <= len(data):
        if data[index] != 0xFF:
            return None
        marker = data[index + 1]
        if marker == 0xFF:  # a fill byte
            index += 1
            continue
        if marker == 0x01 or 0xD0 <= marker <= 0xD8:  # markers without a length
            index += 2
            continue
        if marker == 0xDA:  # the image data begins before any frame header
            return None
        if marker in JPEG_FRAMES:
            if index + 9 > len(data):
                return None
            return "JPEG", int.from_bytes(data[index + 7:index + 9], "big"), int.from_bytes(data[index + 5:index + 7], "big")
        index += 2 + int.from_bytes(data[index + 2:index + 4], "big")
    return None


def file_checks(data: bytes) -> tuple[list[dict], list[int]]:
    """H51: the checks of an image file before the engine decodes it; its EXIF orientation changes neither."""
    header = file_header(data)
    if header is None:
        return [_check("file_type", False, "a JPEG or PNG image is needed")], [0, 0]
    kind, width, height = header
    fits = min(width, height) >= SHORT_SIDE_MINIMUM and width * height <= MAX_PIXELS
    return [_check("file_type", True, f"a {kind} image", kind=kind),
            _check("image_size", fits, f"{width} x {height} pixels: at least {SHORT_SIDE_MINIMUM} on the shorter side "
                   f"and at most {MAX_PIXELS:,} in all", width=width, height=height, minimum=SHORT_SIDE_MINIMUM,
                   maximum=MAX_PIXELS)], [width, height]


def _extract(service: FaceService, image: bytes) -> Extracted:
    reply, parts = service.engine.request({"op": "extract"}, [image])
    width, height, faces = _faces(reply)
    decoded, stored = reply.get("decoded", [width, height]), reply.get("stored", [width, height])
    if not all(isinstance(size, list) and len(size) == 2 and all(type(v) is int and v > 0 for v in size)
               for size in (decoded, stored)):
        raise EngineError("invalid face reply")
    found = Extracted(width, height, faces, checks_for(width, height, faces), decoded=decoded, stored=stored)
    if len(faces) != 1:
        return found
    if reply.get("embedding_length") != EMBEDDING_LENGTH or len(parts) != 3 or len(parts[2]) != 4 * EMBEDDING_LENGTH:
        raise EngineError("invalid face embedding")
    embedding = list(struct.unpack(f"<{EMBEDDING_LENGTH}f", parts[2]))
    if not all(math.isfinite(v) for v in embedding) or not any(embedding) or not parts[0] or not parts[1]:
        raise EngineError("invalid face embedding")
    found.png, found.aligned, found.embedding = parts[0], parts[1], embedding
    return found


def detect(service: FaceService, image: bytes) -> dict:
    """Where the faces of one live frame are, for the box drawn over the camera's view; nothing is kept."""
    reply, _ = service.engine.request({"op": "detect"}, [image])
    width, height, faces = _faces(reply)
    return {"width": width, "height": height, "faces": faces}


def check(service: FaceService, image: bytes) -> dict:
    """One taken image's checks and its aligned face, for the page to show at once; nothing is kept."""
    found = _extract(service, image)
    return {"width": found.width, "height": found.height, "faces": found.faces, "checks": found.checks,
            "passed": found.passed, "aligned": base64_text(found.aligned) if found.passed else None}


def method(databases: Databases, service: FaceService | None) -> dict:
    """SFace's card and the rules of a face enrolment."""
    return {**card(databases, SFACE, service), "images": IMAGES, "most_kept": MOST_KEPT,
            "score_minimum": SCORE_MINIMUM, "width_minimum": WIDTH_MINIMUM, "embedding_length": EMBEDDING_LENGTH}


def current_enrolment(databases: Databases, subject: uuid.UUID) -> Enrolment | None:
    return embeddings.current_enrolment(databases, subject, FACE)


def enrol(service: FaceService, databases: Databases, keys: Keys, subject: uuid.UUID,
          images: list[tuple[bytes, datetime]]) -> dict:
    """The images taken so far, in the order they were taken: saved when three of them match each other,
    otherwise the client is asked for another image, until six have passed the checks."""
    return embeddings.enrol(FACES, service, databases, keys, subject, images)


def _save(databases: Databases, keys: Keys, subject: uuid.UUID, chosen: list[tuple[int, Extracted, datetime]],
          version: str) -> tuple[Enrolment, bool, list[Sample], list]:
    return embeddings.save(FACES, databases, keys, subject, chosen, version)


def delete_face(databases: Databases, subject: uuid.UUID) -> bool:
    """As H34 for a finger: the face enrolment and those it replaced are erased with their sealed images and
    embeddings; False when the face is not enrolled."""
    return embeddings.delete_enrolments(databases, subject, FACE)


def _take(service: FaceService, image: bytes, source: str) -> Extracted:
    """The new image of a verification or an identification: from the camera, or from a file (H27, H51), whose
    own checks come first and keep a refused file from the engine."""
    if source not in SOURCES:
        raise FaceError("invalid_request")
    checks: list[dict] = []
    if source == "file":
        checks, size = file_checks(image)
        if not all(check["passed"] for check in checks):
            return Extracted(size[0], size[1], [], checks, decoded=size, stored=size)
    probe = _extract(service, image)
    probe.checks = checks + probe.checks
    return probe


def _rejected(probe: Extracted, source: str) -> dict:
    return {"status": "rejected", "source": source, "width": probe.width, "height": probe.height,
            "faces": probe.faces, "checks": probe.checks}


def _size(probe: Extracted) -> dict:
    return {"decoded": probe.decoded, "stored": probe.stored}


def _repeat_view(service: FaceService, keys: Keys, databases: Databases, subject: uuid.UUID, sample_id: uuid.UUID,
                 stored: list[float]) -> bytes:
    """The aligned face of the caller's own winning image, for the result screen (H49)."""
    return embeddings.repeat_view(FACES, service, keys, databases, subject, sample_id, stored)


def verify(service: FaceService, databases: Databases, keys: Keys, subject: uuid.UUID, image: bytes,
           source: str = "device") -> dict:
    """H49: one taken image against the caller's current face enrolment, as H35 does for a finger."""
    return embeddings.verify(FACES, service, databases, keys, subject, image, source)


def identify(service: FaceService, databases: Databases, keys: Keys, subject: uuid.UUID, image: bytes,
             source: str = "device") -> dict:
    """H50: one taken image against every current face enrolment of the active user accounts, as H41 does for
    fingerprints."""
    return embeddings.identify(FACES, service, databases, keys, subject, image, source)


def _sample_json(sample: Sample, found: Extracted) -> dict:
    return {"id": str(sample.id), "placement": sample.placement, "captured_at": sample.captured_at.isoformat(),
            "width": sample.width, "height": sample.height, "sealed_length": len(sample.data),
            "aligned": base64_text(found.aligned)}


FACES = Modality(
    name=FACE, algorithm=SFACE, version_key="sface_sha256", per_enrolment=IMAGES, most_kept=MOST_KEPT,
    embedding_length=EMBEDDING_LENGTH, noun="image", refusal=FaceError,
    extract=lambda service, image: _extract(service, image),
    take=lambda service, image, source: _take(service, image, source),
    rejected=lambda probe, source: _rejected(probe, source),
    sealed=lambda found: found.png,
    sample_fields=lambda found: {"media_type": "image/png", "width": found.width, "height": found.height,
                                 "checks": found.checks},
    sample_json=lambda sample, found: _sample_json(sample, found),
    shown=lambda image, again: again.aligned,
    origin=lambda probe, source: {"source": source, "size": _size(probe)},
    view=lambda probe, reference: {"probe": base64_text(probe.aligned), "reference": base64_text(reference)},
    repeat_view=lambda *args: _repeat_view(*args),
)
