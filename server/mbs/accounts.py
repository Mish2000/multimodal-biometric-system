"""Accounts: registration with the national ID, sign-in, sessions, password recovery and administration
(H3, H12, H14, H29-H32).

Errors carry a short code for the client, which shows its own text in the account's language; nothing
here logs a national ID, a password or a token.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import threading
import time
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from . import keys as keyring
from . import national_id, outbox, passwords, phones
from .db import Databases
from .fingerprint import enrolled_fingers
from .keys import Keys
from .models import (ACTIVE, ADMIN, DISABLED, EMAIL, LANGUAGES, SMS, THEMES, USER, Account, AuditEntry,
                     IdentityLink, PasswordReset, Session, Subject)

SESSION_IDLE = timedelta(minutes=30)
SESSION_LONGEST = timedelta(hours=12)
RESET_VALID = timedelta(minutes=30)  # how long a link to reset a password works (H32)
RESET_PAUSE = timedelta(minutes=1)  # at most one message per account in this time, against flooding
USERNAME = re.compile(r"[^\W_][\w.\-]{1,30}[^\W_]")  # 3-32 letters (any script) or digits, with . _ - inside
MODALITIES = ("fingerprint", "face", "voice")


class AccountError(Exception):
    def __init__(self, code: str, status: int = 400, retry_after: float | None = None):
        super().__init__(code)
        self.code, self.status, self.retry_after = code, status, retry_after


@dataclass(frozen=True)
class SignedIn:
    """The account behind a valid session, as the API needs it."""

    id: uuid.UUID
    username: str
    email: str
    role: str
    must_change_password: bool
    theme: str
    language: str


def now() -> datetime:
    return datetime.now(timezone.utc)


def _db(engine) -> DbSession:
    return DbSession(engine, expire_on_commit=False)


def username_key(username: str) -> str:
    return unicodedata.normalize("NFKC", username).casefold()


def _username(text: str) -> tuple[str, str]:
    username = unicodedata.normalize("NFC", text.strip())
    if not USERNAME.fullmatch(username):
        raise AccountError("invalid_username")
    return username, username_key(username)


def _email(text: str) -> tuple[str, str]:
    try:
        email = validate_email(text.strip(), check_deliverability=False).normalized
    except EmailNotValidError:
        raise AccountError("invalid_email") from None
    return email, email.casefold()


def _phone(text: str) -> str:
    try:
        return phones.normalize(text)
    except phones.InvalidPhone:
        raise AccountError("invalid_phone") from None


def _password(text: str) -> str:
    try:
        passwords.check_new(text)
    except passwords.InvalidPassword:
        raise AccountError("invalid_password") from None
    return text


def _language(text: str) -> str:
    if text not in LANGUAGES:
        raise AccountError("invalid_language")
    return text


def _taken(db: DbSession, username: str, email: str, phone: str | None = None) -> None:
    if db.scalar(select(Account.id).where(Account.username_key == username)):
        raise AccountError("username_taken", 409)
    if db.scalar(select(Account.id).where(Account.email_key == email)):
        raise AccountError("email_taken", 409)
    if phone is not None and db.scalar(select(Account.id).where(Account.phone == phone)):
        raise AccountError("phone_taken", 409)


def _new_account(username: str, email: str, password: str, role: str, must_change: bool,
                 phone: str | None = None, language: str = "en") -> Account:
    (name, name_key), (mail, mail_key) = _username(username), _email(email)
    return Account(id=uuid.uuid4(), username=name, username_key=name_key, email=mail, email_key=mail_key,
                   phone=phone, password_hash=passwords.hash_password(password), role=role, status=ACTIVE,
                   must_change_password=must_change, theme="system", language=language, created_at=now())


def register(databases: Databases, keys: Keys, username: str, email: str, phone: str, password: str,
             national_id_text: str, language: str = "en") -> SignedIn:
    """A user account (H3): the national ID is checked, turned into its HMAC and forgotten. A new random
    subject is created in the biometric database, and only its sealed identifier links it to the account.
    The mobile phone (H29) and the language of the registration screen (H31) are kept with the account."""
    try:
        normalized = national_id.normalize(national_id_text)
    except national_id.InvalidNationalId:
        raise AccountError("invalid_national_id") from None
    account = _new_account(username, email, _password(password), USER, False, _phone(phone), _language(language))
    id_hmac = keyring.national_id_hmac(keys, normalized)
    del normalized
    with _db(databases.accounts) as db:
        _taken(db, account.username_key, account.email_key, account.phone)
        if db.scalar(select(IdentityLink.account_id).where(IdentityLink.national_id_hmac == id_hmac)):
            raise AccountError("national_id_registered", 409)
    subject = uuid.uuid4()
    with _db(databases.biometric) as bio, bio.begin():
        bio.add(Subject(id=subject))
    try:
        with _db(databases.accounts) as db, db.begin():
            db.add(account)
            db.flush()
            db.add(IdentityLink(account_id=account.id, national_id_hmac=id_hmac,
                                subject=keyring.seal(keys, keyring.IDENTITY_LINK, account.id.bytes, subject.bytes)))
    except IntegrityError:
        # Another registration took the name, email or ID meanwhile: the new subject is removed again.
        with _db(databases.biometric) as bio, bio.begin():
            bio.execute(Subject.__table__.delete().where(Subject.id == subject))
        raise AccountError("already_registered", 409) from None
    return _signed_in(account)


def subject_of(databases: Databases, keys: Keys, account_id: uuid.UUID) -> uuid.UUID | None:
    """The subject behind a user account, opened from its sealed link (None for administrators)."""
    with _db(databases.accounts) as db:
        link = db.get(IdentityLink, account_id)
    if link is None:
        return None
    return uuid.UUID(bytes=keyring.open_sealed(keys, keyring.IDENTITY_LINK, account_id.bytes, link.subject))


class Throttle:
    """Slows down repeated failed sign-ins for one login name (H14): the first five failures cost
    nothing, then each further try must wait 2, 4, 8, ... seconds, at most five minutes; a successful
    sign-in clears the count. Kept in memory: the server runs as one process on one PC (H11)."""

    FREE = 5
    LONGEST = 300.0

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._failures: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    def wait(self, key: str) -> float:
        with self._lock:
            count, last = self._failures.get(key, (0, 0.0))
        if count < self.FREE:
            return 0.0
        return max(0.0, last + min(self.LONGEST, 2.0 ** (count - self.FREE + 1)) - self._clock())

    def failed(self, key: str) -> None:
        with self._lock:
            count, _ = self._failures.get(key, (0, 0.0))
            self._failures[key] = (count + 1, self._clock())

    def succeeded(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


def sign_in(databases: Databases, throttle: Throttle, login: str, password: str,
            language: str | None = None) -> tuple[str, SignedIn]:
    """Email or username with the password; the same answer whether the name exists or not. A language
    chosen on the sign-in screen becomes the account's (H31); without one the account keeps its own."""
    if language is not None:
        _language(language)
    key = username_key(login.strip())
    wait = throttle.wait(key)
    if wait > 0:
        raise AccountError("too_many_attempts", 429, retry_after=wait)
    with _db(databases.accounts) as db, db.begin():
        account = db.scalar(select(Account).where((Account.username_key == key) | (Account.email_key == key)))
        if account is None:
            passwords.verify_password(password, passwords.UNKNOWN_ACCOUNT_HASH)
            throttle.failed(key)
            raise AccountError("wrong_credentials", 401)
        if not passwords.verify_password(password, account.password_hash):
            throttle.failed(key)
            raise AccountError("wrong_credentials", 401)
        if account.status != ACTIVE:
            raise AccountError("account_disabled", 403)
        throttle.succeeded(key)
        if language is not None:
            account.language = language
        token = secrets.token_urlsafe(32)
        moment = now()
        db.add(Session(token_hash=_token_hash(token), account_id=account.id, created_at=moment,
                       last_seen_at=moment, expires_at=moment + SESSION_LONGEST))
    return token, _signed_in(account)


def session_account(databases: Databases, token: str) -> SignedIn | None:
    """The active account behind a token, sliding its idle limit; expired sessions are removed."""
    moment = now()
    with _db(databases.accounts) as db, db.begin():
        session = db.get(Session, _token_hash(token))
        if session is None:
            return None
        account = db.get(Account, session.account_id)
        if moment > session.expires_at or moment - session.last_seen_at > SESSION_IDLE or account.status != ACTIVE:
            db.delete(session)
            return None
        session.last_seen_at = moment
        return _signed_in(account)


def sign_out(databases: Databases, token: str) -> None:
    with _db(databases.accounts) as db, db.begin():
        db.execute(Session.__table__.delete().where(Session.token_hash == _token_hash(token)))


def change_password(databases: Databases, account_id: uuid.UUID, token: str, current: str, new: str) -> None:
    """Also ends a one-time password (H12). The account's other sessions are signed out."""
    _password(new)
    with _db(databases.accounts) as db, db.begin():
        account = db.get(Account, account_id)
        if not passwords.verify_password(current, account.password_hash):
            raise AccountError("wrong_password", 403)
        if passwords.verify_password(new, account.password_hash):
            raise AccountError("same_password")
        account.password_hash = passwords.hash_password(new)
        account.must_change_password = False
        db.execute(Session.__table__.delete().where(Session.account_id == account_id,
                                                    Session.token_hash != _token_hash(token)))


def set_theme(databases: Databases, account_id: uuid.UUID, theme: str) -> None:
    """The account's look in the client (H24): Windows' setting, light or dark."""
    if theme not in THEMES:
        raise AccountError("invalid_theme")
    with _db(databases.accounts) as db, db.begin():
        db.get(Account, account_id).theme = theme


def set_language(databases: Databases, account_id: uuid.UUID, language: str) -> None:
    """The client's language for the account (H31): English or Hebrew."""
    _language(language)
    with _db(databases.accounts) as db, db.begin():
        db.get(Account, account_id).language = language


# Password recovery while signed out (H32), as OWASP's Forgot Password Cheat Sheet advises: the same answer
# whether the details belong to an account or not, a random single-use token stored only as its hash, a
# short lifetime, every session signed out after the change, and no sign-in by the link itself.

def request_reset(databases: Databases, channel: str, destination: str, language: str) -> outbox.Message | None:
    """The message to send for a request by SMS (the account's mobile phone) or email, or None when
    nothing is sent: no active account has these details, or one was sent to it within RESET_PAUSE. The
    caller answers the same in every case; only a malformed number or address is refused."""
    _language(language)
    if channel == SMS:
        found = Account.phone == _phone(destination)
    elif channel == EMAIL:
        found = Account.email_key == _email(destination)[1]
    else:
        raise AccountError("invalid_channel")
    moment = now()
    with _db(databases.accounts) as db, db.begin():
        db.execute(delete(PasswordReset).where(PasswordReset.expires_at < moment))
        account = db.scalar(select(Account).where(found))
        if account is None or account.status != ACTIVE:
            return None
        latest = db.scalar(select(func.max(PasswordReset.created_at)).where(PasswordReset.account_id == account.id))
        if latest is not None and moment - latest < RESET_PAUSE:
            return None
        db.execute(delete(PasswordReset).where(PasswordReset.account_id == account.id))  # only the newest works
        token = secrets.token_urlsafe(32)
        db.add(PasswordReset(token_hash=_token_hash(token), account_id=account.id, channel=channel,
                             created_at=moment, expires_at=moment + RESET_VALID))
    to = account.phone if channel == SMS else account.email
    return outbox.password_reset(channel, to, account.username, token, language, int(RESET_VALID.total_seconds() // 60))


def _reset_account(db: DbSession, token: str, lock: bool = False) -> Account:
    """The active account whose link this is, or the one answer for an unknown, used or expired link.
    `lock` holds the link's row, so two uses at the same moment cannot both pass."""
    reset = db.get(PasswordReset, _token_hash(token), with_for_update=lock) if token.isascii() else None
    account = None if reset is None or now() > reset.expires_at else db.get(Account, reset.account_id)
    if account is None or account.status != ACTIVE:
        raise AccountError("invalid_reset_link")
    return account


def check_reset(databases: Databases, token: str) -> None:
    """Whether a link still works, so the screen can say so before a new password is typed."""
    with _db(databases.accounts) as db:
        _reset_account(db, token)


def complete_reset(databases: Databases, throttle: Throttle, token: str, new: str) -> None:
    """The new password, under the rules of H30. The link and every other link of the account stop
    working, every session of the account ends, and its failed sign-ins are forgotten."""
    _password(new)
    with _db(databases.accounts) as db, db.begin():
        account = _reset_account(db, token, lock=True)
        if passwords.verify_password(new, account.password_hash):
            raise AccountError("same_password")
        account.password_hash = passwords.hash_password(new)
        account.must_change_password = False
        db.execute(delete(PasswordReset).where(PasswordReset.account_id == account.id))
        db.execute(delete(Session).where(Session.account_id == account.id))
    throttle.succeeded(account.username_key)
    throttle.succeeded(account.email_key)


def modalities(databases: Databases, keys: Keys, account: SignedIn) -> dict[str, dict] | None:
    """Enrolment per modality for the home screen (H15), with the enrolled fingers (H33); administrator
    accounts have none (H12). Face and voice arrive with increments 4 and 5."""
    if account.role != USER:
        return None
    fingers = enrolled_fingers(databases, subject_of(databases, keys, account.id))
    states: dict[str, dict] = {modality: {"enrolled": False} for modality in MODALITIES}
    states["fingerprint"] = {"enrolled": bool(fingers), "fingers": fingers}
    return states


# Administration (H12): each change asks for the administrator's password again and is audited.

def _reauthenticate(db: DbSession, administrator_id: uuid.UUID, password: str) -> Account:
    administrator = db.get(Account, administrator_id)
    if not passwords.verify_password(password, administrator.password_hash):
        raise AccountError("wrong_password", 403)
    return administrator


def _audit(db: DbSession, administrator_id: uuid.UUID, action: str, target: str) -> None:
    db.add(AuditEntry(at=now(), administrator_id=administrator_id, action=action, target=target))


def first_administrator(databases: Databases, username: str, email: str) -> str:
    """The server command's administrator (H12); returns its one-time password."""
    one_time = passwords.one_time()
    account = _new_account(username, email, one_time, ADMIN, True)
    with _db(databases.accounts) as db, db.begin():
        _taken(db, account.username_key, account.email_key)
        db.add(account)
        db.flush()
        _audit(db, account.id, "first_administrator", account.username)
    return one_time


def create_administrator(databases: Databases, administrator_id: uuid.UUID, password: str,
                         username: str, email: str) -> tuple[SignedIn, str]:
    one_time = passwords.one_time()
    account = _new_account(username, email, one_time, ADMIN, True)
    with _db(databases.accounts) as db, db.begin():
        _reauthenticate(db, administrator_id, password)
        _taken(db, account.username_key, account.email_key)
        db.add(account)
        db.flush()
        _audit(db, administrator_id, "create_administrator", account.username)
    return _signed_in(account), one_time


def set_status(databases: Databases, administrator_id: uuid.UUID, password: str, account_id: uuid.UUID, status: str) -> None:
    """Disable or enable an account. A disabled account cannot sign in, loses its sessions and leaves the
    1:N gallery; the last active administrator cannot be disabled."""
    if status not in (ACTIVE, DISABLED):
        raise AccountError("invalid_status")
    with _db(databases.accounts) as db, db.begin():
        _reauthenticate(db, administrator_id, password)
        account = db.get(Account, account_id, with_for_update=True)
        if account is None:
            raise AccountError("no_such_account", 404)
        if account.status == status:
            return
        if status == DISABLED and account.role == ADMIN:
            active = db.scalars(select(Account.id).where(Account.role == ADMIN, Account.status == ACTIVE)
                                .with_for_update()).all()
            if len(active) <= 1:
                raise AccountError("last_administrator", 409)
        account.status = status
        if status == DISABLED:
            db.execute(Session.__table__.delete().where(Session.account_id == account_id))
        _audit(db, administrator_id, "disable_account" if status == DISABLED else "enable_account", account.username)


def list_accounts(databases: Databases) -> list[dict]:
    with _db(databases.accounts) as db:
        rows = db.scalars(select(Account).order_by(Account.created_at)).all()
        return [{"id": str(a.id), "username": a.username, "email": a.email, "role": a.role, "status": a.status,
                 "created_at": a.created_at.isoformat()} for a in rows]


def audit_log(databases: Databases) -> list[dict]:
    with _db(databases.accounts) as db:
        rows = db.execute(select(AuditEntry, Account.username).join(Account, Account.id == AuditEntry.administrator_id)
                          .order_by(AuditEntry.id.desc())).all()
        return [{"at": e.at.isoformat(), "administrator": name, "action": e.action, "target": e.target}
                for e, name in rows]


def _signed_in(account: Account) -> SignedIn:
    return SignedIn(account.id, account.username, account.email, account.role, account.must_change_password,
                    account.theme, account.language)


def _token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode("ascii")).digest()
