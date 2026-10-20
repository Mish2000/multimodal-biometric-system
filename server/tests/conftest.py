"""A throwaway PostgreSQL cluster from the multimodal-postgres environment, migrated once, and a fresh copy
of both databases for every test (from template databases), so tests never share data."""

from __future__ import annotations

import socket
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from mbs import config as settings
from mbs import keys as keyring
from mbs import postgres
from mbs.api import create_app
from mbs.db import migrate, open_databases


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def cluster(tmp_path_factory):
    base = settings.load() if settings.LOCAL.exists() else settings.defaults()
    config = replace(base, data_dir=tmp_path_factory.mktemp("postgres") / "data", database_port=free_port(),
                     key_file=tmp_path_factory.mktemp("keys") / "keys.json", server_port=0)
    keys = keyring.Keys.generate()
    postgres.initialize(config, keys)
    postgres.start(config)
    try:
        postgres.bootstrap(config, keys)
        databases = open_databases(config, keys)
        migrate(databases)
        databases.dispose()
        with postgres.connect(config, keys) as conn:
            for name in postgres.DATABASES:
                conn.execute(sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(sql.Identifier(f"{name}_template"),
                                                                              sql.Identifier(name)))
        yield config, keys
    finally:
        postgres.stop(config)


@pytest.fixture
def keys(cluster):
    return cluster[1]


@pytest.fixture
def config(cluster):
    return cluster[0]


@pytest.fixture
def databases(cluster):
    config, keys = cluster
    with postgres.connect(config, keys) as conn:
        for name in postgres.DATABASES:
            database = sql.Identifier(name)
            conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(database))
            conn.execute(sql.SQL("CREATE DATABASE {} TEMPLATE {} OWNER {}").format(
                database, sql.Identifier(f"{name}_template"), database))
            conn.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(database))
    opened = open_databases(config, keys)
    yield opened
    opened.dispose()


@pytest.fixture
def client(databases, keys):
    with TestClient(create_app(databases, keys)) as test_client:
        yield test_client
