"""Connections to the two databases (H4), each through its own role, and their migrations (Alembic,
one history per database under mbs/migrations/)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import URL, Engine, create_engine

from . import postgres
from .config import Config
from .keys import Keys

MIGRATIONS = Path(__file__).parent / "migrations"


@dataclass(frozen=True)
class Databases:
    accounts: Engine
    biometric: Engine

    def dispose(self) -> None:
        self.accounts.dispose()
        self.biometric.dispose()


def url(config: Config, keys: Keys, database: str) -> URL:
    return URL.create("postgresql+psycopg", username=database, password=keys.database[postgres.DATABASES[database]],
                      host="127.0.0.1", port=config.database_port, database=database,
                      query=postgres.CONNECTION_OPTIONS)


def open_databases(config: Config, keys: Keys) -> Databases:
    return Databases(
        accounts=create_engine(url(config, keys, postgres.ACCOUNTS), pool_pre_ping=True),
        biometric=create_engine(url(config, keys, postgres.BIOMETRIC), pool_pre_ping=True),
    )


def migrate(databases: Databases) -> None:
    """Bring both databases to their latest schema."""
    for name, engine in (("accounts", databases.accounts), ("biometric", databases.biometric)):
        alembic = AlembicConfig()
        alembic.set_main_option("script_location", str(MIGRATIONS / name))
        alembic.attributes["engine"] = engine
        command.upgrade(alembic, "head")
