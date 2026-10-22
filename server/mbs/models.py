"""The tables of the two databases (docs/specification.md, section 4; H3, H12, H14).

The databases share no key: only the sealed identity link in the accounts database leads to a subject
in the biometric one. The biometric database names people only by random subject identifiers and keeps
no creation time for them, so its rows cannot be matched to accounts by when they were made.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Identity, LargeBinary,
                        String, Uuid)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

USER, ADMIN = "user", "admin"
ACTIVE, DISABLED = "active", "disabled"
THEMES = ("system", "light", "dark")  # the account's look: Windows' setting, light or dark (H24)


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
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    username: Mapped[str] = mapped_column(String(32))
    username_key: Mapped[str] = mapped_column(String(32), unique=True)  # case-folded, for uniqueness and sign-in
    email: Mapped[str] = mapped_column(String(254))
    email_key: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))  # Argon2id, PHC string
    role: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(8))
    must_change_password: Mapped[bool] = mapped_column(Boolean)
    theme: Mapped[str] = mapped_column(String(8), server_default="system")
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
