"""The biometric database: subjects, named only by random identifiers (H3). pgvector is created by
mbs.postgres.bootstrap, since the extension needs the superuser."""

import sqlalchemy as sa
from alembic import op

revision = "biometric_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "subject",
        sa.Column("id", sa.Uuid(), primary_key=True),
    )


def downgrade() -> None:
    op.drop_table("subject")
