"""Machine-specific settings, kept in the git-ignored local/server.toml (H11, H14, H19, H33).

The repository is public, so none of its files holds a local path: `python -m mbs setup` writes
this file with this machine's defaults, and it can be edited afterwards. The fingerprint settings are
optional: without them the server runs, and fingerprint enrolment answers that it is unavailable.
"""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]
LOCAL = REPOSITORY / "local" / "server.toml"
RESEARCH_LOCAL = REPOSITORY / "local" / "research.toml"  # the research link's machine paths (H10)
SCANNER_EXE = REPOSITORY / "scanner" / "ScannerCapture" / "bin" / "Release" / "net48" / "ScannerCapture.exe"
NFIQ2_BIN = REPOSITORY / "local" / "nfiq2" / "2.3.0-fix" / "bin"


@dataclass(frozen=True)
class Config:
    postgres_bin: Path  # Library/bin of the multimodal-postgres environment (H19)
    data_dir: Path  # the PostgreSQL cluster, under local/
    database_port: int
    key_file: Path  # outside the repository (H14)
    server_port: int
    scanner_driver_dir: Path | None = None  # the supplied OEM 3.3 driver folder (H8)
    scanner_exe: Path = SCANNER_EXE  # ScannerCapture, built from scanner/ (H33)
    nfiq2_bin: Path | None = None  # NFIQ 2.3.0 built with NIST's fix (engines/README.md, H33)

    @property
    def postgres_log(self) -> Path:
        return self.data_dir.parent / "postgres.log"


def defaults() -> Config:
    """This machine's defaults: the database environment next to the server's, the key file in the
    user's local application data."""
    environments = Path(sys.prefix).parent
    appdata = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return Config(
        postgres_bin=environments / "multimodal-postgres" / "Library" / "bin",
        data_dir=REPOSITORY / "local" / "postgres" / "data",
        database_port=55432,
        key_file=appdata / "multimodal-biometric-system" / "keys.json",
        server_port=55433,
        nfiq2_bin=NFIQ2_BIN if (NFIQ2_BIN / "Nfiq2Api.dll").exists() else None,
    )


def _path(value: str | None) -> Path | None:
    return Path(value) if value else None


def load(path: Path = LOCAL) -> Config:
    with open(path, "rb") as f:
        values = tomllib.load(f)
    data_dir = Path(values["data_dir"])
    return Config(
        postgres_bin=Path(values["postgres_bin"]),
        data_dir=data_dir if data_dir.is_absolute() else REPOSITORY / data_dir,
        database_port=int(values["database_port"]),
        key_file=Path(values["key_file"]),
        server_port=int(values["server_port"]),
        scanner_driver_dir=_path(values.get("scanner_driver_dir")),
        scanner_exe=_path(values.get("scanner_exe")) or SCANNER_EXE,
        nfiq2_bin=_path(values.get("nfiq2_bin")),
    )


def write(config: Config, path: Path = LOCAL) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Machine-specific settings of the server (server/README.md); git-ignored.",
        f'postgres_bin = "{config.postgres_bin.as_posix()}"',
        f'data_dir = "{config.data_dir.as_posix()}"',
        f"database_port = {config.database_port}",
        f'key_file = "{config.key_file.as_posix()}"',
        f"server_port = {config.server_port}",
        "# Fingerprint enrolment (H33): the scanner's driver folder and the NFIQ 2 build.",
        f'scanner_driver_dir = "{config.scanner_driver_dir.as_posix()}"' if config.scanner_driver_dir
        else '# scanner_driver_dir = "<the supplied fx_hs_windows_10_driver_v3.3 folder>"',
        f'nfiq2_bin = "{config.nfiq2_bin.as_posix()}"' if config.nfiq2_bin
        else '# nfiq2_bin = "<the folder with Nfiq2Api.dll and nist_plain_tir-ink.yaml>"',
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def research_python() -> Path | None:
    """The research project environment's python.exe, which runs the OpenCV SIFT and quality engines."""
    if not RESEARCH_LOCAL.exists():
        return None
    with open(RESEARCH_LOCAL, "rb") as f:
        value = tomllib.load(f).get("project_python")
    return Path(value) if value else None
