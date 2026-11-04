"""The account's mobile phone (H29) and language (H31), and the links that reset a password (H32)."""

import sqlalchemy as sa
from alembic import op

revision = "accounts_0003"
down_revision = "accounts_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Accounts made before H29 have no phone, and administrators never get one.
    op.add_column("account", sa.Column("phone", sa.String(16), nullable=True))
    op.create_unique_constraint("account_phone_key", "account", ["phone"])
    op.add_column("account", sa.Column("language", sa.String(2), nullable=False, server_default="en"))
    op.create_check_constraint("account_language", "account", "language IN ('en', 'he')")
    op.create_table(
        "password_reset",
        sa.Column("token_hash", sa.LargeBinary(32), primary_key=True),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("account.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel", sa.String(8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("channel IN ('sms', 'email')", name="password_reset_channel"),
    )
    op.create_index("ix_password_reset_account_id", "password_reset", ["account_id"])


def downgrade() -> None:
    op.drop_index("ix_password_reset_account_id", table_name="password_reset")
    op.drop_table("password_reset")
    op.drop_constraint("account_language", "account", type_="check")
    op.drop_column("account", "language")
    op.drop_constraint("account_phone_key", "account", type_="unique")
    op.drop_column("account", "phone")
