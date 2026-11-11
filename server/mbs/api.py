"""The HTTP API on 127.0.0.1 (H11). Every route declares who may call it, and a route without a
declaration is refused (deny by default); the role is checked here on every request, whatever the
client shows (H12)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

import anyio
from fastapi import BackgroundTasks, Depends, FastAPI, Request
from fastapi import Path as PathParameter
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from . import accounts, face, fingerprint, verification, identification, voice
from .accounts import AccountError, SignedIn, Throttle
from .db import Databases
from .engines import EngineError
from .face import FaceError, FaceService
from .fingerprint import FingerprintService
from .keys import Keys
from .models import ADMIN, USER
from .outbox import Outbox
from .voice import VoiceError, VoiceService

PUBLIC = "public"


class FingerprintResponse(StreamingResponse):
    """H35: also close the capture generator when sending a progress event fails or is cancelled."""

    def __init__(self, events):
        super().__init__(fingerprint.ndjson(events), media_type="application/x-ndjson",
                         headers={"Cache-Control": "no-store"})

    async def stream_response(self, send) -> None:
        try:
            await super().stream_response(send)
        finally:
            with anyio.CancelScope(shield=True):
                await self.body_iterator.aclose()


def allow(*roles: str, during_password_change: bool = False):
    """Who may call a route: PUBLIC, or the account roles. `during_password_change` keeps the route open
    to an account that must still replace its one-time password (H12)."""
    def mark(endpoint):
        endpoint.mbs_allow = frozenset(roles)
        endpoint.mbs_during_password_change = during_password_change
        return endpoint
    return mark


def policy(request: Request) -> None:
    endpoint = request.scope.get("endpoint")
    allowed = getattr(endpoint, "mbs_allow", None)
    if not allowed:
        raise AccountError("forbidden", 403)
    if PUBLIC in allowed:
        return
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AccountError("not_signed_in", 401)
    account = accounts.session_account(request.app.state.databases, token)
    if account is None:
        raise AccountError("not_signed_in", 401)
    if account.role not in allowed:
        raise AccountError("forbidden", 403)
    if account.must_change_password and not endpoint.mbs_during_password_change:
        raise AccountError("password_change_required", 403)
    request.state.account, request.state.token = account, token


def signed_in(request: Request) -> SignedIn:
    return request.state.account


class Registration(BaseModel):
    username: str = Field(max_length=64)
    email: str = Field(max_length=320)
    phone: str = Field(max_length=32)
    password: str = Field(max_length=1024)
    national_id: str = Field(max_length=32)
    language: str = Field("en", max_length=8)  # the registration screen's (H31)


class Credentials(BaseModel):
    login: str = Field(max_length=320)
    password: str = Field(max_length=1024)
    language: str | None = Field(None, max_length=8)  # only when chosen on the sign-in screen (H31)


class ResetRequest(BaseModel):
    channel: str = Field(max_length=8)
    destination: str = Field(max_length=320)  # the phone number or the email address
    language: str = Field("en", max_length=8)


class ResetLink(BaseModel):
    token: str = Field(max_length=64)


class NewPassword(BaseModel):
    token: str = Field(max_length=64)
    password: str = Field(max_length=1024)


class PasswordChange(BaseModel):
    current: str = Field(max_length=1024)
    new: str = Field(max_length=1024)


class NewAdministrator(BaseModel):
    password: str = Field(max_length=1024)  # the acting administrator's, asked again (H12)
    username: str = Field(max_length=64)
    email: str = Field(max_length=320)


class ThemeChange(BaseModel):
    theme: str = Field(max_length=16)


class LanguageChange(BaseModel):
    language: str = Field(max_length=8)


class StatusChange(BaseModel):
    password: str = Field(max_length=1024)
    status: str = Field(max_length=16)


class FingerprintEnrolment(BaseModel):
    finger: int = Field(ge=1, le=10)  # ANSI/NIST-ITL position, as in ScannerCapture


class FingerprintVerification(FingerprintEnrolment):
    algorithm: Literal["opencv-sift", "pore-sift", "learned-pore"] = "opencv-sift"  # H38, H39


class FingerprintIdentification(BaseModel):
    model_config = {"extra": "forbid"}
    algorithm: Literal["opencv-sift", "pore-sift", "learned-pore"] = "opencv-sift"  # H41, H42


def _base64_length(size: int) -> int:
    return (size + 2) // 3 * 4


class FaceFrame(BaseModel):
    """A frame of the camera's live view (H48), made small by the page, in base64."""
    model_config = {"extra": "forbid"}
    image: str = Field(max_length=_base64_length(face.LIVE_BYTES))


class FaceImage(BaseModel):
    """An image the user took, as a PNG of the camera's frame, in base64 (H48)."""
    model_config = {"extra": "forbid"}
    image: str = Field(max_length=_base64_length(face.IMAGE_BYTES))


class FaceProbe(BaseModel):
    """The new image of a verification or identification (H49, H50): a PNG of the camera's frame, or the content
    of a JPEG or PNG file (H27, H51), in base64. Enrolment and the live checks take no files."""
    model_config = {"extra": "forbid"}
    image: str = Field(max_length=_base64_length(face.FILE_BYTES))
    source: Literal["device", "file"] = "device"

    def data(self) -> bytes:
        return face.decode_image(self.image, face.FILE_BYTES if self.source == "file" else face.IMAGE_BYTES)


class FaceTaken(FaceImage):
    captured_at: datetime


class FaceEnrolment(BaseModel):
    model_config = {"extra": "forbid"}
    images: list[FaceTaken] = Field(min_length=face.IMAGES, max_length=face.MOST_KEPT)


class VoiceRecording(BaseModel):
    """A recording the user made, as a WAV of 16 kHz, one channel and 16-bit PCM, in base64 (H54)."""
    model_config = {"extra": "forbid"}
    recording: str = Field(max_length=_base64_length(voice.RECORDING_BYTES))


class VoiceMade(VoiceRecording):
    captured_at: datetime


class VoiceEnrolment(BaseModel):
    model_config = {"extra": "forbid"}
    recordings: list[VoiceMade] = Field(min_length=voice.RECORDINGS, max_length=voice.MOST_KEPT)


def account_json(account: SignedIn) -> dict:
    return {"id": str(account.id), "username": account.username, "email": account.email, "role": account.role,
            "must_change_password": account.must_change_password, "theme": account.theme,
            "language": account.language}


def create_app(databases: Databases, keys: Keys, outbox: Outbox, fingerprints: FingerprintService | None = None,
               faces: FaceService | None = None, voices: VoiceService | None = None) -> FastAPI:
    # The policy runs for every route of the application, also for routes added later.
    app = FastAPI(title="Multimodal biometric system", docs_url=None, redoc_url=None, openapi_url=None,
                  dependencies=[Depends(policy)])
    app.state.databases, app.state.keys, app.state.throttle = databases, keys, Throttle()
    app.state.fingerprints = fingerprints
    app.state.faces = faces
    app.state.voices = voices

    @app.exception_handler(AccountError)
    def account_error(request: Request, error: AccountError) -> JSONResponse:
        headers = {"Retry-After": str(int(error.retry_after) + 1)} if error.retry_after else None
        return JSONResponse({"error": error.code}, status_code=error.status, headers=headers)

    @app.exception_handler(FaceError)
    def face_error(request: Request, error: FaceError) -> JSONResponse:
        return JSONResponse({"error": error.code, **error.extra}, status_code=error.status)

    def face_service() -> FaceService:
        service = app.state.faces
        if service is None:
            raise FaceError("face_unavailable", 503)
        return service

    @app.exception_handler(VoiceError)
    def voice_error(request: Request, error: VoiceError) -> JSONResponse:
        return JSONResponse({"error": error.code, **error.extra}, status_code=error.status)

    def voice_service() -> VoiceService:
        service = app.state.voices
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

    def engine_work(work):
        """H48: an engine that cannot answer is the server's failure, reported without the image."""
        try:
            return work()
        except EngineError:
            face.logger.warning("the face engine failed a request")
            raise FaceError("engine_unavailable", 503) from None

    @app.get("/api/health")
    @allow(PUBLIC)
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/api/register", status_code=201)
    @allow(PUBLIC)
    def register(body: Registration) -> dict:
        account = accounts.register(databases, keys, body.username, body.email, body.phone, body.password,
                                    body.national_id, body.language)
        return {"account": account_json(account)}

    @app.post("/api/login")
    @allow(PUBLIC)
    def login(body: Credentials) -> dict:
        token, account = accounts.sign_in(databases, app.state.throttle, body.login, body.password, body.language)
        return {"token": token, "account": account_json(account)}

    # Password recovery while signed out (H32). The request answers the same whether a message is sent
    # or not, and the message is written after the answer, so its time tells nothing either.
    @app.post("/api/password-reset", status_code=202)
    @allow(PUBLIC)
    def request_reset(body: ResetRequest, background: BackgroundTasks) -> None:
        message = accounts.request_reset(databases, body.channel, body.destination, body.language)
        if message is not None:
            background.add_task(outbox.send, message)

    @app.post("/api/password-reset/check", status_code=204)
    @allow(PUBLIC)
    def check_reset(body: ResetLink) -> None:
        accounts.check_reset(databases, body.token)

    @app.post("/api/password-reset/complete", status_code=204)
    @allow(PUBLIC)
    def complete_reset(body: NewPassword) -> None:
        accounts.complete_reset(databases, app.state.throttle, body.token, body.password)

    @app.post("/api/logout", status_code=204)
    @allow(USER, ADMIN, during_password_change=True)
    def logout(request: Request) -> None:
        accounts.sign_out(databases, request.state.token)

    @app.get("/api/me")
    @allow(USER, ADMIN, during_password_change=True)
    def me(account: SignedIn = Depends(signed_in)) -> dict:
        return {"account": account_json(account), "modalities": accounts.modalities(databases, keys, account)}

    @app.post("/api/me/password", status_code=204)
    @allow(USER, ADMIN, during_password_change=True)
    def change_password(body: PasswordChange, request: Request, account: SignedIn = Depends(signed_in)) -> None:
        accounts.change_password(databases, account.id, request.state.token, body.current, body.new)

    @app.post("/api/me/theme", status_code=204)
    @allow(USER, ADMIN)
    def change_theme(body: ThemeChange, account: SignedIn = Depends(signed_in)) -> None:
        accounts.set_theme(databases, account.id, body.theme)

    @app.post("/api/me/language", status_code=204)
    @allow(USER, ADMIN)
    def change_language(body: LanguageChange, account: SignedIn = Depends(signed_in)) -> None:
        accounts.set_language(databases, account.id, body.language)

    # Fingerprint enrolment (H15, H33): the answer is a stream of JSON lines, one per event, so the client can
    # show the scanner's progress live; it ends with `saved` or `failed`. Closing the connection cancels it.
    @app.post("/api/fingerprint/enrolments")
    @allow(USER)
    async def enrol_fingerprint(body: FingerprintEnrolment, account: SignedIn = Depends(signed_in)) -> StreamingResponse:
        service = app.state.fingerprints
        if service is None:
            raise AccountError("fingerprint_unavailable", 503)
        subject = await run_in_threadpool(accounts.subject_of, databases, keys, account.id)
        events = fingerprint.enrol(service, databases, keys, subject, body.finger)
        return FingerprintResponse(events)

    # The user deletes a finger's enrolment (H34): its captures and templates are erased, and the finger can be
    # enrolled again later, or not at all.
    @app.delete("/api/fingerprint/fingers/{finger}", status_code=204)
    @allow(USER)
    def delete_fingerprint(finger: Annotated[int, PathParameter(ge=1, le=10)], account: SignedIn = Depends(signed_in)) -> None:
        subject = accounts.subject_of(databases, keys, account.id)
        if not fingerprint.delete_finger(databases, subject, finger):
            raise AccountError("not_enrolled", 404)

    @app.post("/api/fingerprint/verifications")
    @allow(USER)
    async def verify_fingerprint(body: FingerprintVerification, account: SignedIn = Depends(signed_in)) -> StreamingResponse:
        """H35: the signed-in user's chosen finger, through the same capture and progress channel as H33."""
        service = app.state.fingerprints
        if service is None:
            raise AccountError("fingerprint_unavailable", 503)
        subject = await run_in_threadpool(accounts.subject_of, databases, keys, account.id)
        events = verification.verify(service, databases, keys, subject, body.finger, body.algorithm)
        return FingerprintResponse(events)

    @app.get("/api/fingerprint/methods")
    @allow(USER)
    def fingerprint_methods() -> dict:
        return {"methods": fingerprint.methods(databases, app.state.fingerprints)}

    @app.post("/api/fingerprint/identifications")
    @allow(USER)
    async def identify_fingerprint(body: FingerprintIdentification, account: SignedIn = Depends(signed_in)) -> StreamingResponse:
        service = app.state.fingerprints
        if service is None:
            raise AccountError("fingerprint_unavailable", 503)
        subject = await run_in_threadpool(accounts.subject_of, databases, keys, account.id)
        return FingerprintResponse(identification.identify(service, databases, keys, subject, body.algorithm))

    # Face (H48): the page owns the camera. It asks where the faces of its live view are, has each taken image
    # checked at once, then sends the images that passed to be enrolled; the server keeps nothing between
    # these requests and checks everything again before it saves.
    @app.get("/api/face/method")
    @allow(USER)
    def face_method() -> dict:
        return face.method(databases, app.state.faces)

    @app.post("/api/face/detect")
    @allow(USER)
    def detect_face(body: FaceFrame) -> dict:
        service = face_service()
        image = face.decode_image(body.image, face.LIVE_BYTES)
        return engine_work(lambda: face.detect(service, image))

    @app.post("/api/face/checks")
    @allow(USER)
    def check_face(body: FaceImage) -> dict:
        service = face_service()
        image = face.decode_image(body.image, face.IMAGE_BYTES)
        return engine_work(lambda: face.check(service, image))

    @app.post("/api/face/enrolments")
    @allow(USER)
    def enrol_face(body: FaceEnrolment, account: SignedIn = Depends(signed_in)) -> JSONResponse:
        service = face_service()
        images = [(face.decode_image(taken.image, face.IMAGE_BYTES), taken.captured_at) for taken in body.images]
        subject = accounts.subject_of(databases, keys, account.id)
        result = engine_work(lambda: face.enrol(service, databases, keys, subject, images))
        return JSONResponse(result, status_code=201 if result["status"] == "saved" else 200)

    # H49: one taken image against the caller's current face enrolment; a completed comparison is saved with
    # its sealed image before the answer, a rejected image is not.
    @app.post("/api/face/verifications")
    @allow(USER)
    def verify_face(body: FaceProbe, account: SignedIn = Depends(signed_in)) -> dict:
        service = face_service()
        image = body.data()
        subject = accounts.subject_of(databases, keys, account.id)
        return engine_work(lambda: face.verify(service, databases, keys, subject, image, body.source))

    # H50: one taken image against every current face enrolment of the active users. A completed search is saved
    # with its sealed image before the answer, a rejected image is not; other users stay anonymous (H18).
    @app.post("/api/face/identifications")
    @allow(USER)
    def identify_face(body: FaceProbe, account: SignedIn = Depends(signed_in)) -> dict:
        service = face_service()
        image = body.data()
        subject = accounts.subject_of(databases, keys, account.id)
        return engine_work(lambda: face.identify(service, databases, keys, subject, image, body.source))

    # As H34 for a finger: the face's enrolment is erased with its images and embeddings, and (H49) with its
    # verification attempts and their sealed images; identification attempts stay, without the link (H41, H50).
    @app.delete("/api/face/enrolment", status_code=204)
    @allow(USER)
    def delete_face(account: SignedIn = Depends(signed_in)) -> None:
        subject = accounts.subject_of(databases, keys, account.id)
        if not face.delete_face(databases, subject):
            raise AccountError("not_enrolled", 404)

    # H54: the page records with the microphone and sends each recording to be checked at once, then sends the
    # recordings that passed to be enrolled; the server keeps nothing between these requests and checks
    # everything again before it saves.
    @app.get("/api/voice/method")
    @allow(USER)
    def voice_method() -> dict:
        return voice.method(databases, app.state.voices)

    @app.post("/api/voice/checks")
    @allow(USER)
    def check_voice(body: VoiceRecording) -> dict:
        service = voice_service()
        recording = voice.decode_recording(body.recording, voice.RECORDING_BYTES)
        return voice_work(lambda: voice.check(service, recording))

    @app.post("/api/voice/enrolments")
    @allow(USER)
    def enrol_voice(body: VoiceEnrolment, account: SignedIn = Depends(signed_in)) -> JSONResponse:
        service = voice_service()
        recordings = [(voice.decode_recording(made.recording, voice.RECORDING_BYTES), made.captured_at)
                      for made in body.recordings]
        subject = accounts.subject_of(databases, keys, account.id)
        result = voice_work(lambda: voice.enrol(service, databases, keys, subject, recordings))
        return JSONResponse(result, status_code=201 if result["status"] == "saved" else 200)

    # As H34 for a finger and H48 for the face: the voice's enrolment is erased with its recordings and embeddings.
    @app.delete("/api/voice/enrolment", status_code=204)
    @allow(USER)
    def delete_voice(account: SignedIn = Depends(signed_in)) -> None:
        subject = accounts.subject_of(databases, keys, account.id)
        if not voice.delete_voice(databases, subject):
            raise AccountError("not_enrolled", 404)

    @app.get("/api/admin/accounts")
    @allow(ADMIN)
    def admin_accounts() -> dict:
        return {"accounts": accounts.list_accounts(databases)}

    @app.post("/api/admin/administrators", status_code=201)
    @allow(ADMIN)
    def admin_new_administrator(body: NewAdministrator, account: SignedIn = Depends(signed_in)) -> dict:
        created, one_time = accounts.create_administrator(databases, account.id, body.password, body.username, body.email)
        return {"account": account_json(created), "one_time_password": one_time}

    @app.post("/api/admin/accounts/{account_id}/status", status_code=204)
    @allow(ADMIN)
    def admin_status(account_id: uuid.UUID, body: StatusChange, account: SignedIn = Depends(signed_in)) -> None:
        accounts.set_status(databases, account.id, body.password, account_id, body.status)

    @app.get("/api/admin/audit")
    @allow(ADMIN)
    def admin_audit() -> dict:
        return {"entries": accounts.audit_log(databases)}

    return app
