"""Machine-specific settings, kept in the git-ignored local/server.toml (H11, H14, H19).

The repository is public, so none of its files holds a local path: `python -m mbs setup` writes
this file with this machine's defaults, and it can be edited afterwards.
"""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]
LOCAL = REPOSITORY / "local" / "server.toml"


@dataclass(frozen=True)
class Config:
    postgres_bin: Path  # Library/bin of the multimodal-postgres environment (H19)
    data_dir: Path  # the PostgreSQL cluster, under local/
    database_port: int
    key_file: Path  # outside the repository (H14)
    server_port: int

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
    )


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
    )


def write(config: Config, path: Path = LOCAL) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Machine-specific settings of the server (server/README.md); git-ignored.\n"
        f'postgres_bin = "{config.postgres_bin.as_posix()}"\n'
        f'data_dir = "{config.data_dir.as_posix()}"\n'
        f"database_port = {config.database_port}\n"
        f'key_file = "{config.key_file.as_posix()}"\n'
        f"server_port = {config.server_port}\n",
        encoding="utf-8",
    )
