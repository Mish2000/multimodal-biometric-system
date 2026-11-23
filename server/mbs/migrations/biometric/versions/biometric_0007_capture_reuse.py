"""H59: a fingerprint attempt may compare again, with another method, the capture of an earlier attempt of the
same person. It keeps its own sealed copy of that capture and names the attempt that took it."""

import sqlalchemy as sa
from alembic import op

revision = "biometric_0007"
down_revision = "biometric_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("attempt", sa.Column("capture_attempt_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("attempt_capture_attempt_id_fkey", "attempt", "attempt",
                          ["capture_attempt_id"], ["id"], ondelete="SET NULL")
    op.create_check_constraint("attempt_capture", "attempt",
                               "capture_attempt_id IS NULL OR (modality = 'fingerprint' AND capture_attempt_id <> id)")


def downgrade() -> None:
    op.drop_constraint("attempt_capture", "attempt", type_="check")
    op.drop_constraint("attempt_capture_attempt_id_fkey", "attempt", type_="foreignkey")
    op.drop_column("attempt", "capture_attempt_id")
