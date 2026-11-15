"""The offscreen check of the built client against a throwaway server (H26): python tools/client-check/run.py NAME

Run it from the repository root with the multimodal-server environment, after `npm run build` in client/. Without
options it checks what needs no engine: registration, sign-in, password recovery, settings, both languages and
themes, and the administration. The options add the engines, each found as the server finds it (local/server.toml):

    --captures DIR    stored ScannerCapture captures of one person: the fingerprint engines and the scanner's
                      stand-in, which hands them over (the left index, f07, and other fingers, f02 and f04)
    --identify        with --captures: a second account's enrolment for 1:N (H41)
    --pore, --learned, --match-view, --identify-methods   with --captures: the pore methods and the drawings
    --face            the face engine and its models, with Chromium's synthetic camera (H48)
    --voice           the voice engine and its model, with the synthetic recordings of voice_files.py (H54, H57)
    --page URL        the development server's page instead of the built one (dev_server.mts)

Everything it writes goes to the git-ignored local/client-check/: NAME-server.log, NAME-check.log, shots-NAME/
(screenshots, which show the stored captures when --captures is given) and run-NAME/ (the throwaway cluster, removed
at the end). It never touches the real cluster or key file.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / "tools" / "client-check"
OUT = ROOT / "local" / "client-check"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
FLAGS = {"identify": "MBS_CHECK_IDENTIFY", "pore": "MBS_CHECK_PORE", "learned": "MBS_CHECK_LEARNED",
         "match_view": "MBS_CHECK_MATCH_VIEW", "identify_methods": "MBS_CHECK_IDENTIFY_METHODS",
         "face": "MBS_CHECK_FACE", "voice": "MBS_CHECK_VOICE"}


def tail(path: Path, lines: int = 40) -> str:
    return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]) if path.exists() else ""


def voice_recordings(folder: Path) -> Path:
    """The synthetic recordings, made by the voice environment's Python, which has numpy, scipy and soundfile."""
    sys.path.insert(0, str(ROOT / "server"))
    from mbs import config as settings

    config = settings.load() if settings.LOCAL.exists() else settings.defaults()
    python = config.voice_python
    if python is None or not python.exists():
        sys.exit("--voice needs the multimodal-voice environment (voice_python)")
    environment = python.parent
    path = os.pathsep.join(str(environment / part) for part in
                           ("", "Library/mingw-w64/bin", "Library/usr/bin", "Library/bin", "Scripts", "bin"))
    subprocess.run([str(python), "-I", str(HERE / "voice_files.py"), str(folder)], check=True,
                   env={**os.environ, "PATH": path + os.pathsep + os.environ["PATH"]}, creationflags=NO_WINDOW)
    return folder / "voice-synthetic.wav"


def electron_program() -> str:
    """Electron's own program, as its package finds it: since Electron 44 the package downloads it, checked against
    its checksums, the first time it is needed rather than when npm installs the package."""
    found = subprocess.run(["node", "-e", "process.stdout.write('ELECTRON=' + require('electron'))"],
                           cwd=ROOT / "client", capture_output=True, text=True, check=True, creationflags=NO_WINDOW)
    return found.stdout.rsplit("ELECTRON=", 1)[1].strip()  # after what a first download prints


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # the logs hold Hebrew; a console's code page may not
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("name")
    parser.add_argument("--captures", type=Path)
    for flag in FLAGS:
        parser.add_argument(f"--{flag.replace('_', '-')}", action="store_true")
    parser.add_argument("--page")
    args = parser.parse_args()

    run, shots = OUT / f"run-{args.name}", OUT / f"shots-{args.name}"
    server_log, check_log = OUT / f"{args.name}-server.log", OUT / f"{args.name}-check.log"
    run.mkdir(parents=True, exist_ok=True)
    for stale in ("server.json", "stop"):
        (run / stale).unlink(missing_ok=True)
    env = {name: value for name, value in os.environ.items() if not name.startswith("MBS_CHECK_")}
    for flag, variable in FLAGS.items():
        if getattr(args, flag):
            env[variable] = "1"
    if args.captures is not None:
        env["MBS_CHECK_CAPTURES"] = str(args.captures.resolve())
    if args.voice:
        env["MBS_CHECK_VOICE_WAV"] = str(voice_recordings(run / "voice"))

    with open(server_log, "w", encoding="utf-8") as log:
        server = subprocess.Popen([sys.executable, str(HERE / "throwaway_server.py"), str(run)], env=env, stdout=log,
                                  stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
    deadline = time.monotonic() + 600  # the cluster, and with --identify a second account's enrolment
    while not (run / "server.json").exists():
        if server.poll() is not None or time.monotonic() > deadline:
            (run / "stop").touch()
            server.wait(60)
            print("the throwaway server did not start\n" + tail(server_log))
            return 1
        time.sleep(0.5)

    command = [electron_program(), str(HERE / "check.mts"), str(ROOT / "client"), str(run), str(shots)]
    try:
        with open(check_log, "w", encoding="utf-8") as log:
            status = subprocess.run(command + ([args.page] if args.page else []), env=env, stdout=log,
                                    stderr=subprocess.STDOUT, timeout=600, creationflags=NO_WINDOW).returncode
    except subprocess.TimeoutExpired:
        status = 1
    finally:
        (run / "stop").touch()
        try:
            server.wait(120)
        except subprocess.TimeoutExpired:
            server.kill()
    print(tail(check_log, 3 if status == 0 else 40))
    if status != 0:
        print("--- the throwaway server's log\n" + tail(server_log))
    return status


if __name__ == "__main__":
    sys.exit(main())
