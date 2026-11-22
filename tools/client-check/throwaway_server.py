"""A throwaway server for the client's end-to-end check, made as the server's tests make theirs
(server/tests/conftest.py): its own PostgreSQL cluster, keys held only in memory and free ports, never the
real cluster or key file. Run with the multimodal-server environment:

    python tools/client-check/throwaway_server.py RUN_DIR

It writes RUN_DIR/server.json (the address, the first administrator's one-time password and the outbox of
H32, RUN_DIR/outbox), serves until
RUN_DIR/stop appears or 15 minutes pass, then stops its cluster and removes it."""

from __future__ import annotations

import json
import os
import shutil
import socket
import sys
import threading
import time
from dataclasses import replace
from datetime import UTC
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))

import uvicorn  # noqa: E402

from mbs import accounts, postgres  # noqa: E402
from mbs import config as settings
from mbs import keys as keyring
from mbs.api import create_app  # noqa: E402
from mbs.db import migrate, open_databases  # noqa: E402
from mbs.outbox import Outbox  # noqa: E402


def seed_face(databases, keys, username: str) -> None:
    """H51: a face enrolment of synthetic numbers for the check's account (no image of a person: each sample is
    one grey pixel, each embedding random), saved by the server's own save, so that the check reaches the 1:1
    and 1:N camera screens."""
    import random
    import struct
    import zlib
    from datetime import datetime, timedelta

    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from mbs import face as face_module
    from mbs.models import Account, Algorithm

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    grey = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)) \
        + chunk(b"IDAT", zlib.compress(b"\x00\x80")) + chunk(b"IEND", b"")
    with Session(databases.accounts) as db:
        account = db.scalar(select(Account).where(Account.username == username))
    subject = accounts.subject_of(databases, keys, account.id)
    with Session(databases.biometric) as db:
        version = db.get(Algorithm, "sface").version
    rng, now = random.Random(51), datetime.now(UTC)
    chosen = [(placement, face_module.Extracted(1, 1, [], [], png=grey, embedding=[rng.gauss(0, 1) for _ in range(128)]),
               now - timedelta(seconds=10 * (4 - placement))) for placement in (1, 2, 3)]
    face_module._save(databases, keys, subject, chosen, version)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def check_fingerprints(run: Path, config):
    """H33: with MBS_CHECK_CAPTURES (a git-ignored folder of ScannerCapture's captures), the real NFIQ 2 and OpenCV SIFT engines
    and a scanner that hands over the three stored placements of the left index; nothing is written."""
    folder = os.environ.get("MBS_CHECK_CAPTURES")
    if not folder:
        return None
    from mbs.engines import Engine, Scanner, conda_environment
    from mbs.fingerprint import FingerprintService

    python = settings.research_python()
    script = run / "scanner.json"
    steps = []
    for file in sorted(Path(folder).glob("*_f07_p*.png")):
        steps += [{"wait": "finger", "file": str(file)}, {"wait": "lift"}]
    script.write_text(json.dumps(steps[:-1]), encoding="utf-8")
    fakes = settings.REPOSITORY / "server" / "tests" / "fakes"
    engines, env = settings.REPOSITORY / "engines", conda_environment(python)
    service = FingerprintService(
        scanner=Scanner([sys.executable, str(fakes / "fake_scanner.py"), "--script", str(script)]),
        quality=Engine("nfiq2", [str(python), "-I", str(engines / "nfiq2_quality.py"), str(config.nfiq2_bin)], env),
        sift=Engine("opencv-sift", [str(python), "-I", str(engines / "opencv_sift.py")], env),
    )
    identify_methods = os.environ.get("MBS_CHECK_IDENTIFY_METHODS")
    if os.environ.get("MBS_CHECK_PORE") or identify_methods:
        # Start from the H35 enrolment shape, then enable the new method so the UI must prepare it.
        (run / "enable-pore").unlink(missing_ok=True)
        pore_python = settings.pore_python()
        def enable_pore():
            deadline = time.monotonic() + 300
            while not (run / "enable-pore").exists():
                if (run / "stop").exists() or time.monotonic() >= deadline:
                    return
                time.sleep(0.1)
            service.pore = Engine("pore-sift", [str(pore_python), "-I", "-B", str(engines / "pore_sift.py"), str(python)],
                                  conda_environment(pore_python))
            if os.environ.get("MBS_CHECK_LEARNED") or identify_methods:
                learned = settings.learned_python()
                service.learned = Engine("learned-pore", [str(learned), "-I", "-B", str(engines / "learned_pore.py")],
                                         conda_environment(learned))
        threading.Thread(target=enable_pore, daemon=True).start()
    return service


def main() -> None:
    run = Path(sys.argv[1]).resolve()
    cluster = run / "cluster"
    if cluster.exists():
        sys.exit(f"{cluster} exists: another check is running, or one did not finish")
    run.mkdir(parents=True, exist_ok=True)
    stop, described = run / "stop", run / "server.json"
    stop.unlink(missing_ok=True)
    described.unlink(missing_ok=True)
    base = settings.load() if settings.LOCAL.exists() else settings.defaults()
    config = replace(base, data_dir=cluster / "data", database_port=free_port(),
                     key_file=cluster / "never-written-keys.json", server_port=free_port())
    keys = keyring.Keys.generate()
    postgres.initialize(config, keys)
    postgres.start(config)
    try:
        postgres.bootstrap(config, keys)
        databases = open_databases(config, keys)
        try:
            fingerprints = faces = voices = None
            migrate(databases)
            one_time = accounts.first_administrator(databases, "admin", "admin@example.com")
            outbox = run / "outbox"
            shutil.rmtree(outbox, ignore_errors=True)
            fingerprints = check_fingerprints(run, config)
            if os.environ.get("MBS_CHECK_FACE"):
                # H48: the real face engine, in the face environment, with the pinned models of local/models/face.
                from mbs import face as face_module
                faces, missing = face_module.from_config(config)
                assert faces is not None, missing
            if os.environ.get("MBS_CHECK_VOICE"):
                # H54: the real voice engine, in the voice environment, with the pinned model of local/models/voice.
                from mbs import voice as voice_module
                voices, missing = voice_module.from_config(config)
                assert voices is not None, missing
            if fingerprints is not None and os.environ.get("MBS_CHECK_IDENTIFY"):
                # H41: a second test account supplies a separate, anonymous gallery candidate.
                import anyio

                from mbs import fingerprint
                gallery_account = accounts.register(databases, keys, "gallery-user", "gallery@example.org",
                                                    "0527654321", "Gallery password 1", "123456782")
                gallery_subject = accounts.subject_of(databases, keys, gallery_account.id)
                scanner_script = run / "scanner.json"
                initial_steps = scanner_script.read_bytes()
                gallery_steps = []
                for file in sorted(Path(os.environ["MBS_CHECK_CAPTURES"]).glob("*_f02_p*.png")):
                    gallery_steps += [{"wait": "finger", "file": str(file)}, {"wait": "lift"}]
                assert len(gallery_steps) == 6
                scanner_script.write_text(json.dumps(gallery_steps[:-1]), encoding="utf-8")
                async def enrol_gallery():
                    events = [event async for event in fingerprint.enrol(fingerprints, databases, keys, gallery_subject, 2)]
                    assert events[-1]["type"] == "saved", events[-1]
                anyio.run(enrol_gallery)
                scanner_script.write_bytes(initial_steps)
            server = uvicorn.Server(uvicorn.Config(create_app(databases, keys, Outbox(outbox), fingerprints, faces, voices), host="127.0.0.1",
                                                   port=config.server_port, log_level="info"))

            def watch() -> None:
                deadline = time.monotonic() + (30 if os.environ.get("MBS_CHECK_SHOTS") else 15) * 60
                while not stop.exists() and time.monotonic() < deadline:
                    time.sleep(0.5)
                server.should_exit = True

            threading.Thread(target=watch, daemon=True).start()

            def seed_faces() -> None:
                # H51: the check writes RUN_DIR/seed-face with a username; the answer is RUN_DIR/seed-face.done.
                request, done = run / "seed-face", run / "seed-face.done"
                while not stop.exists():
                    if request.exists() and not done.exists():
                        try:
                            seed_face(databases, keys, request.read_text(encoding="utf-8").strip())
                            done.write_text("ok", encoding="utf-8")
                        except Exception as error:  # reported to the check, which fails on it
                            done.write_text(f"failed: {error!r}", encoding="utf-8")
                    time.sleep(0.3)

            if faces is not None:
                (run / "seed-face").unlink(missing_ok=True)
                (run / "seed-face.done").unlink(missing_ok=True)
                threading.Thread(target=seed_faces, daemon=True).start()
            described.write_text(json.dumps({"url": f"http://127.0.0.1:{config.server_port}",
                                             "administrator": "admin", "one_time_password": one_time,
                                             "outbox": str(outbox), "fingerprint": fingerprints is not None,
                                             "face": faces is not None, "voice": voices is not None}),
                                 encoding="utf-8")
            server.run()
        finally:
            if fingerprints is not None:
                fingerprints.close()
            if faces is not None:
                faces.close()
            if voices is not None:
                voices.close()
            databases.dispose()
    finally:
        postgres.stop(config)
        shutil.rmtree(cluster, ignore_errors=True)
        described.unlink(missing_ok=True)
        print("stopped and removed the throwaway cluster", flush=True)


if __name__ == "__main__":
    main()
