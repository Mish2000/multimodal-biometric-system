"""H58: only requests addressed to this PC's own names reach the API, and a body larger than its route takes is
refused before any route runs: by its declared length, or while it arrives without one."""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi.routing import APIRoute, iter_route_contexts

from mbs import api, face
from mbs.guard import BODY_LIMIT, Guard, host_name

from test_api import error

JSON = {"content-type": "application/json"}


def test_requests_to_another_host_are_refused(client, caplog):
    assert client.get("/api/health").json() == {"status": "ok"}
    for host in ("localhost", "127.0.0.1:55433", "LOCALHOST:55433"):
        assert client.get("/api/health", headers={"host": host}).status_code == 200, host
    with caplog.at_level(logging.WARNING, logger="mbs.guard"):
        for host in ("rebound.example", "rebound.example:55433", "127.0.0.1.rebound.example", "[::1]:55433"):
            response = client.post("/api/login", json={"login": "michael", "password": "x"}, headers={"host": host})
            assert error(response) == (400, "invalid_host"), host
    assert "refused a request addressed to another host ('rebound.example')" in caplog.text


def test_host_names_are_read_without_their_port():
    assert host_name(b"127.0.0.1:55433") == "127.0.0.1"
    assert host_name(b"LocalHost") == "localhost"
    assert host_name(b"[::1]:55433") == "[::1]"
    assert host_name(b"") is None and host_name(None) is None and host_name(b"\xff") is None


def test_a_body_larger_than_its_route_takes_is_refused_before_the_route(client):
    at_limit = b"x" * BODY_LIMIT
    assert client.post("/api/login", content=at_limit, headers=JSON).status_code == 422  # the route's own answer
    assert error(client.post("/api/login", content=at_limit + b"x", headers=JSON)) == (413, "body_too_large")


def test_the_largest_image_file_still_reaches_its_route(client):
    limit = api.BODY_LIMITS["/api/face/verifications"]
    image = "A" * ((face.FILE_BYTES + 2) // 3 * 4)  # a file of 10 MB in base64, the most the route's model takes
    body = json.dumps({"image": image, "source": "file"}).encode("ascii")
    assert len(body) <= limit
    assert error(client.post("/api/face/verifications", content=body, headers=JSON)) == (401, "not_signed_in")
    response = client.post("/api/face/verifications", content=b"x" * (limit + 1), headers=JSON)
    assert error(response) == (413, "body_too_large")


def test_every_larger_limit_names_a_route_of_the_api(client):
    posts = {route.path for route in iter_route_contexts(client.app.routes)
             if isinstance(route.original_route, APIRoute) and "POST" in route.methods}
    assert set(api.BODY_LIMITS) <= posts
    assert all(limit > BODY_LIMIT for limit in api.BODY_LIMITS.values())


def guarded(limit: int, chunks: list[bytes], disconnect: bool = False) -> tuple[list, list]:
    """One request to a guarded application, its body in `chunks` without a declared length: what the application
    received and what was sent back."""
    messages = [{"type": "http.request", "body": chunk, "more_body": index < len(chunks) - 1 or disconnect}
                for index, chunk in enumerate(chunks)]
    if disconnect:
        messages.append({"type": "http.disconnect"})
    reached, sent = [], []

    async def app(scope, receive, send):
        reached.append(await receive())
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive():
        return messages.pop(0)

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "path": "/upload", "headers": [(b"host", b"127.0.0.1:55433")]}
    asyncio.run(Guard(app, {"/upload": limit})(scope, receive, send))
    return reached, sent


def test_a_body_without_its_length_is_counted_as_it_arrives():
    reached, sent = guarded(10, [b"12345", b"67890"])
    assert reached == [{"type": "http.request", "body": b"1234567890", "more_body": False}]
    assert sent[0]["status"] == 204
    reached, sent = guarded(10, [b"123456", b"78901"])
    assert reached == [] and sent[0]["status"] == 413 and json.loads(sent[1]["body"]) == {"error": "body_too_large"}
    reached, sent = guarded(10, [b"12345"], disconnect=True)
    assert reached == [] and sent == []
