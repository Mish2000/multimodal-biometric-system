"""The key file and the cryptography of H3 and H14, every primitive from the `cryptography` package (H4).

The key file lives outside the repository, and only the Windows user who created it can read it. It
holds a master secret per key version (new values are sealed with the current one, older versions
still open), the HMAC key of national IDs, and the database passwords. Without it the stored data can
be neither read nor linked to its accounts, so the researcher keeps a backup copy of it.
"""

from __future__ import annotations

import base64
import json
import secrets
import subprocess
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, hmac
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

FORMAT = 1
MAGIC = b"MBS1"  # a sealed value: MAGIC, key version (2 bytes), salt, nonce, then ciphertext and tag
SALT_BYTES = 32
NONCE_BYTES = 12
HEADER_BYTES = len(MAGIC) + 2 + SALT_BYTES + NONCE_BYTES

# A label names what a derived key is for, so a key derived for one use never opens another's data.
IDENTITY_LINK = "mbs/identity-link/v1"

DATABASE_ROLES = ("postgres", "accounts", "biometric")


class KeysError(RuntimeError):
    """The key file is missing or damaged, or a sealed value does not open."""


@dataclass(frozen=True)
class Keys:
    current: int
    masters: dict[int, bytes]
    national_id: bytes
    database: dict[str, str]  # database role -> password

    @classmethod
    def generate(cls) -> Keys:
        return cls(
            current=1,
            masters={1: secrets.token_bytes(32)},
            national_id=secrets.token_bytes(32),
            database={role: secrets.token_urlsafe(32) for role in DATABASE_ROLES},
        )

    def to_json(self) -> str:
        return json.dumps({
            "format": FORMAT,
            "current": self.current,
            "masters": {str(v): _b64(k) for v, k in self.masters.items()},
            "national_id_hmac": _b64(self.national_id),
            "database": self.database,
        }, indent=1)

    @classmethod
    def from_json(cls, text: str) -> Keys:
        data = json.loads(text)
        if data.get("format") != FORMAT:
            raise KeysError(f"unknown key file format {data.get('format')!r}")
        keys = cls(
            current=int(data["current"]),
            masters={int(v): base64.b64decode(k) for v, k in data["masters"].items()},
            national_id=base64.b64decode(data["national_id_hmac"]),
            database=dict(data["database"]),
        )
        if keys.current not in keys.masters or any(len(k) != 32 for k in keys.masters.values()):
            raise KeysError("the key file has no valid current master secret")
        return keys


def create(path: Path) -> Keys:
    """Write a new key file that only the current Windows user can read. An existing file is never
    replaced: its keys are what opens the stored data."""
    if path.exists():
        raise KeysError(f"{path} exists; keys are never replaced automatically")
    path.parent.mkdir(parents=True, exist_ok=True)
    restrict(path.parent, folder=True)
    keys = Keys.generate()
    with open(path, "x", encoding="utf-8"):
        pass
    restrict(path)
    path.write_text(keys.to_json(), encoding="utf-8")
    return keys


def load(path: Path) -> Keys:
    if not path.exists():
        raise KeysError(f"{path} is missing; run `python -m mbs setup`, or restore the backup copy")
    return Keys.from_json(path.read_text(encoding="utf-8"))


def restrict(path: Path, folder: bool = False) -> None:
    """Remove inherited permissions and give only the current user (by SID) full control."""
    grant = f"*{current_user_sid()}:" + ("(OI)(CI)(F)" if folder else "(F)")
    subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", grant], check=True, capture_output=True)


def current_user_sid() -> str:
    out = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], check=True, capture_output=True, text=True).stdout
    return out.strip().split(",")[-1].strip('"')


def derive(keys: Keys, version: int, salt: bytes, label: str) -> bytes:
    """Our key function (H3): HKDF-SHA256 of a master secret with the record's salt and the use's label."""
    if version not in keys.masters:
        raise KeysError(f"key version {version} is not in the key file")
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=label.encode("ascii")).derive(keys.masters[version])


def seal(keys: Keys, label: str, row: bytes, plaintext: bytes) -> bytes:
    """AES-256-GCM under a key derived for this one record. The header (key version, salt, nonce), the
    label and the row's identity are associated data, so the value does not open in another row (H14)."""
    salt, nonce = secrets.token_bytes(SALT_BYTES), secrets.token_bytes(NONCE_BYTES)
    header = MAGIC + keys.current.to_bytes(2, "big") + salt + nonce
    key = derive(keys, keys.current, salt, label)
    return header + AESGCM(key).encrypt(nonce, plaintext, header + label.encode("ascii") + row)


def open_sealed(keys: Keys, label: str, row: bytes, sealed: bytes) -> bytes:
    if len(sealed) < HEADER_BYTES + 16 or sealed[:len(MAGIC)] != MAGIC:
        raise KeysError("not a sealed value")
    header = sealed[:HEADER_BYTES]
    version = int.from_bytes(header[4:6], "big")
    salt, nonce = header[6:6 + SALT_BYTES], header[6 + SALT_BYTES:]
    key = derive(keys, version, salt, label)
    try:
        return AESGCM(key).decrypt(nonce, sealed[HEADER_BYTES:], header + label.encode("ascii") + row)
    except InvalidTag as e:
        raise KeysError("the sealed value does not open here: another key, label or row, or it was changed") from e


def national_id_hmac(keys: Keys, national_id: str) -> bytes:
    """HMAC-SHA256 of a normalised national ID under its own key (H3): duplicates can be found, the number
    cannot be recovered."""
    h = hmac.HMAC(keys.national_id, hashes.SHA256())
    h.update(national_id.encode("ascii"))
    return h.finalize()


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")
