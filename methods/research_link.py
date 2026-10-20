"""Pinned, checked link to the research repository (H10, H21).

The system uses the research's fingerprint methods from a local checkout instead of copying them.
Before anything runs, the checkout must descend from the pinned commit, and every tracked file outside
its documentation (AGENTS.md, README.md, docs/) must be the pinned commit's, committed or not (H21);
the research artefacts outside its git must match their pinned SHA-256, and the `fpl3` package a
research environment imports must come from that checkout. Machine paths live in the git-ignored
local/research.toml; the pin itself is methods/research-pin.toml. Standard library only, so any of
the research environments can import this module.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parents[1]
PIN = SYSTEM_ROOT / "methods" / "research-pin.toml"
LOCAL = SYSTEM_ROOT / "local" / "research.toml"

# H21: the research repository's documentation may change after the pinned commit without a new pin.
DOCUMENTATION_FILES = frozenset({"AGENTS.md", "README.md"})
DOCUMENTATION_FOLDERS = ("docs/",)


class LinkError(RuntimeError):
    """The research checkout or its artefacts differ from the pin; nothing may run."""


@dataclass(frozen=True)
class Link:
    repository: Path
    commit: str
    files: dict[str, tuple[Path, str]]  # name -> (absolute path, pinned SHA-256)
    thresholds: dict[str, dict[str, float]]  # FAR 0.1 %: method -> scenario -> accept if score above
    project_python: Path
    gpu_python: Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load(pin: Path = PIN, local: Path = LOCAL) -> Link:
    if not local.exists():
        raise LinkError(f"{local} is missing: it names the research checkout and environments on this machine")
    with open(pin, "rb") as f:
        pinned = tomllib.load(f)
    with open(local, "rb") as f:
        paths = tomllib.load(f)
    repository = Path(paths["repository"])
    return Link(
        repository=repository,
        commit=pinned["repository"]["commit"],
        files={name: (repository / entry["path"], entry["sha256"]) for name, entry in pinned["files"].items()},
        thresholds={method: dict(values) for method, values in pinned["thresholds"]["0.1%"].items()},
        project_python=Path(paths["project_python"]),
        gpu_python=Path(paths["gpu_python"]),
    )


def git(repository: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repository), *args], capture_output=True, text=True, check=True).stdout.strip()


def is_documentation(path: str) -> bool:
    return path in DOCUMENTATION_FILES or path.startswith(DOCUMENTATION_FOLDERS)


def verify(link: Link) -> None:
    """Refuse to run unless the checkout's code and every pinned artefact are exactly the pinned ones."""
    descends = subprocess.run(["git", "-C", str(link.repository), "merge-base", "--is-ancestor", link.commit, "HEAD"],
                              capture_output=True, text=True)
    if descends.returncode != 0:
        head = git(link.repository, "rev-parse", "HEAD")
        raise LinkError(f"the research checkout at {head} does not descend from the pinned commit {link.commit}")
    # The working tree against the pinned commit; without renames, a file moved into docs/ still shows
    # as removed from where it was.
    diff = git(link.repository, "diff", "--name-only", "--no-renames", link.commit, "--")
    changed = [path for path in diff.splitlines() if not is_documentation(path)]
    if changed:
        raise LinkError("tracked research files outside the documentation differ from the pinned commit:\n"
                        + "\n".join(changed))
    for name, (path, expected) in link.files.items():
        if not path.exists():
            raise LinkError(f"pinned research file {name} is missing: {path}")
        if sha256(path) != expected:
            raise LinkError(f"pinned research file {name} differs from its SHA-256: {path}")
    verify_thresholds(link)


def verify_thresholds(link: Link) -> None:
    """The pinned thresholds must be the plain vs plain report's operational values at FAR 0.1 %."""
    report = json.loads(link.files["plain_thresholds"][0].read_text(encoding="utf-8"))
    for method, scenarios in link.thresholds.items():
        for scenario, value in scenarios.items():
            actual = report["scenarios"][scenario]["methods"][method]["operational"]["0.1%"]["accept_if_score_above"]
            if actual != value:
                raise LinkError(f"{method} {scenario}: the pin says {value}, the report says {actual}")


def verify_package(link: Link, package_file: str) -> None:
    """The imported research package must be the pinned checkout's (an editable install of it)."""
    source = (link.repository / "src").resolve()
    if source not in Path(package_file).resolve().parents:
        raise LinkError(f"fpl3 is imported from {package_file}, not from the pinned checkout {source}")


def environment(python: Path) -> dict[str, str]:
    """The process environment with what `conda activate` puts first on PATH for this environment, so its
    compiled libraries load (without it, numpy's linear algebra fails to load in these environments)."""
    root = python.parent
    first = [root, root / "Library" / "mingw-w64" / "bin", root / "Library" / "usr" / "bin",
             root / "Library" / "bin", root / "Scripts", root / "bin"]
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join([str(p) for p in first] + [env.get("PATH", "")])
    return env
