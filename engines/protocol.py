"""The engines' messages on standard input and output (H13): one line of JSON, then its binary data.

The line holds `length`, the number of bytes that follow it (0 when none), and, when the data has
several parts (two templates to compare), `parts` with their lengths in order. Standard library only,
so any research environment can run an engine without new packages.
"""

from __future__ import annotations

import json
import sys
from typing import BinaryIO, Callable

MAX_LINE = 1 << 16
MAX_DATA = 64 << 20


class ProtocolError(RuntimeError):
    """A message that does not follow the format."""


def write_message(stream: BinaryIO, header: dict, data: bytes | list[bytes] = b"") -> None:
    parts = data if isinstance(data, list) else [data]
    header = {**header, "length": sum(len(p) for p in parts)}
    if isinstance(data, list):
        header["parts"] = [len(p) for p in parts]
    stream.write(json.dumps(header, separators=(",", ":")).encode("utf-8") + b"\n")
    for part in parts:
        stream.write(part)
    stream.flush()


def read_message(stream: BinaryIO) -> tuple[dict, list[bytes]] | None:
    """The next message as its header and its parts (one part unless the header lists several); None at the
    end of the stream."""
    line = stream.readline(MAX_LINE + 1)
    if not line:
        return None
    if len(line) > MAX_LINE or not line.endswith(b"\n"):
        raise ProtocolError("a message line is too long or cut off")
    header = json.loads(line)
    length = int(header.get("length", 0))
    if not 0 <= length <= MAX_DATA:
        raise ProtocolError(f"a message announces {length} bytes")
    data = read_exactly(stream, length)
    sizes = header.get("parts", [length])
    if sum(sizes) != length or any(size < 0 for size in sizes):
        raise ProtocolError("the parts do not add up to the length")
    parts, start = [], 0
    for size in sizes:
        parts.append(data[start:start + size])
        start += size
    return header, parts


def read_exactly(stream: BinaryIO, length: int) -> bytes:
    chunks, left = [], length
    while left:
        chunk = stream.read(left)
        if not chunk:
            raise ProtocolError("the stream ended inside a message")
        chunks.append(chunk)
        left -= len(chunk)
    return b"".join(chunks)


Handler = Callable[[dict, list[bytes]], tuple[dict, bytes | list[bytes]]]


def serve(ready: dict, handlers: dict[str, Handler]) -> None:
    """Answer requests until the server closes standard input. Nothing else may reach standard output, so
    print() and library messages are sent to standard error."""
    out, source = sys.stdout.buffer, sys.stdin.buffer
    sys.stdout = sys.stderr
    write_message(out, {"ok": True, **ready})
    def answer(message):
        # H39: request-local variables are released before waiting for the next message.
        header, parts = message
        handler = handlers.get(header.get("op", ""))
        if handler is None:
            write_message(out, {"ok": False, "error": "unknown_operation"})
            return
        try:
            reply, data = handler(header, parts)
        except Exception as error:  # the engine keeps serving; the server decides what a failure means
            write_message(out, {"ok": False, "error": type(error).__name__, "detail": str(error)[:300]})
            return
        write_message(out, {"ok": True, **reply}, data)

    while True:
        message = read_message(source)
        if message is None:
            return
        try:
            answer(message)
        finally:
            del message
