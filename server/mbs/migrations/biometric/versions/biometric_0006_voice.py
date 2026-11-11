"""H54: ECAPA-TDNN joins the algorithm table with its embedding model's SHA-256 as its version and SpeechBrain's
threshold (docs/data-model.md). Voice enrolments use the existing enrolment, sample and template tables."""

import sqlalchemy as sa
from alembic import op

revision = "biometric_0006"
down_revision = "biometric_0005"
branch_labels = None
depends_on = None

ECAPA_SHA256 = "0575cb64845e6b9a10db9bcb74d5ac32b326b8dc90352671d345e2ee3d0126a2"  # embedding_model.ckpt


def upgrade() -> None:
    algorithm = sa.table(
        "algorithm",
        sa.column("code", sa.String), sa.column("modality", sa.String), sa.column("version", sa.String),
        sa.column("threshold", sa.Double), sa.column("threshold_provisional", sa.Boolean),
        sa.column("threshold_origin", sa.String),
    )
    op.bulk_insert(algorithm, [
        {"code": "ecapa-voxceleb", "modality": "voice", "version": ECAPA_SHA256, "threshold": 0.25,
         "threshold_provisional": False, "threshold_origin": "SpeechBrain's verification threshold"},
    ])


def downgrade() -> None:
    op.execute("DELETE FROM algorithm WHERE code = 'ecapa-voxceleb'")
