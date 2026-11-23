"""H60: the combined test of every enrolled modality. A versioned policy (weights, the evidence they share, the score's
threshold and each modality's calibration), the combined tests, and the link of each comparison to its test with the
evidence it gave. H6's fusion of the three fingerprint methods is replaced: its weight columns and its `fusion` method,
never used by an attempt, are removed, so every method now has a threshold."""

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "biometric_0008"
down_revision = "biometric_0007"
branch_labels = None
depends_on = None

RESEARCH_COMMIT = "606c8d33a7a27570b5bb55cca8248259b9b6ba8a"

# The first policy, as H60 describes it: weights 55, 25 and 20 share an evidence of six orders of magnitude, so each
# modality's log10 likelihood ratio is capped at 0.06 x its weight; the score is accepted above 75, a combined
# likelihood ratio above 1,000.
CALIBRATION = {
    "fingerprint": {
        "form": "log1p", "a": -5.5696, "b": 2.1718, "provisional": False,
        "origin": "OpenCV SIFT on SD302 plain vs plain development pairs (626 same finger, 61,974 different people)",
    },
    "face": {
        "form": "linear", "k": 38.8, "t": 0.363, "provisional": True,
        "origin": "SFace: 99.60 % on LFW at 0.363 (OpenCV), equal-variance normal scores",
    },
    "voice": {
        "form": "linear", "k": 46.4, "t": 0.25, "provisional": True,
        "origin": "ECAPA-TDNN: EER 0.80 % on VoxCeleb1-O (its model card), equal-variance normal scores",
    },
}


def upgrade() -> None:
    policy = op.create_table(
        "fusion_policy",
        sa.Column("id", sa.SmallInteger(), primary_key=True, autoincrement=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("weight_fingerprint", sa.SmallInteger(), nullable=False),
        sa.Column("weight_face", sa.SmallInteger(), nullable=False),
        sa.Column("weight_voice", sa.SmallInteger(), nullable=False),
        sa.Column("budget", sa.Double(), nullable=False),
        sa.Column("threshold", sa.Double(), nullable=False),
        sa.Column("calibration", JSONB(), nullable=False),
        sa.Column("origin", sa.String(200), nullable=False),
        sa.CheckConstraint("weight_fingerprint BETWEEN 0 AND 100 AND weight_face BETWEEN 0 AND 100"
                           " AND weight_voice BETWEEN 0 AND 100 AND weight_fingerprint + weight_face + weight_voice = 100",
                           name="fusion_policy_weights"),
        sa.CheckConstraint("budget > 0 AND threshold > 0 AND threshold < 100", name="fusion_policy_values"),
    )
    op.bulk_insert(policy, [{
        "id": 1, "created_at": datetime.now(UTC), "weight_fingerprint": 55, "weight_face": 25, "weight_voice": 20,
        "budget": 6.0, "threshold": 75.0, "calibration": CALIBRATION,
        "origin": "H60: likelihood ratios, each capped by its weight; accepted above a combined ratio of 1,000",
    }])
    op.create_table(
        "fused_attempt",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("subject_id", sa.Uuid(), sa.ForeignKey("subject.id"), nullable=False),
        sa.Column("mode", sa.String(8), nullable=False),
        sa.Column("policy_id", sa.SmallInteger(), sa.ForeignKey("fusion_policy.id"), nullable=False),
        sa.Column("fingerprint_enrolment_id", sa.Uuid(), sa.ForeignKey("enrolment.id", ondelete="CASCADE"), nullable=True),
        sa.Column("face_enrolment_id", sa.Uuid(), sa.ForeignKey("enrolment.id", ondelete="CASCADE"), nullable=True),
        sa.Column("voice_enrolment_id", sa.Uuid(), sa.ForeignKey("enrolment.id", ondelete="CASCADE"), nullable=True),
        sa.Column("gallery_size", sa.Integer(), nullable=True),
        sa.Column("score", sa.Double(), nullable=False),
        sa.Column("threshold", sa.Double(), nullable=False),
        sa.Column("accepted", sa.Boolean(), nullable=False),
        sa.Column("evidence", sa.Double(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.CheckConstraint("mode IN ('verify', 'identify')", name="fused_attempt_mode"),
        sa.CheckConstraint("(mode = 'verify' AND fingerprint_enrolment_id IS NOT NULL AND gallery_size IS NULL)"
                           " OR (mode = 'identify' AND num_nonnulls(fingerprint_enrolment_id, face_enrolment_id,"
                           " voice_enrolment_id) = 0 AND gallery_size >= 1)", name="fused_attempt_target"),
        sa.CheckConstraint("accepted = (score > threshold)", name="fused_attempt_decision"),
        sa.CheckConstraint("duration_ms >= 0", name="fused_attempt_duration"),
    )
    op.create_index("ix_fused_attempt_at", "fused_attempt", ["at"])
    op.create_index("ix_fused_attempt_subject_at", "fused_attempt", ["subject_id", "at"])
    for column in ("fingerprint_enrolment_id", "face_enrolment_id", "voice_enrolment_id"):
        op.create_index(f"ix_fused_attempt_{column}", "fused_attempt", [column])
    op.add_column("attempt", sa.Column("fused_attempt_id", sa.Uuid(), nullable=True))
    op.add_column("attempt", sa.Column("evidence", sa.Double(), nullable=True))
    op.create_foreign_key("attempt_fused_attempt_id_fkey", "attempt", "fused_attempt",
                          ["fused_attempt_id"], ["id"], ondelete="CASCADE")
    op.create_index("ix_attempt_fused_attempt_id", "attempt", ["fused_attempt_id"])
    op.create_check_constraint("attempt_fused", "attempt", "(fused_attempt_id IS NULL) = (evidence IS NULL)")
    # H6's fusion of the fingerprint methods is replaced; no attempt ever used it.
    op.drop_constraint("attempt_weights", "attempt", type_="check")
    for column in ("weight_opencv_sift", "weight_learned_pore", "weight_pore_sift"):
        op.drop_column("attempt", column)
    op.execute("DELETE FROM algorithm WHERE code = 'fusion'")
    op.drop_constraint("algorithm_threshold", "algorithm", type_="check")
    op.alter_column("algorithm", "threshold", existing_type=sa.Double(), nullable=False)


def downgrade() -> None:
    op.alter_column("algorithm", "threshold", existing_type=sa.Double(), nullable=True)
    op.create_check_constraint("algorithm_threshold", "algorithm", "threshold IS NOT NULL OR code = 'fusion'")
    op.execute(sa.text("INSERT INTO algorithm (code, modality, version, threshold, threshold_provisional, threshold_origin)"
                       " VALUES ('fusion', 'fingerprint', :version, NULL, true, 'H16''s rule, from H10''s saved scores')")
               .bindparams(version=RESEARCH_COMMIT))
    for column in ("weight_opencv_sift", "weight_learned_pore", "weight_pore_sift"):
        op.add_column("attempt", sa.Column(column, sa.SmallInteger(), nullable=True))
    op.create_check_constraint(
        "attempt_weights", "attempt",
        "(algorithm = 'fusion' AND weight_opencv_sift BETWEEN 0 AND 100"
        " AND weight_learned_pore BETWEEN 0 AND 100 AND weight_pore_sift BETWEEN 0 AND 100"
        " AND weight_opencv_sift + weight_learned_pore + weight_pore_sift = 100"
        " AND num_nonnulls(weight_opencv_sift, weight_learned_pore, weight_pore_sift) = 3)"
        " OR (algorithm <> 'fusion' AND num_nonnulls(weight_opencv_sift, weight_learned_pore, weight_pore_sift) = 0)")
    # The comparisons of combined tests go with them: the schema before H60 has no place for their link.
    op.execute("DELETE FROM attempt WHERE fused_attempt_id IS NOT NULL")
    op.drop_constraint("attempt_fused", "attempt", type_="check")
    op.drop_index("ix_attempt_fused_attempt_id", table_name="attempt")
    op.drop_constraint("attempt_fused_attempt_id_fkey", "attempt", type_="foreignkey")
    op.drop_column("attempt", "evidence")
    op.drop_column("attempt", "fused_attempt_id")
    op.drop_table("fused_attempt")
    op.drop_table("fusion_policy")
