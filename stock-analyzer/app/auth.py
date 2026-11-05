"""Accounts, password hashing and login throttling."""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import threading
import time

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.migrations import claim_legacy_data
from app.models import AccountEntry, Portfolio, Setting, Transaction, User
from app.settings_store import bump_data_version

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1
MIN_PASSWORD_LENGTH = 10
USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{2,64}$")
MAX_FAILURES = 5
LOCKOUT_SECONDS = 15 * 60

_failures: dict[str, list[float]] = {}
_failures_lock = threading.Lock()


class AccountError(ValueError):
    """Invalid input; the message is shown to the user and names a key in i18n."""


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, maxmem=64 * 1024 * 1024)
    return f"scrypt${SCRYPT_N}${base64.b64encode(salt).decode()}${base64.b64encode(derived).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, salt, expected = stored.split("$")
        derived = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=SCRYPT_R, p=SCRYPT_P,
                                 maxmem=64 * 1024 * 1024)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(derived, base64.b64decode(expected))


def _clean_username(username: str) -> str:
    cleaned = username.strip()
    if not USERNAME_RE.match(cleaned):
        raise AccountError("acc_bad_username")
    return cleaned


def _check_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AccountError("acc_short_password")


def user_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(User)) or 0


def create_user(session: Session, username: str, password: str, is_admin: bool = False) -> User:
    cleaned = _clean_username(username)
    _check_password(password)
    if session.scalar(select(User).where(func.lower(User.username) == cleaned.lower())):
        raise AccountError("acc_username_taken")
    user = User(username=cleaned, password_hash=hash_password(password), is_admin=is_admin)
    session.add(user)
    session.flush()
    portfolio = Portfolio(user_id=user.id, name="Mijn portefeuille")
    session.add(portfolio)
    session.flush()
    if is_admin:
        # The first account inherits what was imported before accounts existed.
        if claim_legacy_data(session, portfolio.id, user.id):
            bump_data_version(session)
    return user


def set_password(session: Session, user: User, password: str) -> None:
    _check_password(password)
    user.password_hash = hash_password(password)
    user.session_version += 1
    session.flush()


def delete_user(session: Session, user: User) -> None:
    for portfolio in session.scalars(select(Portfolio).where(Portfolio.user_id == user.id)).all():
        delete_portfolio(session, portfolio)
    session.execute(delete(Setting).where(Setting.key == f"analysis:{user.id}"))
    session.delete(user)
    session.flush()


def delete_portfolio(session: Session, portfolio: Portfolio) -> None:
    session.execute(delete(Transaction).where(Transaction.portfolio_id == portfolio.id))
    session.execute(delete(AccountEntry).where(AccountEntry.portfolio_id == portfolio.id))
    session.execute(delete(Setting).where(Setting.key == f"backtest:{portfolio.id}"))
    session.delete(portfolio)
    bump_data_version(session)
    session.flush()


def is_locked_out(username: str) -> bool:
    key = username.strip().lower()
    now = time.time()
    with _failures_lock:
        recent = [t for t in _failures.get(key, []) if now - t < LOCKOUT_SECONDS]
        _failures[key] = recent
        return len(recent) >= MAX_FAILURES


def record_failure(username: str) -> None:
    with _failures_lock:
        _failures.setdefault(username.strip().lower(), []).append(time.time())


def clear_failures(username: str) -> None:
    with _failures_lock:
        _failures.pop(username.strip().lower(), None)


def authenticate(session: Session, username: str, password: str) -> User | None:
    user = session.scalar(select(User).where(func.lower(User.username) == username.strip().lower()))
    if user is None:
        # Same work as a real check, so timing doesn't reveal which usernames exist.
        verify_password(password, _DUMMY_HASH)
        return None
    return user if verify_password(password, user.password_hash) else None


_DUMMY_HASH = hash_password(secrets.token_hex(8))
