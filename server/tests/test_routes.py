"""The API's routes as the client knows them: each path with its method, its name, its status, who may call it (H12)
and its request model, whose JSON schema is pinned by a short SHA-256. Moving routes between modules must leave this
table unchanged, and the policy must stay every route's first dependency (deny by default)."""

from __future__ import annotations

import hashlib
import json

from fastapi.routing import APIRoute, iter_route_contexts

from mbs.api import create_app
from mbs.routes.policy import policy

ROUTES = [
    ("GET", "/api/admin/accounts", "admin_accounts", None, ("admin",), False, None),
    ("POST", "/api/admin/accounts/{account_id}/status", "admin_status", 204, ("admin",), False, "StatusChange"),
    ("POST", "/api/admin/administrators", "admin_new_administrator", 201, ("admin",), False, "NewAdministrator"),
    ("GET", "/api/admin/audit", "admin_audit", None, ("admin",), False, None),
    ("POST", "/api/face/checks", "check_face", None, ("user",), False, "FaceImage"),
    ("POST", "/api/face/detect", "detect_face", None, ("user",), False, "FaceFrame"),
    ("DELETE", "/api/face/enrolment", "delete_face", 204, ("user",), False, None),
    ("POST", "/api/face/enrolments", "enrol_face", None, ("user",), False, "FaceEnrolment"),
    ("POST", "/api/face/identifications", "identify_face", None, ("user",), False, "FaceProbe"),
    ("GET", "/api/face/method", "face_method", None, ("user",), False, None),
    ("POST", "/api/face/verifications", "verify_face", None, ("user",), False, "FaceProbe"),
    ("POST", "/api/fingerprint/enrolments", "enrol_fingerprint", None, ("user",), False, "FingerprintEnrolment"),
    ("DELETE", "/api/fingerprint/fingers/{finger}", "delete_fingerprint", 204, ("user",), False, None),
    ("POST", "/api/fingerprint/identifications", "identify_fingerprint", None, ("user",), False,
     "FingerprintIdentification"),
    ("GET", "/api/fingerprint/methods", "fingerprint_methods", None, ("user",), False, None),
    ("POST", "/api/fingerprint/verifications", "verify_fingerprint", None, ("user",), False, "FingerprintVerification"),
    ("GET", "/api/health", "health", None, ("public",), False, None),
    ("POST", "/api/login", "login", None, ("public",), False, "Credentials"),
    ("POST", "/api/logout", "logout", 204, ("admin", "user"), True, None),
    ("GET", "/api/me", "me", None, ("admin", "user"), True, None),
    ("POST", "/api/me/language", "change_language", 204, ("admin", "user"), False, "LanguageChange"),
    ("POST", "/api/me/password", "change_password", 204, ("admin", "user"), True, "PasswordChange"),
    ("POST", "/api/me/theme", "change_theme", 204, ("admin", "user"), False, "ThemeChange"),
    ("POST", "/api/password-reset", "request_reset", 202, ("public",), False, "ResetRequest"),
    ("POST", "/api/password-reset/check", "check_reset", 204, ("public",), False, "ResetLink"),
    ("POST", "/api/password-reset/complete", "complete_reset", 204, ("public",), False, "NewPassword"),
    ("POST", "/api/register", "register", 201, ("public",), False, "Registration"),
    ("POST", "/api/voice/checks", "check_voice", None, ("user",), False, "VoiceRecording"),
    ("DELETE", "/api/voice/enrolment", "delete_voice", 204, ("user",), False, None),
    ("POST", "/api/voice/enrolments", "enrol_voice", None, ("user",), False, "VoiceEnrolment"),
    ("POST", "/api/voice/identifications", "identify_voice", None, ("user",), False, "VoiceProbe"),
    ("GET", "/api/voice/method", "voice_method", None, ("user",), False, None),
    ("POST", "/api/voice/verifications", "verify_voice", None, ("user",), False, "VoiceProbe"),
]

SCHEMAS = {
    "Credentials": "5609baba1730",
    "FaceEnrolment": "ddb89bde9c7f",
    "FaceFrame": "d37b32ff5418",
    "FaceImage": "0013efbc6c48",
    "FaceProbe": "3ee2e5ae3bb8",
    "FingerprintEnrolment": "898de78fb99c",
    "FingerprintIdentification": "4de684dd54ed",
    "FingerprintVerification": "a93cf7738403",
    "LanguageChange": "ea2be26793a9",
    "NewAdministrator": "6b6f6495df9b",
    "NewPassword": "6d756741f900",
    "PasswordChange": "16443c0bc790",
    "Registration": "5d0399c71cd5",
    "ResetLink": "1b5f895d6348",
    "ResetRequest": "bdc5244e5093",
    "StatusChange": "1b2e103e1921",
    "ThemeChange": "cb6916652de5",
    "VoiceEnrolment": "e40c59cd5d68",
    "VoiceProbe": "f4c67d2b2ead",
    "VoiceRecording": "44df7c8fecc9",
}


def test_the_routes_who_may_call_them_and_their_request_models():
    app = create_app(None, None, None)  # nothing in the state is used until a request arrives
    table, schemas = [], {}
    # The routes of the included routers too, which FastAPI keeps out of `app.routes` until a request needs them.
    for context in iter_route_contexts(app.routes):
        route = context.original_route
        if not isinstance(route, APIRoute):
            continue
        assert context.dependant.dependencies[0].call is policy, context.path
        models = [param.field_info.annotation for param in route.dependant.body_params]
        for model in models:
            schema = json.dumps(model.model_json_schema(), sort_keys=True).encode("utf-8")
            schemas[model.__name__] = hashlib.sha256(schema).hexdigest()[:12]
        for method in sorted(context.methods):
            table.append((method, context.path, route.name, route.status_code, tuple(sorted(route.endpoint.mbs_allow)),
                          route.endpoint.mbs_during_password_change, models[0].__name__ if models else None))
    assert sorted(table, key=lambda row: (row[1], row[0])) == ROUTES
    assert schemas == SCHEMAS
