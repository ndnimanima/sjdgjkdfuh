"""Create a credential-scrubbed SQLite snapshot for routine backups.

Usage:
    python docs/safe_backup.py /data/rozaneh.db /secure/backups/rozaneh-sanitized.sqlite3

The output keeps application/content data, but removes API/contact credentials,
destination bot tokens, session cookies, and stored admin password hashes. The
source database is opened read-only and never modified. Keep the host secret
manager (including CONTACT_BOT_ENCRYPTION_KEY) outside the backup location.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import tempfile
from pathlib import Path

SENSITIVE_SETTINGS = (
    "password_hash",
    "password_salt",
    "deepseek_api_key",
    "openai_api_key",
    "analysis_api_key",
    "image_api_key",
    "contact_bot_token",
    "contact_bot_encryption_key",
    "feedback_webhook",
)


def create_sanitized_backup(source: str | Path, destination: str | Path) -> Path:
    src = Path(source).expanduser().resolve(strict=True)
    dst = Path(destination).expanduser().resolve()
    if src == dst:
        raise ValueError("source_and_destination_must_differ")
    if dst.exists():
        raise FileExistsError(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)

    fd, temporary_name = tempfile.mkstemp(prefix=f".{dst.name}.", suffix=".tmp", dir=dst.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    os.chmod(temporary, 0o600)

    source_conn: sqlite3.Connection | None = None
    backup_conn: sqlite3.Connection | None = None
    try:
        source_conn = sqlite3.connect(f"{src.as_uri()}?mode=ro", uri=True, timeout=30)
        backup_conn = sqlite3.connect(str(temporary), timeout=30)
        source_conn.backup(backup_conn)
        backup_conn.execute("PRAGMA secure_delete = ON")
        tables = {
            row[0] for row in backup_conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

        if "settings" in tables:
            placeholders = ",".join("?" for _ in SENSITIVE_SETTINGS)
            backup_conn.execute(
                f"DELETE FROM settings WHERE key IN ({placeholders})",
                SENSITIVE_SETTINGS,
            )
        if "destinations" in tables:
            columns = {row[1] for row in backup_conn.execute("PRAGMA table_info(destinations)")}
            if "bot_token" in columns:
                backup_conn.execute("UPDATE destinations SET bot_token = ''")
        for table in ("sessions", "creator_sessions"):
            if table in tables:
                backup_conn.execute(f"DELETE FROM {table}")

        backup_conn.commit()
        backup_conn.execute("VACUUM")
        backup_conn.commit()
        backup_conn.close()
        backup_conn = None
        source_conn.close()
        source_conn = None

        # Publish only the finished, sanitized snapshot; fail rather than
        # overwrite an existing backup if another process won the race.
        os.link(temporary, dst)
        temporary.unlink()
        return dst
    except Exception:
        if backup_conn is not None:
            backup_conn.close()
        if source_conn is not None:
            source_conn.close()
        temporary.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="path to the live SQLite database")
    parser.add_argument("destination", help="new sanitized backup path (must not exist)")
    args = parser.parse_args()
    result = create_sanitized_backup(args.source, args.destination)
    print(f"Sanitized backup written: {result}")


if __name__ == "__main__":
    main()
