"""Passwords as Argon2id at RFC 9106's second recommended option (H14), stored as PHC strings."""

from __future__ import annotations

import secrets
import unicodedata

from cryptography.exceptions import InvalidKey
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

MIN_LENGTH = 12
MAX_LENGTH = 256


class WeakPassword(ValueError):
    pass


def _encode(password: str) -> bytes:
    return unicodedata.normalize("NFKC", password).encode("utf-8")


def hash_password(password: str) -> str:
    kdf = Argon2id(salt=secrets.token_bytes(16), length=32, iterations=3, lanes=4, memory_cost=64 * 1024)
    return kdf.derive_phc_encoded(_encode(password))


def verify_password(password: str, phc: str) -> bool:
    try:
        Argon2id.verify_phc_encoded(_encode(password), phc)
    except InvalidKey:
        return False
    return True


def check_new(password: str) -> None:
    """Length only, with no composition rules: a long passphrase is the strongest choice."""
    if not MIN_LENGTH <= len(password) <= MAX_LENGTH:
        raise WeakPassword(f"a password has {MIN_LENGTH} to {MAX_LENGTH} characters")


def one_time() -> str:
    """A one-time password for a new administrator, changed at the first sign-in (H12)."""
    return secrets.token_urlsafe(12)


# Verified for a login name that has no account, so a failed sign-in takes the same time either way.
UNKNOWN_ACCOUNT_HASH = hash_password(secrets.token_urlsafe(16))
