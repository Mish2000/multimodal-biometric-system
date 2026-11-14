"""The routes of one's own account (H12): registration with the national ID (H3), sign-in and sign-out, password
recovery while signed out (H32), and the signed-in account with its password, theme and language (H24, H28, H31)."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from pydantic import BaseModel, Field

from .. import accounts
from ..accounts import SignedIn
from ..models import ADMIN, USER
from .common import DatabasesDep, KeysDep, OutboxDep, ThrottleDep
from .policy import PUBLIC, allow, signed_in

router = APIRouter()


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


class ThemeChange(BaseModel):
    theme: str = Field(max_length=16)


class LanguageChange(BaseModel):
    language: str = Field(max_length=8)


def account_json(account: SignedIn) -> dict:
    return {"id": str(account.id), "username": account.username, "email": account.email, "role": account.role,
            "must_change_password": account.must_change_password, "theme": account.theme,
            "language": account.language}


@router.post("/api/register", status_code=201)
@allow(PUBLIC)
def register(body: Registration, databases: DatabasesDep, keys: KeysDep) -> dict:
    account = accounts.register(databases, keys, body.username, body.email, body.phone, body.password,
                                body.national_id, body.language)
    return {"account": account_json(account)}


@router.post("/api/login")
@allow(PUBLIC)
def login(body: Credentials, databases: DatabasesDep, throttle: ThrottleDep) -> dict:
    token, account = accounts.sign_in(databases, throttle, body.login, body.password, body.language)
    return {"token": token, "account": account_json(account)}


# Password recovery while signed out (H32). The request answers the same whether a message is sent
# or not, and the message is written after the answer, so its time tells nothing either.
@router.post("/api/password-reset", status_code=202)
@allow(PUBLIC)
def request_reset(body: ResetRequest, background: BackgroundTasks, databases: DatabasesDep, outbox: OutboxDep) -> None:
    message = accounts.request_reset(databases, body.channel, body.destination, body.language)
    if message is not None:
        background.add_task(outbox.send, message)


@router.post("/api/password-reset/check", status_code=204)
@allow(PUBLIC)
def check_reset(body: ResetLink, databases: DatabasesDep) -> None:
    accounts.check_reset(databases, body.token)


@router.post("/api/password-reset/complete", status_code=204)
@allow(PUBLIC)
def complete_reset(body: NewPassword, databases: DatabasesDep, throttle: ThrottleDep) -> None:
    accounts.complete_reset(databases, throttle, body.token, body.password)


@router.post("/api/logout", status_code=204)
@allow(USER, ADMIN, during_password_change=True)
def logout(request: Request, databases: DatabasesDep) -> None:
    accounts.sign_out(databases, request.state.token)


@router.get("/api/me")
@allow(USER, ADMIN, during_password_change=True)
def me(databases: DatabasesDep, keys: KeysDep, account: SignedIn = Depends(signed_in)) -> dict:
    return {"account": account_json(account), "modalities": accounts.modalities(databases, keys, account)}


@router.post("/api/me/password", status_code=204)
@allow(USER, ADMIN, during_password_change=True)
def change_password(body: PasswordChange, request: Request, databases: DatabasesDep,
                    account: SignedIn = Depends(signed_in)) -> None:
    accounts.change_password(databases, account.id, request.state.token, body.current, body.new)


@router.post("/api/me/theme", status_code=204)
@allow(USER, ADMIN)
def change_theme(body: ThemeChange, databases: DatabasesDep, account: SignedIn = Depends(signed_in)) -> None:
    accounts.set_theme(databases, account.id, body.theme)


@router.post("/api/me/language", status_code=204)
@allow(USER, ADMIN)
def change_language(body: LanguageChange, databases: DatabasesDep, account: SignedIn = Depends(signed_in)) -> None:
    accounts.set_language(databases, account.id, body.language)
