"""The tables of the two databases (docs/specification.md, section 4; H3, H12, H14).

The databases share no key: only the sealed identity link in the accounts database leads to a subject
in the biometric one. The biometric database names people only by random subject identifiers and keeps
no creation time for them, so its rows cannot be matched to accounts by when they were made.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, DateTime, Double, ForeignKey, Identity, Index, Integer,
                        LargeBinary, SmallInteger, String, UniqueConstraint, Uuid, text)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql.base import ischema_names
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import UserDefinedType

USER, ADMIN = "user", "admin"
ACTIVE, DISABLED = "active", "disabled"
THEMES = ("system", "light", "dark")  # the account's look: Windows' setting, light or dark (H24)
LANGUAGES = ("en", "he")  # the client's language: English, the default, or Hebrew (H31)
SMS, EMAIL = "sms", "email"  # where a link to reset a password is sent (H32)


class Vector(UserDefinedType):
    """pgvector's `vector`, of any length (face and voice embeddings, H14); no Python package is needed for it."""

    cache_ok = True

    def get_col_spec(self, **kw) -> str:
        return "vector"


ischema_names["vector"] = Vector  # so that reading the schema back knows the type too


class AccountsBase(DeclarativeBase):
    pass


class BiometricBase(DeclarativeBase):
    pass


class Account(AccountsBase):
    """A user account (registered with the national ID) or a separate administrator account (H12)."""

    __tablename__ = "account"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'admin')", name="account_role"),
        CheckConstraint("status IN ('active', 'disabled')", name="account_status"),
        CheckConstraint("theme IN ('system', 'light', 'dark')", name="account_theme"),
        CheckConstraint("language IN ('en', 'he')", name="account_language"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    username: Mapped[str] = mapped_column(String(32))
    username_key: Mapped[str] = mapped_column(String(32), unique=True)  # case-folded, for uniqueness and sign-in
    email: Mapped[str] = mapped_column(String(254))
    email_key: Mapped[str] = mapped_column(String(254), unique=True)
    phone: Mapped[str | None] = mapped_column(String(16), unique=True)  # E.164; user accounts only (H29)
    password_hash: Mapped[str] = mapped_column(String(200))  # Argon2id, PHC string
    role: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(8))
    must_change_password: Mapped[bool] = mapped_column(Boolean)
    theme: Mapped[str] = mapped_column(String(8), server_default="system")
    language: Mapped[str] = mapped_column(String(2), server_default="en")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IdentityLink(AccountsBase):
    """Only for user accounts: the national ID's HMAC and the sealed subject identifier (H3)."""

    __tablename__ = "identity_link"

    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("account.id", ondelete="CASCADE"), primary_key=True)
    national_id_hmac: Mapped[bytes] = mapped_column(LargeBinary(32), unique=True)
    subject: Mapped[bytes] = mapped_column(LargeBinary)


class Session(AccountsBase):
    """A sign-in: the token itself is never stored, only its SHA-256 (H14)."""

    __tablename__ = "session"

    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), primary_key=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("account.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PasswordReset(AccountsBase):
    """A link that lets a signed-out account choose a new password (H32). As with sessions, only the
    token's SHA-256 is stored; a link works once, for 30 minutes, and only an account's newest one works."""

    __tablename__ = "password_reset"
    __table_args__ = (CheckConstraint("channel IN ('sms', 'email')", name="password_reset_channel"),)

    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), primary_key=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("account.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuditEntry(AccountsBase):
    """An administrative change (H12). The table only takes inserts: a trigger refuses updates,
    deletes and truncation."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    administrator_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("account.id"))
    action: Mapped[str] = mapped_column(String(40))
    target: Mapped[str] = mapped_column(String(200))


class Subject(BiometricBase):
    """A person in the biometric database: a random identifier and nothing else (H3)."""

    __tablename__ = "subject"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)


class Algorithm(BiometricBase):
    """A method and its threshold (H16): a comparison is accepted when its score is above the threshold."""

    __tablename__ = "algorithm"
    __table_args__ = (
        CheckConstraint("modality IN ('fingerprint', 'face', 'voice')", name="algorithm_modality"),
        CheckConstraint("threshold IS NOT NULL OR code = 'fusion'", name="algorithm_threshold"),
    )

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    modality: Mapped[str] = mapped_column(String(12))
    version: Mapped[str] = mapped_column(String(64))
    threshold: Mapped[float | None] = mapped_column(Double)
    threshold_provisional: Mapped[bool] = mapped_column(Boolean)
    threshold_origin: Mapped[str] = mapped_column(String(120))
    threshold_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Enrolment(BiometricBase):
    """One finger, the face or the voice of one subject (H6, H15). A new enrolment of the same finger replaces
    the old one, which stays with its findings (replaced_at)."""

    __tablename__ = "enrolment"
    __table_args__ = (
        CheckConstraint("modality IN ('fingerprint', 'face', 'voice')", name="enrolment_modality"),
        CheckConstraint("(modality = 'fingerprint') = (finger IS NOT NULL) AND (finger IS NULL OR finger BETWEEN 1 AND 10)",
                        name="enrolment_finger"),
        # One current enrolment per subject, modality and finger; face and voice have no finger.
        Index("enrolment_current", "subject_id", "modality", "finger", unique=True,
              postgresql_where=text("replaced_at IS NULL"), postgresql_nulls_not_distinct=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    subject_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("subject.id"), index=True)
    modality: Mapped[str] = mapped_column(String(12))
    finger: Mapped[int | None] = mapped_column(SmallInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    replaced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Sample(BiometricBase):
    """A finding: one raw capture, sealed (label mbs/sample/v1, bound to the sample and its subject, H25)."""

    __tablename__ = "sample"
    __table_args__ = (
        UniqueConstraint("enrolment_id", "placement", name="sample_placement"),
        CheckConstraint("placement >= 1", name="sample_placement_from_1"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    enrolment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("enrolment.id"))
    placement: Mapped[int] = mapped_column(SmallInteger)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    media_type: Mapped[str] = mapped_column(String(16))
    width: Mapped[int | None] = mapped_column(SmallInteger)
    height: Mapped[int | None] = mapped_column(SmallInteger)
    ppi: Mapped[int | None] = mapped_column(SmallInteger)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    checks: Mapped[list | None] = mapped_column(JSONB)
    data: Mapped[bytes] = mapped_column(LargeBinary)


class Template(BiometricBase):
    """What one method made of one finding (H6). Fingerprint templates are sealed (label mbs/template/v1,
    bound to the template, its subject and its algorithm, H25); face and voice keep an unsealed `embedding`
    (increments 4 and 5). Exactly one of the two is set."""

    __tablename__ = "template"
    __table_args__ = (
        UniqueConstraint("sample_id", "algorithm", name="template_per_algorithm"),
        CheckConstraint("num_nonnulls(data, embedding) = 1", name="template_one_value"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    sample_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sample.id"))
    algorithm: Mapped[str] = mapped_column(ForeignKey("algorithm.code"))
    version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    data: Mapped[bytes | None] = mapped_column(LargeBinary)
    embedding: Mapped[object | None] = mapped_column(Vector)


class Attempt(BiometricBase):
    """A completed comparison (H25, H35). Its outcome is searchable; its probe is sealed to this row
    and subject. Deleting the compared enrolment also deletes its verification attempts (H35)."""

    __tablename__ = "attempt"
    __table_args__ = (
        CheckConstraint("modality IN ('fingerprint', 'face', 'voice')", name="attempt_modality"),
        CheckConstraint("mode IN ('verify', 'identify')", name="attempt_mode"),
        CheckConstraint("source IN ('device', 'file') AND (modality <> 'fingerprint' OR source = 'device')",
                        name="attempt_source"),
        CheckConstraint("(mode = 'verify' AND enrolment_id IS NOT NULL AND top_enrolment_id IS NULL AND gallery_size IS NULL)"
                        " OR (mode = 'identify' AND enrolment_id IS NULL AND gallery_size IS NOT NULL AND gallery_size >= 0)", name="attempt_target"),
        CheckConstraint("duration_ms >= 0", name="attempt_duration"),
        CheckConstraint("accepted = (score > threshold)", name="attempt_decision"),
        CheckConstraint("(algorithm = 'fusion' AND weight_opencv_sift BETWEEN 0 AND 100"
                        " AND weight_learned_pore BETWEEN 0 AND 100 AND weight_pore_sift BETWEEN 0 AND 100"
                        " AND weight_opencv_sift + weight_learned_pore + weight_pore_sift = 100"
                        " AND num_nonnulls(weight_opencv_sift, weight_learned_pore, weight_pore_sift) = 3)"
                        " OR (algorithm <> 'fusion' AND num_nonnulls(weight_opencv_sift, weight_learned_pore, weight_pore_sift) = 0)",
                        name="attempt_weights"),
        Index("ix_attempt_subject_at", "subject_id", "at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    subject_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("subject.id"))
    modality: Mapped[str] = mapped_column(String(12))
    mode: Mapped[str] = mapped_column(String(8))
    algorithm: Mapped[str] = mapped_column(ForeignKey("algorithm.code"))
    weight_opencv_sift: Mapped[int | None] = mapped_column(SmallInteger)
    weight_learned_pore: Mapped[int | None] = mapped_column(SmallInteger)
    weight_pore_sift: Mapped[int | None] = mapped_column(SmallInteger)
    enrolment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("enrolment.id", ondelete="CASCADE"), index=True)
    top_enrolment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("enrolment.id", ondelete="SET NULL"), index=True)
    gallery_size: Mapped[int | None] = mapped_column(Integer)
    score: Mapped[float] = mapped_column(Double)
    threshold: Mapped[float] = mapped_column(Double)
    accepted: Mapped[bool] = mapped_column(Boolean)
    duration_ms: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(8), server_default="device")
    probe: Mapped[bytes] = mapped_column(LargeBinary)
