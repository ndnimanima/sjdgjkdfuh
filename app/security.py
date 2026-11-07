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
