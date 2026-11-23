"""The combined test's routes (H60): its card, and 1:1 and 1:N with the scanner's progress streamed as JSON lines, as
the fingerprint's routes stream theirs. The page sends the face image and the voice recording it took for the test;
the scan comes last."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .. import accounts, face, fusion, voice
from ..accounts import AccountError
from ..models import USER
from .common import JSON_AROUND, DatabasesDep, KeysDep, base64_length
from .faces import FacesDep
from .fingerprints import FingerprintResponse, FingerprintsDep
from .policy import SignedInDep, allow
from .voices import VoicesDep

router = APIRouter()


class FusionFace(BaseModel):
    """The camera's image taken for this test, a PNG in base64 (H48), and when it was taken."""
    model_config = {"extra": "forbid"}
    image: str = Field(max_length=base64_length(face.IMAGE_BYTES))
    captured_at: datetime


class FusionVoice(BaseModel):
    """The microphone's recording taken for this test, a WAV in base64 (H54), and when it was taken."""
    model_config = {"extra": "forbid"}
    recording: str = Field(max_length=base64_length(voice.RECORDING_BYTES))
    captured_at: datetime


class FusionIdentification(BaseModel):
    model_config = {"extra": "forbid"}
    face: FusionFace | None = None
    voice: FusionVoice | None = None

    def samples(self) -> dict[str, fusion.Taken | None]:
        return {
            "face": fusion.Taken(face.decode_image(self.face.image, face.IMAGE_BYTES), self.face.captured_at)
            if self.face else None,
            "voice": fusion.Taken(voice.decode_recording(self.voice.recording, voice.RECORDING_BYTES),
                                  self.voice.captured_at) if self.voice else None,
        }


class FusionVerification(FusionIdentification):
    finger: int = Field(ge=1, le=10)  # the enrolled finger to place, as fingerprint verification has it (H35)


# H58: the two routes may receive one image and one recording, with room for the JSON around each.
BODY_LIMITS = {
    route: base64_length(face.IMAGE_BYTES) + base64_length(voice.RECORDING_BYTES) + 2 * JSON_AROUND
    for route in ("/api/fusion/verifications", "/api/fusion/identifications")
}


@router.get("/api/fusion/method")
@allow(USER)
def fusion_method(databases: DatabasesDep, fingerprints: FingerprintsDep, faces: FacesDep, voices: VoicesDep) -> dict:
    return fusion.method(databases, fingerprints, faces, voices)


@router.post("/api/fusion/verifications")
@allow(USER)
async def verify_fused(body: FusionVerification, databases: DatabasesDep, keys: KeysDep, fingerprints: FingerprintsDep,
                       faces: FacesDep, voices: VoicesDep, account: SignedInDep) -> StreamingResponse:
    if fingerprints is None:
        raise AccountError("fingerprint_unavailable", 503)
    subject = await run_in_threadpool(accounts.user_subject, databases, keys, account.id)
    events = fusion.verify(fingerprints, {"face": faces, "voice": voices}, databases, keys, subject, body.finger,
                           body.samples())
    return FingerprintResponse(events)


@router.post("/api/fusion/identifications")
@allow(USER)
async def identify_fused(body: FusionIdentification, databases: DatabasesDep, keys: KeysDep,
                         fingerprints: FingerprintsDep, faces: FacesDep, voices: VoicesDep,
                         account: SignedInDep) -> StreamingResponse:
    if fingerprints is None:
        raise AccountError("fingerprint_unavailable", 503)
    subject = await run_in_threadpool(accounts.user_subject, databases, keys, account.id)
    return FingerprintResponse(fusion.identify(fingerprints, {"face": faces, "voice": voices}, databases, keys, subject,
                                               body.samples()))
