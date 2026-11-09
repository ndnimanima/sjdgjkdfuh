"""Offline check that sanitized database backups contain no stored credentials."""
from __future__ import annotations

import secrets
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "docs"))

from safe_backup import create_sanitized_backup  # noqa: E402


def check(label: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(label)
    print("  ok  ", label)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rozaneh-backup-smoke-") as tmp:
        source = Path(tmp) / "source.sqlite3"
        destination = Path(tmp) / "sanitized.sqlite3"
        markers = {
            "admin_hash": "hash-" + secrets.token_urlsafe(24),
            "admin_salt": "salt-" + secrets.token_urlsafe(24),
            "api_key": "api-" + secrets.token_urlsafe(24),
            "contact_token": "contact-" + secrets.token_urlsafe(24),
            "encryption_key": "key-" + secrets.token_urlsafe(24),
            "webhook": "https://hooks.example/" + secrets.token_urlsafe(24),
            "channel_token": "channel-" + secrets.token_urlsafe(24),
            "admin_session": "session-" + secrets.token_urlsafe(24),
            "creator_session": "creator-session-" + secrets.token_urlsafe(24),
        }
        with sqlite3.connect(source) as conn:
            conn.executescript(
                """
                CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE destinations(id INTEGER PRIMARY KEY, name TEXT, bot_token TEXT);
                CREATE TABLE sessions(token TEXT PRIMARY KEY);
                CREATE TABLE creator_sessions(token TEXT PRIMARY KEY);
                CREATE TABLE sample_content(title TEXT NOT NULL);
                """
            )
            conn.executemany(
                "INSERT INTO settings(key, value) VALUES(?, ?)",
                [
                    ("password_hash", markers["admin_hash"]),
                    ("password_salt", markers["admin_salt"]),
                    ("analysis_api_key", markers["api_key"]),
                    ("contact_bot_token", markers["contact_token"]),
                    ("contact_bot_encryption_key", markers["encryption_key"]),
                    ("feedback_webhook", markers["webhook"]),
                    ("panel_title", "Rozaneh smoke fixture"),
                ],
            )
            conn.execute(
                "INSERT INTO destinations(name, bot_token) VALUES(?, ?)",
                ("smoke destination", markers["channel_token"]),
            )
            conn.execute("INSERT INTO sessions(token) VALUES(?)", (markers["admin_session"],))
            conn.execute("INSERT INTO creator_sessions(token) VALUES(?)", (markers["creator_session"],))
            conn.execute("INSERT INTO sample_content(title) VALUES(?)", ("keep this content",))

        created = create_sanitized_backup(source, destination)
        with sqlite3.connect(created) as conn:
            settings = dict(conn.execute("SELECT key, value FROM settings"))
            destination_row = conn.execute(
                "SELECT name, bot_token FROM destinations"
            ).fetchone()
            remaining_sessions = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            remaining_creator_sessions = conn.execute("SELECT COUNT(*) FROM creator_sessions").fetchone()[0]
            content = conn.execute("SELECT title FROM sample_content").fetchone()[0]

        check("sanitized backup retains ordinary settings and content",
              settings.get("panel_title") == "Rozaneh smoke fixture" and content == "keep this content")
        check("sensitive settings and webhook credentials are removed",
              all(key not in settings for key in (
                  "password_hash", "password_salt", "analysis_api_key",
                  "contact_bot_token", "contact_bot_encryption_key", "feedback_webhook",
              )))
        check("destination bot token is blank and session tables are cleared",
              destination_row == ("smoke destination", "")
              and remaining_sessions == 0
              and remaining_creator_sessions == 0)
        backup_bytes = created.read_bytes()
        check("sanitized SQLite file contains no credential or session marker",
              all(marker.encode("utf-8") not in backup_bytes for marker in markers.values()))
        check("backup file permissions are owner-only",
              created.stat().st_mode & 0o777 == 0o600)
        check("source database remains unchanged",
              all(marker.encode("utf-8") in source.read_bytes() for marker in markers.values()))

    print("Sanitized backup smoke test passed.")


if __name__ == "__main__":
    main()
