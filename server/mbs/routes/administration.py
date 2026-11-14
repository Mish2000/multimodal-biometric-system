"""The administration's routes (H12): the accounts, a new administrator, disabling and enabling an account, and the
audit log. A change asks for the acting administrator's password again and is written to the audit log."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from .. import accounts
from ..accounts import SignedIn
from ..models import ADMIN
from .account import account_json
from .common import DatabasesDep
from .policy import allow, signed_in

router = APIRouter()


class NewAdministrator(BaseModel):
    password: str = Field(max_length=1024)  # the acting administrator's, asked again (H12)
    username: str = Field(max_length=64)
    email: str = Field(max_length=320)


class StatusChange(BaseModel):
    password: str = Field(max_length=1024)
    status: str = Field(max_length=16)


@router.get("/api/admin/accounts")
@allow(ADMIN)
def admin_accounts(databases: DatabasesDep) -> dict:
    return {"accounts": accounts.list_accounts(databases)}


@router.post("/api/admin/administrators", status_code=201)
@allow(ADMIN)
def admin_new_administrator(body: NewAdministrator, databases: DatabasesDep,
                            account: SignedIn = Depends(signed_in)) -> dict:
    created, one_time = accounts.create_administrator(databases, account.id, body.password, body.username, body.email)
    return {"account": account_json(created), "one_time_password": one_time}


@router.post("/api/admin/accounts/{account_id}/status", status_code=204)
@allow(ADMIN)
def admin_status(account_id: uuid.UUID, body: StatusChange, databases: DatabasesDep,
                 account: SignedIn = Depends(signed_in)) -> None:
    accounts.set_status(databases, account.id, body.password, account_id, body.status)


@router.get("/api/admin/audit")
@allow(ADMIN)
def admin_audit(databases: DatabasesDep) -> dict:
    return {"entries": accounts.audit_log(databases)}
