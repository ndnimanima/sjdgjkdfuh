"""Password hashing + cookie sessions."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request

from . import config, db

ITERATIONS = 240_000


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), ITERATIONS)
    return digest.hex(), salt


def set_password(password: str) -> None:
    digest, salt = hash_password(password)
    db.set_setting("password_hash", digest)
    db.set_setting("password_salt", salt)


def verify_password(password: str) -> bool:
    stored = db.get_setting("password_hash")
    salt = db.get_setting("password_salt")
    if not stored or not salt:
        # bootstrap: env password (default "newsrail") until the admin sets one
        return hmac.compare_digest(password, config.BOOTSTRAP_PASSWORD)
    digest, _ = hash_password(password, salt)
    return hmac.compare_digest(digest, stored)


def password_is_bootstrap() -> bool:
    return not db.get_setting("password_hash")


def create_session(user_agent: str = "") -> str:
    token = db.new_token(32)
    now = datetime.now(timezone.utc)
    db.execute(
        "INSERT INTO sessions(token, created_at, expires_at, user_agent) VALUES(?,?,?,?)",
        (
            token,
            now.replace(microsecond=0).isoformat(),
            (now + timedelta(days=config.SESSION_DAYS)).replace(microsecond=0).isoformat(),
            user_agent[:200],
        ),
    )
    db.execute(
        "DELETE FROM sessions WHERE expires_at < ?",
        (now.replace(microsecond=0).isoformat(),),
    )
    return token


def destroy_session(token: str) -> None:
    db.execute("DELETE FROM sessions WHERE token = ?", (token,))


def current_token(request: Request) -> str | None:
    token = request.cookies.get(config.COOKIE_NAME)
    if token:
        return token
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def is_authenticated(request: Request) -> bool:
    token = current_token(request)
    if not token:
        return False
    row = db.query_one("SELECT expires_at FROM sessions WHERE token = ?", (token,))
    if not row:
        return False
    try:
        expires = datetime.fromisoformat(row["expires_at"])
    except ValueError:
        return False
    if expires < datetime.now(timezone.utc):
        destroy_session(token)
        return False
    return True


def require_auth(request: Request) -> None:
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="auth_required")


def creator_auth_configured() -> bool:
    usernames = (config.CREATOR1_USERNAME, config.CREATOR2_USERNAME)
    passwords = (config.CREATOR1_PASSWORD, config.CREATOR2_PASSWORD)
    return bool(
        all(usernames)
        and all(passwords)
        and usernames[0].casefold() != usernames[1].casefold()
    )


def authenticate_creator(username: str, password: str) -> int | None:
    """Return creator slot 1/2 for a matching pair; never accept a default account."""
    if not creator_auth_configured():
        return None
    supplied_user = username.strip().casefold().encode("utf-8")
    supplied_password = password.encode("utf-8")
    matched_slot: int | None = None
    accounts = (
        (1, config.CREATOR1_USERNAME, config.CREATOR1_PASSWORD),
        (2, config.CREATOR2_USERNAME, config.CREATOR2_PASSWORD),
    )
    # Compare both configured accounts to avoid revealing which username exists.
    for slot, expected_user, expected_password in accounts:
        user_ok = hmac.compare_digest(supplied_user, expected_user.casefold().encode("utf-8"))
        password_ok = hmac.compare_digest(supplied_password, expected_password.encode("utf-8"))
        if user_ok & password_ok:
            matched_slot = slot
    return matched_slot


def create_creator_session(creator_slot: int, user_agent: str = "") -> str:
    if creator_slot not in (1, 2):
        raise ValueError("invalid_creator_slot")
    token = db.new_token(32)
    now = datetime.now(timezone.utc)
    db.execute(
        "INSERT INTO creator_sessions(token, creator_slot, created_at, expires_at, user_agent) VALUES(?,?,?,?,?)",
        (
            token,
            creator_slot,
            now.replace(microsecond=0).isoformat(),
            (now + timedelta(days=config.CREATOR_SESSION_DAYS)).replace(microsecond=0).isoformat(),
            user_agent[:200],
        ),
    )
    db.execute("DELETE FROM creator_sessions WHERE expires_at < ?", (now.replace(microsecond=0).isoformat(),))
    return token


def creator_current_token(request: Request) -> str | None:
    return request.cookies.get(config.CREATOR_COOKIE_NAME)


def creator_session_slot(request: Request) -> int | None:
    token = creator_current_token(request)
    if not token:
        return None
    row = db.query_one(
        "SELECT creator_slot, expires_at FROM creator_sessions WHERE token = ?", (token,)
    )
    if not row:
        return None
    try:
        expires = datetime.fromisoformat(row["expires_at"])
    except (TypeError, ValueError):
        db.execute("DELETE FROM creator_sessions WHERE token = ?", (token,))
        return None
    if expires < datetime.now(timezone.utc) or not creator_auth_configured():
        db.execute("DELETE FROM creator_sessions WHERE token = ?", (token,))
        return None
    slot = int(row["creator_slot"])
    return slot if slot in (1, 2) else None


def is_creator_authenticated(request: Request) -> bool:
    return creator_session_slot(request) is not None


def destroy_creator_session(token: str) -> None:
    db.execute("DELETE FROM creator_sessions WHERE token = ?", (token,))


def require_creator_auth(request: Request) -> int:
    slot = creator_session_slot(request)
    if slot is None:
        # This is intentionally 403 rather than 401 so a logged-in admin is not
        # redirected out of the panel when creator re-authentication is needed.
        raise HTTPException(status_code=403, detail="creator_auth_required")
    return slot
