"""The server's child processes (H13, H33): the engines and the scanner's acquisition mode.

An engine is a long-running process that answers one request at a time on its standard input and output
in the format of engines/protocol.py (a line of JSON with `length` and, for several parts, `parts`, then
the bytes). It loads its method once and keeps nothing between requests. The scanner's acquisition mode
(`ScannerCapture oem-acquire`) runs once per wait; the server is its watchdog and stops it when its
deadline passes or the enrolment is cancelled. No child process opens a window.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .config import REPOSITORY

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
MAX_LINE = 1 << 16
MAX_DATA = 64 << 20


class EngineError(RuntimeError):
    """An engine could not start, failed a request or broke the protocol."""


class ScannerError(RuntimeError):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code


def conda_environment(python: Path) -> dict[str, str]:
    """What `conda activate` puts first on PATH, as methods/research_link.py's environment(): without it the
    research environments' compiled libraries do not load."""
    root = python.parent
    first = [root, root / "Library" / "mingw-w64" / "bin", root / "Library" / "usr" / "bin", root / "Library" / "bin",
             root / "Scripts", root / "bin"]
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join([str(p) for p in first] + [env.get("PATH", "")])
    return env


def write_message(stream, header: dict, parts: list[bytes]) -> None:
    header = {**header, "length": sum(len(p) for p in parts)}
    if len(parts) > 1:
        header["parts"] = [len(p) for p in parts]
    stream.write(json.dumps(header, separators=(",", ":")).encode("utf-8") + b"\n")
    for part in parts:
        stream.write(part)
    stream.flush()


def read_exactly(stream, length: int) -> bytes:
    chunks, left = [], length
    while left:
        chunk = stream.read(left)
        if not chunk:
            raise EngineError("the process ended inside a message")
        chunks.append(chunk)
        left -= len(chunk)
    return b"".join(chunks)


def read_message(stream) -> tuple[dict, list[bytes]]:
    line = stream.readline(MAX_LINE + 1)
    if not line:
        raise EngineError("the process ended")
    if len(line) > MAX_LINE or not line.endswith(b"\n"):
        raise EngineError("a message line is too long or cut off")
    header = json.loads(line)
    length = int(header.get("length", 0))
    if not 0 <= length <= MAX_DATA:
        raise EngineError(f"a message announces {length} bytes")
    data = read_exactly(stream, length)
    sizes = header.get("parts", [length])
    if sum(sizes) != length:
        raise EngineError("the parts do not add up to the length")
    parts, start = [], 0
    for size in sizes:
        parts.append(data[start:start + size])
        start += size
    return header, parts


class Engine:
    """One engine process, started when first needed and again after it failed."""

    def __init__(self, name: str, command: list[str], env: dict[str, str] | None = None,
                 start_timeout: float = 90, request_timeout: float = 60):
        self.name, self.command, self.env = name, command, env
        self.start_timeout, self.request_timeout = start_timeout, request_timeout
        self.ready: dict | None = None
        self._process: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def _start(self) -> None:
        self._process = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=None,
                                         env=self.env, cwd=REPOSITORY, creationflags=NO_WINDOW)
        header, _ = self._guarded(lambda: read_message(self._process.stdout), self.start_timeout)
        if not header.get("ok"):
            raise EngineError(f"{self.name} did not start: {header}")
        self.ready = header

    def _guarded(self, work: Callable, seconds: float):
        process = self._process
        timer = threading.Timer(seconds, process.kill)
        timer.start()
        try:
            return work()
        except (OSError, ValueError, EngineError) as error:
            self._stop()
            raise EngineError(f"{self.name}: {error}") from error
        finally:
            timer.cancel()

    def start(self) -> dict:
        with self._lock:
            if self._process is None or self._process.poll() is not None:
                self._start()
            return self.ready

    def request(self, header: dict, parts: list[bytes]) -> tuple[dict, list[bytes]]:
        with self._lock:
            if self._process is None or self._process.poll() is not None:
                self._start()

            def exchange():
                write_message(self._process.stdin, header, parts)
                return read_message(self._process.stdout)

            reply, data = self._guarded(exchange, self.request_timeout)
            if not reply.get("ok"):
                raise EngineError(f"{self.name} refused {header.get('op')}: {reply.get('error')} {reply.get('detail', '')}")
            return reply, data

    def _stop(self) -> None:
        process, self._process, self.ready = self._process, None, None
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()

    def close(self) -> None:
        with self._lock:
            process, self._process = self._process, None
            if process is not None and process.poll() is None:
                process.stdin.close()
                try:
                    process.wait(10)
                except subprocess.TimeoutExpired:
                    process.kill()


@dataclass
class ScannerRun:
    """The scanner's current run, so that a cancelled enrolment can stop it."""

    process: subprocess.Popen | None = None
    cancelled: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def cancel(self) -> None:
        with self._lock:
            self.cancelled = True
            if self.process is not None and self.process.poll() is None:
                self.process.kill()


class Scanner:
    """`ScannerCapture oem-acquire` (H33): one checked image of a placed finger, or the moment it is lifted.
    A run that fails with OEM status 110 is tried once more (H9: 2 of 32 runs, each fine when asked again)."""

    def __init__(self, command: list[str]):
        self.command = command  # the executable, `oem-acquire` and `--driver-dir DIR`

    def acquire(self, wait: str, timeout_s: int, on_event: Callable[[dict], None], run: ScannerRun) -> tuple[dict, bytes | None]:
        for attempt in (1, 2):
            code, result, error = self._once(wait, timeout_s, on_event, run)
            if run.cancelled:
                raise ScannerError("cancelled")
            if code == 0 and result is not None:
                return result
            if code == 3:
                raise ScannerError("no_finger" if wait == "finger" else "not_lifted")
            if attempt == 1 and "OEM status 110" in error:
                continue
            if "Another native scanner command" in error:
                raise ScannerError("scanner_busy", error)
            raise ScannerError("scanner_failed", error.strip()[-300:])
        raise ScannerError("scanner_failed")

    def _once(self, wait: str, timeout_s: int, on_event, run: ScannerRun):
        command = [*self.command, "--wait", wait, "--timeout-s", str(timeout_s)]
        with run._lock:
            if run.cancelled:
                return 1, None, ""
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       cwd=REPOSITORY, creationflags=NO_WINDOW)
            run.process = process
        errors: list[bytes] = []
        reader = threading.Thread(target=lambda: errors.append(process.stderr.read()), daemon=True)
        reader.start()
        timer = threading.Timer(timeout_s + 15, process.kill)  # the watchdog of a hung native call (H8)
        timer.start()
        result = None
        try:
            while True:
                line = process.stdout.readline(MAX_LINE + 1)
                if not line:
                    break
                header = json.loads(line)
                event = header.get("event")
                if event == "image":
                    result = header, read_exactly(process.stdout, int(header["length"]))
                elif event == "lifted":
                    result = header, None
                elif event != "timeout":
                    on_event(header)
        except (ValueError, EngineError):
            process.kill()
        finally:
            code = process.wait()
            timer.cancel()
            reader.join(5)
            with run._lock:
                run.process = None
        return code, result, b"".join(errors).decode("utf-8", "replace")
