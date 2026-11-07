"""Completed comparisons and their sealed probes (H25, H27, H35)."""

import sqlalchemy as sa
from alembic import op

revision = "biometric_0003"
down_revision = "biometric_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "attempt",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("subject_id", sa.Uuid(), sa.ForeignKey("subject.id"), nullable=False),
        sa.Column("modality", sa.String(12), nullable=False),
        sa.Column("mode", sa.String(8), nullable=False),
        sa.Column("algorithm", sa.String(32), sa.ForeignKey("algorithm.code"), nullable=False),
        sa.Column("weight_opencv_sift", sa.SmallInteger()),
        sa.Column("weight_learned_pore", sa.SmallInteger()),
        sa.Column("weight_pore_sift", sa.SmallInteger()),
        sa.Column("enrolment_id", sa.Uuid(), sa.ForeignKey("enrolment.id", ondelete="CASCADE")),
        sa.Column("top_enrolment_id", sa.Uuid(), sa.ForeignKey("enrolment.id")),
        sa.Column("gallery_size", sa.Integer()),
        sa.Column("score", sa.Double(), nullable=False),
        sa.Column("threshold", sa.Double(), nullable=False),
        sa.Column("accepted", sa.Boolean(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(8), nullable=False, server_default="device"),
        sa.Column("probe", sa.LargeBinary(), nullable=False),
        sa.CheckConstraint("modality IN ('fingerprint', 'face', 'voice')", name="attempt_modality"),
        sa.CheckConstraint("mode IN ('verify', 'identify')", name="attempt_mode"),
        sa.CheckConstraint("source IN ('device', 'file') AND (modality <> 'fingerprint' OR source = 'device')",
                           name="attempt_source"),
        sa.CheckConstraint("(mode = 'verify' AND enrolment_id IS NOT NULL AND top_enrolment_id IS NULL AND gallery_size IS NULL)"
                           " OR (mode = 'identify' AND enrolment_id IS NULL AND gallery_size IS NOT NULL AND gallery_size >= 0)", name="attempt_target"),
        sa.CheckConstraint("duration_ms >= 0", name="attempt_duration"),
        sa.CheckConstraint("accepted = (score > threshold)", name="attempt_decision"),
        sa.CheckConstraint("(algorithm = 'fusion' AND weight_opencv_sift BETWEEN 0 AND 100"
                           " AND weight_learned_pore BETWEEN 0 AND 100 AND weight_pore_sift BETWEEN 0 AND 100"
                           " AND weight_opencv_sift + weight_learned_pore + weight_pore_sift = 100"
                           " AND num_nonnulls(weight_opencv_sift, weight_learned_pore, weight_pore_sift) = 3)"
                           " OR (algorithm <> 'fusion' AND num_nonnulls(weight_opencv_sift, weight_learned_pore, weight_pore_sift) = 0)",
                           name="attempt_weights"),
    )
    op.create_index("ix_attempt_at", "attempt", ["at"])
    op.create_index("ix_attempt_subject_at", "attempt", ["subject_id", "at"])
    op.create_index("ix_attempt_enrolment_id", "attempt", ["enrolment_id"])


def downgrade() -> None:
    op.drop_table("attempt")
