"""Alembic environment of the accounts database; the engine comes from mbs.db.migrate."""

from alembic import context

from mbs.models import AccountsBase

engine = context.config.attributes["engine"]
with engine.begin() as connection:
    context.configure(connection=connection, target_metadata=AccountsBase.metadata)
    with context.begin_transaction():
        context.run_migrations()
