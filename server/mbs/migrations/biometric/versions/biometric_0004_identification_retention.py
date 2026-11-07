"""H41: retain identification attempts and probes when their leading enrolment is deleted."""

from alembic import op

revision = "biometric_0004"
down_revision = "biometric_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("attempt_top_enrolment_id_fkey", "attempt", type_="foreignkey")
    op.create_foreign_key("attempt_top_enrolment_id_fkey", "attempt", "enrolment",
                          ["top_enrolment_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_attempt_top_enrolment_id", "attempt", ["top_enrolment_id"])


def downgrade() -> None:
    op.drop_index("ix_attempt_top_enrolment_id", table_name="attempt")
    op.drop_constraint("attempt_top_enrolment_id_fkey", "attempt", type_="foreignkey")
    op.create_foreign_key("attempt_top_enrolment_id_fkey", "attempt", "enrolment",
                          ["top_enrolment_id"], ["id"])
