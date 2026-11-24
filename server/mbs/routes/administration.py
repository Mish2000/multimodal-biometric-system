"""The administration's routes (H12): the accounts, a new administrator, disabling and enabling an account, the
audit log and the attempt history (H61). A change asks for the acting administrator's password again and is written
to the audit log; reading is not a change."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter
from pydantic import AwareDatetime, BaseModel, Field

from .. import accounts, history
from ..models import ADMIN
from .account import account_json
from .common import DatabasesDep, KeysDep
from .policy import SignedInDep, allow

router = APIRouter()


class NewAdministrator(BaseModel):
    password: str = Field(max_length=1024)  # the acting administrator's, asked again (H12)
    username: str = Field(max_length=64)
    email: str = Field(max_length=320)


class StatusChange(BaseModel):
    password: str = Field(max_length=1024)
    status: str = Field(max_length=16)


class HistoryRow(BaseModel):
    """The last row of a page, to read the next one after it."""
    at: AwareDatetime
    id: uuid.UUID


class AttemptSearch(BaseModel):
    """The history's filters, each optional, in the body: the client's routes carry no query string, and a username
    in an address would be written to the server's access log (H61)."""
    since: AwareDatetime | None = None
    until: AwareDatetime | None = None
    user: str | None = Field(default=None, max_length=32)
    type: Literal["fingerprint", "face", "voice", "combined"] | None = None
    mode: Literal["verify", "identify"] | None = None
    method: Literal["opencv-sift", "pore-sift", "learned-pore", "sface", "ecapa-voxceleb"] | None = None
    result: Literal["accepted", "rejected"] | None = None
    source: Literal["device", "file"] | None = None
    after: HistoryRow | None = None
    limit: int = Field(default=history.PAGE, ge=1, le=history.PAGE)


@router.get("/api/admin/accounts")
@allow(ADMIN)
def admin_accounts(databases: DatabasesDep) -> dict:
    return {"accounts": accounts.list_accounts(databases)}


@router.post("/api/admin/administrators", status_code=201)
@allow(ADMIN)
def admin_new_administrator(body: NewAdministrator, databases: DatabasesDep,
                            account: SignedInDep) -> dict:
    created, one_time = accounts.create_administrator(databases, account.id, body.password, body.username, body.email)
    return {"account": account_json(created), "one_time_password": one_time}


@router.post("/api/admin/accounts/{account_id}/status", status_code=204)
@allow(ADMIN)
def admin_status(account_id: uuid.UUID, body: StatusChange, databases: DatabasesDep,
                 account: SignedInDep) -> None:
    accounts.set_status(databases, account.id, body.password, account_id, body.status)


@router.get("/api/admin/audit")
@allow(ADMIN)
def admin_audit(databases: DatabasesDep) -> dict:
    return {"entries": accounts.audit_log(databases)}


@router.post("/api/admin/attempts/search")
@allow(ADMIN)
def admin_attempts(body: AttemptSearch, databases: DatabasesDep, keys: KeysDep) -> dict:
    filters = history.Filters(since=body.since, until=body.until, user=body.user, type=body.type, mode=body.mode,
                              method=body.method, result=body.result, source=body.source)
    after = (body.after.at, body.after.id) if body.after is not None else None
    return history.search(databases, keys, filters, after, body.limit)
