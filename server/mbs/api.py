"""The HTTP API on 127.0.0.1 (H11). Every route declares who may call it, and a route without a
declaration is refused (deny by default); the role is checked here on every request, whatever the
client shows (H12)."""

from __future__ import annotations

import uuid

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import accounts
from .accounts import AccountError, SignedIn, Throttle
from .db import Databases
from .keys import Keys
from .models import ADMIN, USER

PUBLIC = "public"


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
    password: str = Field(max_length=1024)
    national_id: str = Field(max_length=32)


class Credentials(BaseModel):
    login: str = Field(max_length=320)
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


class StatusChange(BaseModel):
    password: str = Field(max_length=1024)
    status: str = Field(max_length=16)


def account_json(account: SignedIn) -> dict:
    return {"id": str(account.id), "username": account.username, "email": account.email, "role": account.role,
            "must_change_password": account.must_change_password, "theme": account.theme}


def create_app(databases: Databases, keys: Keys) -> FastAPI:
    # The policy runs for every route of the application, also for routes added later.
    app = FastAPI(title="Multimodal biometric system", docs_url=None, redoc_url=None, openapi_url=None,
                  dependencies=[Depends(policy)])
    app.state.databases, app.state.keys, app.state.throttle = databases, keys, Throttle()

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
        account = accounts.register(databases, keys, body.username, body.email, body.password, body.national_id)
        return {"account": account_json(account)}

    @app.post("/api/login")
    @allow(PUBLIC)
    def login(body: Credentials) -> dict:
        token, account = accounts.sign_in(databases, app.state.throttle, body.login, body.password)
        return {"token": token, "account": account_json(account)}

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
