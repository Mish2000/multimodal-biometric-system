"""Who may call a route (H12). Every route declares it with `allow`, and `policy`, the application's own dependency,
checks the declaration on every request: a route without one is refused (deny by default), and the role is checked
here whatever the client shows."""

from __future__ import annotations

from fastapi import Request

from .. import accounts
from ..accounts import AccountError, SignedIn

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
