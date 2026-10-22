"""The account's look, chosen in the client's settings: Windows' setting, light or dark (H24)."""

import sqlalchemy as sa
from alembic import op

revision = "accounts_0002"
down_revision = "accounts_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("account", sa.Column("theme", sa.String(8), nullable=False, server_default="system"))
    op.create_check_constraint("account_theme", "account", "theme IN ('system', 'light', 'dark')")


def downgrade() -> None:
    op.drop_constraint("account_theme", "account", type_="check")
    op.drop_column("account", "theme")
