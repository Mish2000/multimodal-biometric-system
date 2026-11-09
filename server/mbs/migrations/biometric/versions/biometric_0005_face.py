"""H48: SFace joins the algorithm table with its model file's SHA-256 as its version and OpenCV's threshold
(docs/data-model.md). Face enrolments use the existing enrolment, sample and template tables."""

import sqlalchemy as sa
from alembic import op

revision = "biometric_0005"
down_revision = "biometric_0004"
branch_labels = None
depends_on = None

SFACE_SHA256 = "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79"  # face_recognition_sface_2021dec.onnx


def upgrade() -> None:
    algorithm = sa.table(
        "algorithm",
        sa.column("code", sa.String), sa.column("modality", sa.String), sa.column("version", sa.String),
        sa.column("threshold", sa.Double), sa.column("threshold_provisional", sa.Boolean),
        sa.column("threshold_origin", sa.String),
    )
    op.bulk_insert(algorithm, [
        {"code": "sface", "modality": "face", "version": SFACE_SHA256, "threshold": 0.363,
         "threshold_provisional": False, "threshold_origin": "OpenCV's SFace sample, cosine similarity"},
    ])


def downgrade() -> None:
    op.execute("DELETE FROM algorithm WHERE code = 'sface'")
