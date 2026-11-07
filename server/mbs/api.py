"""The HTTP API on 127.0.0.1 (H11). Every route declares who may call it, and a route without a
declaration is refused (deny by default); the role is checked here on every request, whatever the
client shows (H12)."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

import anyio
from fastapi import BackgroundTasks, Depends, FastAPI, Request
from fastapi import Path as PathParameter
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from . import accounts, fingerprint, verification
from .accounts import AccountError, SignedIn, Throttle
from .db import Databases
from .fingerprint import FingerprintService
from .keys import Keys
from .models import ADMIN, USER
from .outbox import Outbox

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


def account_json(account: SignedIn) -> dict:
    return {"id": str(account.id), "username": account.username, "email": account.email, "role": account.role,
            "must_change_password": account.must_change_password, "theme": account.theme,
            "language": account.language}


def create_app(databases: Databases, keys: Keys, outbox: Outbox, fingerprints: FingerprintService | None = None) -> FastAPI:
    # The policy runs for every route of the application, also for routes added later.
    app = FastAPI(title="Multimodal biometric system", docs_url=None, redoc_url=None, openapi_url=None,
                  dependencies=[Depends(policy)])
    app.state.databases, app.state.keys, app.state.throttle = databases, keys, Throttle()
    app.state.fingerprints = fingerprints

    @app.exception_handler(AccountError)
    def account_error(request: Request, error: AccountError) -> JSONResponse:
        headers = {"Retry-After": str(int(error.retry_after) + 1)} if error.retry_after else None
        return JSONResponse({"error": error.code}, status_code=error.status, headers=headers)

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
