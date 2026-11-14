"""The HTTP API on 127.0.0.1 (H11), assembled from the routes of every area (mbs/routes/). Every route declares who
may call it, and a route without a declaration is refused (deny by default): the policy, the application's own
dependency, checks the role on every request, whatever the client shows (H12, mbs/routes/policy.py). Before any
route, a request to another host or with a body larger than its route takes is refused (H58, mbs/guard.py)."""

from __future__ import annotations

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from .accounts import AccountError, Throttle
from .db import Databases
from .face import FaceError, FaceService
from .fingerprint import FingerprintService
from .guard import Guard
from .keys import Keys
from .outbox import Outbox
from .routes import BODY_LIMITS, ROUTERS
from .routes.policy import PUBLIC, allow, policy
from .voice import VoiceError, VoiceService


def create_app(databases: Databases, keys: Keys, outbox: Outbox, fingerprints: FingerprintService | None = None,
               faces: FaceService | None = None, voices: VoiceService | None = None) -> FastAPI:
    # The policy runs for every route of the application, also for routes added later.
    app = FastAPI(title="Multimodal biometric system", docs_url=None, redoc_url=None, openapi_url=None,
                  dependencies=[Depends(policy)])
    app.add_middleware(Guard, limits=BODY_LIMITS)  # H58
    app.state.databases, app.state.keys, app.state.outbox, app.state.throttle = databases, keys, outbox, Throttle()
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

    @app.exception_handler(VoiceError)
    def voice_error(request: Request, error: VoiceError) -> JSONResponse:
        return JSONResponse({"error": error.code, **error.extra}, status_code=error.status)

    @app.get("/api/health")
    @allow(PUBLIC)
    def health() -> dict:
        return {"status": "ok"}

    for router in ROUTERS:
        app.include_router(router)
    return app
