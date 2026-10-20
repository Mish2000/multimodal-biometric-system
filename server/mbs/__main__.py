"""The server's commands, run from server/ with the multimodal-server environment:

    python -m mbs setup                                    key file, local/server.toml, cluster, databases
    python -m mbs db start | stop | status
    python -m mbs create-admin --username NAME --email ADDRESS     prints a one-time password (H12)
    python -m mbs serve                                    the API on 127.0.0.1 (H11)
"""

from __future__ import annotations

import argparse
import sys

from . import accounts, config as settings, keys as keyring, postgres
from .db import migrate, open_databases


def setup(_args) -> None:
    if settings.LOCAL.exists():
        config = settings.load()
    else:
        config = settings.defaults()
        settings.write(config)
        print(f"wrote {settings.LOCAL}")
    if config.key_file.exists():
        keys = keyring.load(config.key_file)
    else:
        keys = keyring.create(config.key_file)
        print(f"created the key file {config.key_file}; only this Windows user can read it.\n"
              "Keep a backup copy of it somewhere safe: without it the stored data cannot be read.")
    if postgres.initialize(config, keys):
        print(f"created the PostgreSQL cluster in {config.data_dir}")
    started = postgres.start(config)
    try:
        postgres.bootstrap(config, keys)
        databases = open_databases(config, keys)
        migrate(databases)
        databases.dispose()
        print("the accounts and biometric databases are ready")
    finally:
        if started:
            postgres.stop(config)


def db(args) -> None:
    config = settings.load()
    if args.action == "start":
        postgres.start(config)
    elif args.action == "stop":
        postgres.stop(config)
    print("running" if postgres.running(config) else "stopped")


def create_admin(args) -> None:
    config = settings.load()
    keys = keyring.load(config.key_file)
    started = postgres.start(config)
    try:
        databases = open_databases(config, keys)
        try:
            one_time = accounts.first_administrator(databases, args.username, args.email)
        except accounts.AccountError as e:
            sys.exit(f"not created: {e.code}")
        finally:
            databases.dispose()
        print(f"administrator {args.username} created. One-time password (change it at the first sign-in):\n{one_time}")
    finally:
        if started:
            postgres.stop(config)


def serve(_args) -> None:
    import uvicorn

    from .api import create_app

    config = settings.load()
    keys = keyring.load(config.key_file)
    started = postgres.start(config)
    databases = open_databases(config, keys)
    try:
        uvicorn.run(create_app(databases, keys), host="127.0.0.1", port=config.server_port, log_level="info")
    finally:
        databases.dispose()
        if started:
            postgres.stop(config)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m mbs", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("setup").set_defaults(run=setup)
    database = commands.add_parser("db")
    database.add_argument("action", choices=["start", "stop", "status"])
    database.set_defaults(run=db)
    admin = commands.add_parser("create-admin")
    admin.add_argument("--username", required=True)
    admin.add_argument("--email", required=True)
    admin.set_defaults(run=create_admin)
    commands.add_parser("serve").set_defaults(run=serve)
    args = parser.parse_args(argv)
    args.run(args)


if __name__ == "__main__":
    main()
