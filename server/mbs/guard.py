"""H58: what reaches the API at all. The server listens on 127.0.0.1 only (H11), yet a web page open in any browser
on this PC can send it requests, and through DNS rebinding can do so under a host name of its own. So before any
route runs, a request must be addressed to one of this PC's own names, and its body may not be larger than its route
can use. The body is checked by its declared length and again while it arrives, and is read into memory only within
the limit; the route then gets exactly the body that was read.

FastAPI 0.142.2 offers no body limit per route, and Starlette's own limit answers in plain text, so this one layer
does both checks and answers as every route does, with {"error": code}."""

from __future__ import annotations

import json
import logging

from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("mbs.guard")
HOSTS = frozenset({"127.0.0.1", "localhost"})
BODY_LIMIT = 64 << 10  # a route's body unless it takes images or recordings


class Guard:
    """Refuses a request to another host (400 invalid_host) or a body larger than its route's limit (413
    body_too_large) before the application sees it."""

    def __init__(self, app: ASGIApp, limits: dict[str, int], hosts: frozenset[str] = HOSTS,
                 default: int = BODY_LIMIT) -> None:
        self.app, self.limits, self.hosts, self.default = app, limits, hosts, default

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope["headers"])
        host = host_name(headers.get(b"host"))
        if host not in self.hosts:
            logger.warning("refused a request addressed to another host (%.80r)", host)
            await refuse(send, 400, "invalid_host")
            return
        limit = self.limits.get(scope["path"], self.default)
        declared = headers.get(b"content-length", b"")
        if declared.isdigit() and int(declared) > limit:
            await self.too_large(scope, send, limit)
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return  # the client went away before its body ended
            body += message.get("body", b"")
            if len(body) > limit:
                await self.too_large(scope, send, limit)
                return
            if not message.get("more_body", False):
                break
        pending: list[Message] = [{"type": "http.request", "body": bytes(body), "more_body": False}]

        async def replay() -> Message:
            return pending.pop() if pending else await receive()

        await self.app(scope, replay, send)

    @staticmethod
    async def too_large(scope: Scope, send: Send, limit: int) -> None:
        logger.warning("refused a body larger than %d bytes for %.80r", limit, scope["path"])
        await refuse(send, 413, "body_too_large")


def host_name(value: bytes | None) -> str | None:
    """A Host header's name without its port, in lower case; None when it is missing or not ASCII."""
    if not value:
        return None
    try:
        text = value.decode("ascii").strip().lower()
    except UnicodeDecodeError:
        return None
    if text.startswith("["):  # an IPv6 address, which this server never listens on
        return text.partition("]")[0] + "]"
    return text.rpartition(":")[0] if ":" in text else text


async def refuse(send: Send, status: int, code: str) -> None:
    body = json.dumps({"error": code}).encode("ascii")
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode("ascii"))]})
    await send({"type": "http.response.body", "body": body})
