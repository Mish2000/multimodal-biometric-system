"""Alembic environment of the biometric database; the engine comes from mbs.db.migrate."""

from alembic import context

from mbs.models import BiometricBase

engine = context.config.attributes["engine"]
with engine.begin() as connection:
    context.configure(connection=connection, target_metadata=BiometricBase.metadata)
    with context.begin_transaction():
        context.run_migrations()
