"""The accounts database: accounts, identity links, sessions and the append-only audit log (H3, H12, H14)."""

import sqlalchemy as sa
from alembic import op

revision = "accounts_0001"
down_revision = None
branch_labels = None
depends_on = None

APPEND_ONLY = """
CREATE FUNCTION audit_log_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'the audit log only takes inserts (H12)';
END;
$$
"""


def upgrade() -> None:
    op.create_table(
        "account",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("username", sa.String(32), nullable=False),
        sa.Column("username_key", sa.String(32), nullable=False, unique=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("email_key", sa.String(254), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(200), nullable=False),
        sa.Column("role", sa.String(8), nullable=False),
        sa.Column("status", sa.String(8), nullable=False),
        sa.Column("must_change_password", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('user', 'admin')", name="account_role"),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="account_status"),
    )
    op.create_table(
        "identity_link",
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("account.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("national_id_hmac", sa.LargeBinary(32), nullable=False, unique=True),
        sa.Column("subject", sa.LargeBinary(), nullable=False),
    )
    op.create_table(
        "session",
        sa.Column("token_hash", sa.LargeBinary(32), primary_key=True),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("account.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_session_account_id", "session", ["account_id"])
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("administrator_id", sa.Uuid(), sa.ForeignKey("account.id"), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("target", sa.String(200), nullable=False),
    )
    op.execute(APPEND_ONLY)
    op.execute("CREATE TRIGGER audit_log_no_change BEFORE UPDATE OR DELETE ON audit_log "
               "FOR EACH ROW EXECUTE FUNCTION audit_log_append_only()")
    op.execute("CREATE TRIGGER audit_log_no_truncate BEFORE TRUNCATE ON audit_log "
               "FOR EACH STATEMENT EXECUTE FUNCTION audit_log_append_only()")


def downgrade() -> None:
    op.drop_table("audit_log")
    op.execute("DROP FUNCTION audit_log_append_only()")
    op.drop_index("ix_session_account_id", table_name="session")
    op.drop_table("session")
    op.drop_table("identity_link")
    op.drop_table("account")
