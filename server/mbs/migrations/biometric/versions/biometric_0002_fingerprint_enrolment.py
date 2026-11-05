"""Fingerprint enrolment (H6, H15, H25, H33): the algorithms with their thresholds (H16), enrolments, their
findings (sealed captures) and the templates every method makes from them. Built exactly as in
docs/data-model.md; the attempt table follows with verification (1:1)."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "biometric_0002"
down_revision = "biometric_0001"
branch_labels = None
depends_on = None

RESEARCH_COMMIT = "606c8d33a7a27570b5bb55cca8248259b9b6ba8a"  # methods/research-pin.toml (H10)


def upgrade() -> None:
    algorithm = op.create_table(
        "algorithm",
        sa.Column("code", sa.String(32), primary_key=True),
        sa.Column("modality", sa.String(12), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("threshold", sa.Double(), nullable=True),
        sa.Column("threshold_provisional", sa.Boolean(), nullable=False),
        sa.Column("threshold_origin", sa.String(120), nullable=False),
        sa.Column("threshold_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("modality IN ('fingerprint', 'face', 'voice')", name="algorithm_modality"),
        sa.CheckConstraint("threshold IS NOT NULL OR code = 'fusion'", name="algorithm_threshold"),
    )
    # H16's initial values; face and voice join with their pinned model files (increments 4 and 5).
    op.bulk_insert(algorithm, [
        {"code": "opencv-sift", "modality": "fingerprint", "version": RESEARCH_COMMIT, "threshold": 57,
         "threshold_provisional": False, "threshold_origin": "SD302 plain vs plain, FAR 0.1 % (RxJ)"},
        {"code": "pore-sift", "modality": "fingerprint", "version": RESEARCH_COMMIT, "threshold": 37,
         "threshold_provisional": True, "threshold_origin": "the highest H10 different-finger score"},
        {"code": "learned-pore", "modality": "fingerprint", "version": RESEARCH_COMMIT, "threshold": 21,
         "threshold_provisional": True, "threshold_origin": "the highest H10 different-finger score"},
        {"code": "fusion", "modality": "fingerprint", "version": RESEARCH_COMMIT, "threshold": None,
         "threshold_provisional": True, "threshold_origin": "H16's rule, from H10's saved scores"},
    ])
    op.create_table(
        "enrolment",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("subject_id", sa.Uuid(), sa.ForeignKey("subject.id"), nullable=False),
        sa.Column("modality", sa.String(12), nullable=False),
        sa.Column("finger", sa.SmallInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("replaced_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("modality IN ('fingerprint', 'face', 'voice')", name="enrolment_modality"),
        sa.CheckConstraint("(modality = 'fingerprint') = (finger IS NOT NULL) AND (finger IS NULL OR finger BETWEEN 1 AND 10)",
                           name="enrolment_finger"),
    )
    op.create_index("ix_enrolment_subject_id", "enrolment", ["subject_id"])
    # One current enrolment per subject, modality and finger (NULLS NOT DISTINCT: face and voice have none).
    op.execute("CREATE UNIQUE INDEX enrolment_current ON enrolment (subject_id, modality, finger) NULLS NOT DISTINCT "
               "WHERE replaced_at IS NULL")
    op.create_table(
        "sample",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("enrolment_id", sa.Uuid(), sa.ForeignKey("enrolment.id"), nullable=False),
        sa.Column("placement", sa.SmallInteger(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("media_type", sa.String(16), nullable=False),
        sa.Column("width", sa.SmallInteger(), nullable=True),
        sa.Column("height", sa.SmallInteger(), nullable=True),
        sa.Column("ppi", sa.SmallInteger(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("checks", JSONB(), nullable=True),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.UniqueConstraint("enrolment_id", "placement", name="sample_placement"),
        sa.CheckConstraint("placement >= 1", name="sample_placement_from_1"),
    )
    op.create_table(
        "template",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("sample_id", sa.Uuid(), sa.ForeignKey("sample.id"), nullable=False),
        sa.Column("algorithm", sa.String(32), sa.ForeignKey("algorithm.code"), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=True),
        sa.UniqueConstraint("sample_id", "algorithm", name="template_per_algorithm"),
    )
    # pgvector's type (mbs.postgres.bootstrap creates the extension): face and voice embeddings, unsealed (H14).
    op.execute("ALTER TABLE template ADD COLUMN embedding vector")
    op.create_check_constraint("template_one_value", "template", "num_nonnulls(data, embedding) = 1")


def downgrade() -> None:
    op.drop_table("template")
    op.drop_table("sample")
    op.execute("DROP INDEX enrolment_current")
    op.drop_index("ix_enrolment_subject_id", table_name="enrolment")
    op.drop_table("enrolment")
    op.drop_table("algorithm")
