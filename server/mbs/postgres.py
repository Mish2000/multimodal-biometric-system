"""The local PostgreSQL cluster (H19).

The cluster lives under the git-ignored local/, runs under the user's own account through pg_ctl (no
Windows service, so no administrator rights), listens on localhost only and takes SCRAM passwords
from the key file. Each of the two databases has its own login role and is closed to every other role.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import psycopg
from psycopg import sql

from .config import Config
from .keys import Keys

SUPERUSER = "postgres"
ACCOUNTS = "mbs_accounts"  # the accounts database and its role
BIOMETRIC = "mbs_biometric"  # the biometric database and its role
DATABASES = {ACCOUNTS: "accounts", BIOMETRIC: "biometric"}  # database -> its password in the key file

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# libpq's attempt at GSSAPI encryption crashes the process on this Windows build (seen on 2026-10-20 with
# libpq 18.6 from conda-forge); the cluster takes only SCRAM passwords on localhost, so it is switched off.
CONNECTION_OPTIONS = {"gssencmode": "disable"}


class PostgresError(RuntimeError):
    pass


def tool(config: Config, name: str) -> str:
    path = config.postgres_bin / f"{name}.exe"
    if not path.exists():
        raise PostgresError(f"{path} is missing: is the multimodal-postgres environment installed?")
    return str(path)


def initialized(config: Config) -> bool:
    return (config.data_dir / "PG_VERSION").exists()


def initialize(config: Config, keys: Keys) -> bool:
    """Create the cluster once; returns whether it was created now."""
    if initialized(config):
        return False
    config.data_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        password_file = Path(tmp) / "superuser"
        password_file.write_text(keys.database[SUPERUSER], encoding="utf-8")
        _run([tool(config, "initdb"), "-D", str(config.data_dir), "-U", SUPERUSER, "--pwfile", str(password_file),
              "--auth=scram-sha-256", "--encoding=UTF8", "--no-locale"])
    with open(config.data_dir / "postgresql.conf", "a", encoding="utf-8") as f:
        f.write("\n# The multimodal biometric system (H11, H19): localhost only, SCRAM passwords.\n"
                f"listen_addresses = 'localhost'\nport = {config.database_port}\n"
                "password_encryption = 'scram-sha-256'\n")
    return True


def running(config: Config) -> bool:
    status = subprocess.run([tool(config, "pg_ctl"), "-D", str(config.data_dir), "status"],
                            capture_output=True, creationflags=NO_WINDOW)
    return status.returncode == 0


def start(config: Config) -> bool:
    """Start the cluster unless it runs; returns whether it was started now."""
    if running(config):
        return False
    # No pipes: the server process that pg_ctl leaves behind would hold them open.
    done = subprocess.run([tool(config, "pg_ctl"), "-D", str(config.data_dir), "-l", str(config.postgres_log),
                           "-w", "-t", "60", "start"],
                          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          creationflags=NO_WINDOW)
    if done.returncode != 0:
        raise PostgresError(f"PostgreSQL did not start; see {config.postgres_log}")
    return True


def stop(config: Config) -> None:
    if running(config):
        _run([tool(config, "pg_ctl"), "-D", str(config.data_dir), "-m", "fast", "-w", "-t", "60", "stop"])


def connect(config: Config, keys: Keys, database: str = "postgres", role: str = SUPERUSER) -> psycopg.Connection:
    password = keys.database[SUPERUSER if role == SUPERUSER else DATABASES[role]]
    return psycopg.connect(host="127.0.0.1", port=config.database_port, dbname=database, user=role,
                           password=password, autocommit=True, connect_timeout=10, **CONNECTION_OPTIONS)


def bootstrap(config: Config, keys: Keys) -> None:
    """Create each database with its own login role, closed to everyone else, and pgvector in the
    biometric one (the extension needs the superuser). Safe to run again."""
    with connect(config, keys) as conn:
        for database, password_key in DATABASES.items():
            name = sql.Identifier(database)
            if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (database,)).fetchone():
                conn.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(name, sql.Literal(keys.database[password_key])))
            if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database,)).fetchone():
                conn.execute(sql.SQL("CREATE DATABASE {} OWNER {} ENCODING 'UTF8'").format(name, name))
            conn.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(name))
    with connect(config, keys, database=BIOMETRIC) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")


def _run(command: list[str]) -> None:
    done = subprocess.run(command, capture_output=True, text=True, creationflags=NO_WINDOW)
    if done.returncode != 0:
        raise PostgresError(f"{Path(command[0]).name} failed:\n{done.stderr or done.stdout}")
