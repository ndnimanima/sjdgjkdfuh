"""Encrypted persistence for the creator-managed contact Telegram token.

The Fernet key is supplied only through the host secret manager. SQLite and
its backups may contain ciphertext, but never the key or the plaintext token.
"""
from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from . import config, db

_PREFIX = "fernet:v1:"


class SecretStorageUnavailable(RuntimeError):
    """Raised when a contact token cannot be safely persisted."""


def _cipher() -> Fernet | None:
    key = (config.CONTACT_BOT_ENCRYPTION_KEY or "").strip()
    if not key:
        return None
    try:
        return Fernet(key.encode("ascii"))
    except (UnicodeEncodeError, TypeError, ValueError):
        return None


def encrypt_contact_bot_token(token: str) -> str:
    cipher = _cipher()
    if cipher is None:
        raise SecretStorageUnavailable("contact_bot_storage_unconfigured")
    return _PREFIX + cipher.encrypt(token.encode("utf-8")).decode("ascii")


def decrypt_contact_bot_token(stored_value: str) -> str:
    """Decrypt a stored token; refuse legacy plaintext and invalid ciphertext."""
    if not stored_value or not stored_value.startswith(_PREFIX):
        return ""
    cipher = _cipher()
    if cipher is None:
        return ""
    try:
        return cipher.decrypt(stored_value[len(_PREFIX):].encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeEncodeError, UnicodeDecodeError, TypeError, ValueError):
        return ""


def migrate_legacy_contact_bot_token() -> str:
    """Encrypt a legacy plaintext value, or discard it if no external key exists.

    Returns a non-sensitive result code for startup diagnostics. Never log or
    return the value itself.
    """
    stored = db.get_setting("contact_bot_token")
    if not stored or stored.startswith(_PREFIX):
        return "unchanged"
    cipher = _cipher()
    if cipher is None:
        db.set_setting("contact_bot_token", "")
        return "discarded_without_key"
    encrypted = _PREFIX + cipher.encrypt(stored.encode("utf-8")).decode("ascii")
    db.set_setting("contact_bot_token", encrypted)
    return "encrypted_legacy"
