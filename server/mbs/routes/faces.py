"""The face routes (H48 to H53). The page owns the camera: it asks where the faces of its live view are, has each
taken image checked at once, then sends the images that passed to be enrolled; the server keeps nothing between
these requests and checks everything again before it saves. Verification and identification take one image from the
camera or a file (H27, H51)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .. import accounts, face
from ..accounts import AccountError, SignedIn
from ..engines import EngineError
from ..face import FaceError, FaceService
from ..models import USER
from .common import JSON_AROUND, DatabasesDep, KeysDep, base64_length
from .policy import allow, signed_in

router = APIRouter()


async def _faces(request: Request) -> FaceService | None:
    return request.app.state.faces


FacesDep = Annotated[FaceService | None, Depends(_faces)]


def available(service: FaceService | None) -> FaceService:
    if service is None:
        raise FaceError("face_unavailable", 503)
    return service


def engine_work(work):
    """H48: an engine that cannot answer is the server's failure, reported without the image."""
    try:
        return work()
    except EngineError:
        face.logger.warning("the face engine failed a request")
        raise FaceError("engine_unavailable", 503) from None


class FaceFrame(BaseModel):
    """A frame of the camera's live view (H48), made small by the page, in base64."""
    model_config = {"extra": "forbid"}
    image: str = Field(max_length=base64_length(face.LIVE_BYTES))


class FaceImage(BaseModel):
    """An image the user took, as a PNG of the camera's frame, in base64 (H48)."""
    model_config = {"extra": "forbid"}
    image: str = Field(max_length=base64_length(face.IMAGE_BYTES))


class FaceProbe(BaseModel):
    """The new image of a verification or identification (H49, H50): a PNG of the camera's frame, or the content
    of a JPEG or PNG file (H27, H51), in base64. Enrolment and the live checks take no files."""
    model_config = {"extra": "forbid"}
    image: str = Field(max_length=base64_length(face.FILE_BYTES))
    source: Literal["device", "file"] = "device"

    def data(self) -> bytes:
        return face.decode_image(self.image, face.FILE_BYTES if self.source == "file" else face.IMAGE_BYTES)


class FaceTaken(FaceImage):
    captured_at: datetime


class FaceEnrolment(BaseModel):
    model_config = {"extra": "forbid"}
    images: list[FaceTaken] = Field(min_length=face.IMAGES, max_length=face.MOST_KEPT)


# H58: these routes may receive bodies exactly as large as their models allow, with room for the JSON around each image.
BODY_LIMITS = {
    "/api/face/detect": base64_length(face.LIVE_BYTES) + JSON_AROUND,
    "/api/face/checks": base64_length(face.IMAGE_BYTES) + JSON_AROUND,
    "/api/face/enrolments": face.MOST_KEPT * (base64_length(face.IMAGE_BYTES) + JSON_AROUND),
    "/api/face/verifications": base64_length(face.FILE_BYTES) + JSON_AROUND,
    "/api/face/identifications": base64_length(face.FILE_BYTES) + JSON_AROUND,
}


@router.get("/api/face/method")
@allow(USER)
def face_method(databases: DatabasesDep, faces: FacesDep) -> dict:
    return face.method(databases, faces)


@router.post("/api/face/detect")
@allow(USER)
def detect_face(body: FaceFrame, faces: FacesDep) -> dict:
    service = available(faces)
    image = face.decode_image(body.image, face.LIVE_BYTES)
    return engine_work(lambda: face.detect(service, image))


@router.post("/api/face/checks")
@allow(USER)
def check_face(body: FaceImage, faces: FacesDep) -> dict:
    service = available(faces)
    image = face.decode_image(body.image, face.IMAGE_BYTES)
    return engine_work(lambda: face.check(service, image))


@router.post("/api/face/enrolments")
@allow(USER)
def enrol_face(body: FaceEnrolment, databases: DatabasesDep, keys: KeysDep, faces: FacesDep,
               account: SignedIn = Depends(signed_in)) -> JSONResponse:
    service = available(faces)
    images = [(face.decode_image(taken.image, face.IMAGE_BYTES), taken.captured_at) for taken in body.images]
    subject = accounts.subject_of(databases, keys, account.id)
    result = engine_work(lambda: face.enrol(service, databases, keys, subject, images))
    return JSONResponse(result, status_code=201 if result["status"] == "saved" else 200)


# H49: one taken image against the caller's current face enrolment; a completed comparison is saved with
# its sealed image before the answer, a rejected image is not.
@router.post("/api/face/verifications")
@allow(USER)
def verify_face(body: FaceProbe, databases: DatabasesDep, keys: KeysDep, faces: FacesDep,
                account: SignedIn = Depends(signed_in)) -> dict:
    service = available(faces)
    image = body.data()
    subject = accounts.subject_of(databases, keys, account.id)
    return engine_work(lambda: face.verify(service, databases, keys, subject, image, body.source))


# H50: one taken image against every current face enrolment of the active users. A completed search is saved
# with its sealed image before the answer, a rejected image is not; other users stay anonymous (H18).
@router.post("/api/face/identifications")
@allow(USER)
def identify_face(body: FaceProbe, databases: DatabasesDep, keys: KeysDep, faces: FacesDep,
                  account: SignedIn = Depends(signed_in)) -> dict:
    service = available(faces)
    image = body.data()
    subject = accounts.subject_of(databases, keys, account.id)
    return engine_work(lambda: face.identify(service, databases, keys, subject, image, body.source))


# As H34 for a finger: the face's enrolment is erased with its images and embeddings, and (H49) with its
# verification attempts and their sealed images; identification attempts stay, without the link (H41, H50).
@router.delete("/api/face/enrolment", status_code=204)
@allow(USER)
def delete_face(databases: DatabasesDep, keys: KeysDep, account: SignedIn = Depends(signed_in)) -> None:
    subject = accounts.subject_of(databases, keys, account.id)
    if not face.delete_face(databases, subject):
        raise AccountError("not_enrolled", 404)
