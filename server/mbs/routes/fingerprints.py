"""The fingerprint routes (H33 to H45): enrolment, deleting a finger's enrolment, verification and identification,
with the scanner's progress streamed as JSON lines, and the methods' cards."""

from __future__ import annotations

from typing import Annotated, Literal

import anyio
from fastapi import APIRouter, Depends, Request
from fastapi import Path as PathParameter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .. import accounts, fingerprint, identification, verification
from ..accounts import AccountError, SignedIn
from ..fingerprint import FingerprintService
from ..models import USER
from .common import DatabasesDep, KeysDep
from .policy import allow, signed_in

router = APIRouter()


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


async def _fingerprints(request: Request) -> FingerprintService | None:
    return request.app.state.fingerprints


FingerprintsDep = Annotated[FingerprintService | None, Depends(_fingerprints)]


class FingerprintEnrolment(BaseModel):
    finger: int = Field(ge=1, le=10)  # ANSI/NIST-ITL position, as in ScannerCapture


class FingerprintVerification(FingerprintEnrolment):
    algorithm: Literal["opencv-sift", "pore-sift", "learned-pore"] = "opencv-sift"  # H38, H39


class FingerprintIdentification(BaseModel):
    model_config = {"extra": "forbid"}
    algorithm: Literal["opencv-sift", "pore-sift", "learned-pore"] = "opencv-sift"  # H41, H42


# Fingerprint enrolment (H15, H33): the answer is a stream of JSON lines, one per event, so the client can
# show the scanner's progress live; it ends with `saved` or `failed`. Closing the connection cancels it.
@router.post("/api/fingerprint/enrolments")
@allow(USER)
async def enrol_fingerprint(body: FingerprintEnrolment, databases: DatabasesDep, keys: KeysDep,
                            service: FingerprintsDep, account: SignedIn = Depends(signed_in)) -> StreamingResponse:
    if service is None:
        raise AccountError("fingerprint_unavailable", 503)
    subject = await run_in_threadpool(accounts.subject_of, databases, keys, account.id)
    events = fingerprint.enrol(service, databases, keys, subject, body.finger)
    return FingerprintResponse(events)


# The user deletes a finger's enrolment (H34): its captures and templates are erased, and the finger can be
# enrolled again later, or not at all.
@router.delete("/api/fingerprint/fingers/{finger}", status_code=204)
@allow(USER)
def delete_fingerprint(finger: Annotated[int, PathParameter(ge=1, le=10)], databases: DatabasesDep, keys: KeysDep,
                       account: SignedIn = Depends(signed_in)) -> None:
    subject = accounts.subject_of(databases, keys, account.id)
    if not fingerprint.delete_finger(databases, subject, finger):
        raise AccountError("not_enrolled", 404)


@router.post("/api/fingerprint/verifications")
@allow(USER)
async def verify_fingerprint(body: FingerprintVerification, databases: DatabasesDep, keys: KeysDep,
                             service: FingerprintsDep, account: SignedIn = Depends(signed_in)) -> StreamingResponse:
    """H35: the signed-in user's chosen finger, through the same capture and progress channel as H33."""
    if service is None:
        raise AccountError("fingerprint_unavailable", 503)
    subject = await run_in_threadpool(accounts.subject_of, databases, keys, account.id)
    events = verification.verify(service, databases, keys, subject, body.finger, body.algorithm)
    return FingerprintResponse(events)


@router.get("/api/fingerprint/methods")
@allow(USER)
def fingerprint_methods(databases: DatabasesDep, service: FingerprintsDep) -> dict:
    return {"methods": fingerprint.methods(databases, service)}


@router.post("/api/fingerprint/identifications")
@allow(USER)
async def identify_fingerprint(body: FingerprintIdentification, databases: DatabasesDep, keys: KeysDep,
                               service: FingerprintsDep, account: SignedIn = Depends(signed_in)) -> StreamingResponse:
    if service is None:
        raise AccountError("fingerprint_unavailable", 503)
    subject = await run_in_threadpool(accounts.subject_of, databases, keys, account.id)
    return FingerprintResponse(identification.identify(service, databases, keys, subject, body.algorithm))
