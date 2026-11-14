"""The voice routes (H54 to H57). The page records with the microphone and sends each recording to be checked at once,
then sends the recordings that passed to be enrolled; the server keeps nothing between these requests and checks
everything again before it saves. Verification and identification take one recording from the microphone or a file
(H27, H57)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .. import accounts, voice
from ..accounts import AccountError, SignedIn
from ..engines import EngineError
from ..models import USER
from ..voice import VoiceError, VoiceService
from .common import JSON_AROUND, DatabasesDep, KeysDep, base64_length
from .policy import allow, signed_in

router = APIRouter()


async def _voices(request: Request) -> VoiceService | None:
    return request.app.state.voices


VoicesDep = Annotated[VoiceService | None, Depends(_voices)]


def available(service: VoiceService | None) -> VoiceService:
    if service is None:
        raise VoiceError("voice_unavailable", 503)
    return service


def voice_work(work):
    """H54: an engine that cannot answer is the server's failure, reported without the recording."""
    try:
        return work()
    except EngineError:
        voice.logger.warning("the voice engine failed a request")
        raise VoiceError("engine_unavailable", 503) from None


class VoiceRecording(BaseModel):
    """A recording the user made, as a WAV of 16 kHz, one channel and 16-bit PCM, in base64 (H54)."""
    model_config = {"extra": "forbid"}
    recording: str = Field(max_length=base64_length(voice.RECORDING_BYTES))


class VoiceProbe(BaseModel):
    """The new recording of a verification or identification (H55, H56): a WAV the page recorded, or the content of
    a WAV, MP3 or OGG file (H27, H57), in base64. Enrolment and the checks take no files."""
    model_config = {"extra": "forbid"}
    recording: str = Field(max_length=base64_length(voice.FILE_BYTES))
    source: Literal["device", "file"] = "device"

    def data(self) -> bytes:
        return voice.decode_recording(self.recording, voice.FILE_BYTES if self.source == "file" else voice.RECORDING_BYTES)


class VoiceMade(VoiceRecording):
    captured_at: datetime


class VoiceEnrolment(BaseModel):
    model_config = {"extra": "forbid"}
    recordings: list[VoiceMade] = Field(min_length=voice.RECORDINGS, max_length=voice.MOST_KEPT)


# H58: these routes may receive bodies exactly as large as their models allow, with room for the JSON around each
# recording.
BODY_LIMITS = {
    "/api/voice/checks": base64_length(voice.RECORDING_BYTES) + JSON_AROUND,
    "/api/voice/enrolments": voice.MOST_KEPT * (base64_length(voice.RECORDING_BYTES) + JSON_AROUND),
    "/api/voice/verifications": base64_length(voice.FILE_BYTES) + JSON_AROUND,
    "/api/voice/identifications": base64_length(voice.FILE_BYTES) + JSON_AROUND,
}


@router.get("/api/voice/method")
@allow(USER)
def voice_method(databases: DatabasesDep, voices: VoicesDep) -> dict:
    return voice.method(databases, voices)


@router.post("/api/voice/checks")
@allow(USER)
def check_voice(body: VoiceRecording, voices: VoicesDep) -> dict:
    service = available(voices)
    recording = voice.decode_recording(body.recording, voice.RECORDING_BYTES)
    return voice_work(lambda: voice.check(service, recording))


@router.post("/api/voice/enrolments")
@allow(USER)
def enrol_voice(body: VoiceEnrolment, databases: DatabasesDep, keys: KeysDep, voices: VoicesDep,
                account: SignedIn = Depends(signed_in)) -> JSONResponse:
    service = available(voices)
    recordings = [(voice.decode_recording(made.recording, voice.RECORDING_BYTES), made.captured_at)
                  for made in body.recordings]
    subject = accounts.subject_of(databases, keys, account.id)
    result = voice_work(lambda: voice.enrol(service, databases, keys, subject, recordings))
    return JSONResponse(result, status_code=201 if result["status"] == "saved" else 200)


# H55: one recording against the caller's current voice enrolment; a completed comparison is saved with its
# sealed recording before the answer, a refused recording is not.
@router.post("/api/voice/verifications")
@allow(USER)
def verify_voice(body: VoiceProbe, databases: DatabasesDep, keys: KeysDep, voices: VoicesDep,
                 account: SignedIn = Depends(signed_in)) -> dict:
    service = available(voices)
    recording = body.data()
    subject = accounts.subject_of(databases, keys, account.id)
    return voice_work(lambda: voice.verify(service, databases, keys, subject, recording, body.source))


# H56: one recording against every current voice enrolment of the active users, as H50 does for the face. A
# completed search is saved with its sealed recording before the answer, a refused recording is not; other users
# stay anonymous (H18).
@router.post("/api/voice/identifications")
@allow(USER)
def identify_voice(body: VoiceProbe, databases: DatabasesDep, keys: KeysDep, voices: VoicesDep,
                   account: SignedIn = Depends(signed_in)) -> dict:
    service = available(voices)
    recording = body.data()
    subject = accounts.subject_of(databases, keys, account.id)
    return voice_work(lambda: voice.identify(service, databases, keys, subject, recording, body.source))


# As H34 for a finger and H48 for the face: the voice's enrolment is erased with its recordings and embeddings,
# and (H55) with its verification attempts and their sealed recordings; identification attempts stay, without
# the link (H41, H56).
@router.delete("/api/voice/enrolment", status_code=204)
@allow(USER)
def delete_voice(databases: DatabasesDep, keys: KeysDep, account: SignedIn = Depends(signed_in)) -> None:
    subject = accounts.subject_of(databases, keys, account.id)
    if not voice.delete_voice(databases, subject):
        raise AccountError("not_enrolled", 404)
