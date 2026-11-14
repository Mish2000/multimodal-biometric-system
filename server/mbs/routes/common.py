"""What the routes of every area share: the application's state as dependencies (set by create_app in mbs/api.py),
and the sizes of request bodies that carry images or recordings (H58)."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from ..accounts import Throttle
from ..db import Databases
from ..keys import Keys
from ..outbox import Outbox

JSON_AROUND = 1 << 10  # room for the JSON around one image or recording in a request body (H58)


def base64_length(size: int) -> int:
    return (size + 2) // 3 * 4


async def _databases(request: Request) -> Databases:
    return request.app.state.databases


async def _keys(request: Request) -> Keys:
    return request.app.state.keys


async def _outbox(request: Request) -> Outbox:
    return request.app.state.outbox


async def _throttle(request: Request) -> Throttle:
    return request.app.state.throttle


DatabasesDep = Annotated[Databases, Depends(_databases)]
KeysDep = Annotated[Keys, Depends(_keys)]
OutboxDep = Annotated[Outbox, Depends(_outbox)]
ThrottleDep = Annotated[Throttle, Depends(_throttle)]
