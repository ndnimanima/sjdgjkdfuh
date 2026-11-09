"""Offline creator-auth and Telegram contact-delivery smoke test.

Run from the repository root with ``python docs/creator_contact_smoke.py``.
Creator and bot credentials here are disposable test strings; all Telegram HTTP
calls are mocked and no real service or token is contacted.
"""
from __future__ import annotations

import os
import secrets
import sys
import tempfile
import time

from cryptography.fernet import Fernet
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def check(label: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(label)
    print("  ok  ", label)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rozaneh-creator-contact-smoke-") as tmp:
        os.environ.update(
            DATA_DIR=tmp,
            ADMIN_PASSWORD="rozaneh-admin-smoke-password",
            COOKIE_SECURE="0",
            SCHEDULER_ENABLED="0",
            DEFAULT_TZ="UTC",
            CREATOR1_USERNAME="creator-one-smoke",
            CREATOR1_PASSWORD="creator-one-smoke-password-123",
            CREATOR2_USERNAME="creator-two-smoke",
            CREATOR2_PASSWORD="creator-two-smoke-password-456",
            CONTACT_BOT_TOKEN="",
            CONTACT_BOT_ENCRYPTION_KEY=Fernet.generate_key().decode("ascii"),
        )

        import httpx
        from fastapi.testclient import TestClient
        from app.main import app
        from app import config, db, main, secret_store

        with TestClient(app, base_url="http://testserver") as client:
            admin_login = client.post("/api/login", json={"password": "rozaneh-admin-smoke-password"})
            check("admin login is independent from creator editor", admin_login.status_code == 200)

            state = client.get("/api/creators/auth/session")
            check("both distinct creator accounts enable the editor without revealing usernames",
                  state.status_code == 200
                  and state.json() == {"configured": True, "authenticated": False}
                  and "creator-one-smoke" not in state.text)
            check("ordinary admin cannot edit profiles", client.patch(
                "/api/creators", json={"creator1_name": "Admin bypass"}
            ).status_code == 403)
            check("ordinary admin cannot inspect or change bot token",
                  client.get("/api/creators/contact-bot").status_code == 403
                  and client.put("/api/creators/contact-bot", json={"bot_token": "not-allowed"}).status_code == 403)

            bad_login = client.post("/api/creators/auth/login", json={
                "username": "creator-one-smoke", "password": "wrong-password",
            })
            check("invalid creator credentials return a localizable auth error, not an admin redirect",
                  bad_login.status_code == 401 and bad_login.json().get("detail") == "creator_auth_invalid")

            now = time.monotonic()
            main._RATE_LIMIT_EVENTS[("creator_login", "testclient")] = [now] * 8
            limited_login = client.post("/api/creators/auth/login", json={
                "username": "creator-one-smoke", "password": "wrong-password",
            })
            main._RATE_LIMIT_EVENTS.pop(("creator_login", "testclient"), None)
            check("creator login rate limit returns a localizable 429 without authenticating",
                  limited_login.status_code == 429
                  and limited_login.json().get("detail") == "creator_auth_rate_limited")

            creator_login = client.post("/api/creators/auth/login", json={
                "username": "creator-one-smoke", "password": "creator-one-smoke-password-123",
            })
            cookie = creator_login.headers.get("set-cookie", "")
            check("creator login issues a separate HttpOnly session cookie",
                  creator_login.status_code == 200
                  and "rozaneh_creator_session=" in cookie
                  and "httponly" in cookie.lower())
            check("creator session authenticates the editor", client.get("/api/creators/auth/session").json().get("authenticated") is True)

            profile = client.patch("/api/creators", json={
                "creator1_name": "Creator profile smoke update",
                "edu_youtube_id": "@creator-smoke-channel",
            })
            check("creator can update creator and learning-channel fields",
                  profile.status_code == 200
                  and profile.json()["creators"][0]["name"] == "Creator profile smoke update"
                  and profile.json()["edu"]["youtube_id"] == "@creator-smoke-channel")

            token_status = client.get("/api/creators/contact-bot")
            check("creator sees only bot-token configuration status and both-recipient count",
                  token_status.status_code == 200
                  and token_status.json().get("configured") is False
                  and token_status.json().get("recipient_count") == 2
                  and "bot_token" not in token_status.text)

            configured_key = config.CONTACT_BOT_ENCRYPTION_KEY
            config.CONTACT_BOT_ENCRYPTION_KEY = ""
            rejected_secret = "smoke-" + secrets.token_urlsafe(24)
            rejected_update = client.put("/api/creators/contact-bot", json={"bot_token": rejected_secret})
            config.CONTACT_BOT_ENCRYPTION_KEY = configured_key
            check("creator token writes fail closed when encrypted storage is unconfigured",
                  rejected_update.status_code == 503
                  and rejected_update.json().get("detail") == "contact_bot_storage_unconfigured"
                  and db.get_setting("contact_bot_token") == "")

            replacement = "smoke-" + secrets.token_urlsafe(32)
            updated_token = client.put("/api/creators/contact-bot", json={"bot_token": replacement})
            stored_token = db.get_setting("contact_bot_token")
            check("creator can replace the server-side contact token without receiving it back",
                  updated_token.status_code == 200
                  and updated_token.json() == {"ok": True, "configured": True}
                  and replacement not in updated_token.text
                  and stored_token.startswith("fernet:v1:")
                  and replacement not in stored_token
                  and secret_store.decrypt_contact_bot_token(stored_token) == replacement)
            public_settings = client.get("/api/settings").json()["settings"]
            exported = client.get("/api/admin/export").json()
            check("contact bot token and encrypted value are excluded from settings and JSON backup",
                  "contact_bot_token" not in public_settings
                  and replacement not in str(public_settings)
                  and stored_token not in str(public_settings)
                  and "contact_bot_token" not in exported.get("settings", {})
                  and replacement not in str(exported)
                  and stored_token not in str(exported))
            db_files = [path for path in Path(tmp).glob("rozaneh.db*") if path.is_file()]
            raw_db_bundle = b"".join(path.read_bytes() for path in db_files)
            check("SQLite data and WAL never contain the creator-entered token in plaintext",
                  replacement.encode("utf-8") not in raw_db_bundle)
            import_attempt = "smoke-" + secrets.token_urlsafe(24)
            import_key_attempt = Fernet.generate_key().decode("ascii")
            imported = client.post("/api/admin/import", json={
                "confirm": True,
                "payload": {"settings": {
                    "contact_bot_token": import_attempt,
                    "contact_bot_encryption_key": import_key_attempt,
                }},
            })
            check("JSON import cannot replace the contact token or inject its encryption key",
                  imported.status_code == 200
                  and db.get_setting("contact_bot_token") == stored_token
                  and db.get_setting("contact_bot_encryption_key") == ""
                  and import_attempt not in imported.text
                  and import_key_attempt not in imported.text)

            # A second independent browser has no creator cookie, even if the
            # ordinary admin cookie is available in the first client.
            with TestClient(app, base_url="http://testserver") as other:
                other.post("/api/login", json={"password": "rozaneh-admin-smoke-password"})
                check("creator-only writes reject a different admin browser",
                      other.patch("/api/creators", json={"creator2_name": "Unauthorized"}).status_code == 403)

            original_http_client = httpx.AsyncClient
            calls: list[dict] = []
            outcomes = [
                (200, {"ok": True, "result": {"message_id": 1}}),
                (403, {"ok": False, "description": "smoke fixture only"}),
            ]

            class FakeResponse:
                def __init__(self, status_code: int, body: dict):
                    self.status_code = status_code
                    self._body = body

                def json(self):
                    return self._body

            class FakeAsyncClient:
                def __init__(self, *args, **kwargs):
                    pass

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *args):
                    return False

                async def post(self, url: str, *, json: dict):
                    calls.append({"url": url, "json": json})
                    status, body = outcomes.pop(0)
                    return FakeResponse(status, body)

            httpx.AsyncClient = FakeAsyncClient
            try:
                feedback = client.post("/api/feedback", json={
                    "kind": "message", "name": "Reader", "contact": "@reader",
                    "message": "A mocked contact message for both recipients.",
                })
            finally:
                httpx.AsyncClient = original_http_client

            response = feedback.json()
            delivery = response.get("telegram", {})
            expected_recipients = set(config.CONTACT_TELEGRAM_RECIPIENTS)
            sent_recipients = {str(call["json"].get("chat_id")) for call in calls}
            check("feedback sends separately to both supplied Telegram recipient IDs",
                  feedback.status_code == 200
                  and len(calls) == 2
                  and sent_recipients == expected_recipients
                  and all(replacement in call["url"] for call in calls)
                  and all("mocked contact message" in call["json"].get("text", "") for call in calls))
            check("partial Telegram delivery is reported accurately without false success",
                  response.get("saved") is True
                  and response.get("forwarded") is False
                  and delivery.get("status") == "partial"
                  and delivery.get("sent") == 1
                  and delivery.get("total") == 2
                  and replacement not in feedback.text)

            outcomes.extend([
                (200, {"ok": True}),
                (200, {"ok": True}),
            ])
            httpx.AsyncClient = FakeAsyncClient
            try:
                all_sent = client.post("/api/feedback", json={"message": "All recipients receive this mocked message."})
            finally:
                httpx.AsyncClient = original_http_client
            check("full Telegram delivery is reported only when both sends succeed",
                  all_sent.status_code == 200
                  and all_sent.json().get("telegram", {}).get("status") == "sent"
                  and all_sent.json().get("telegram", {}).get("sent") == 2
                  and all_sent.json().get("forwarded") is True)

            # With no DB override and no environment token, the endpoint records
            # the message but does not attempt network delivery.
            db.set_setting("contact_bot_token", "")
            config.CONTACT_BOT_TOKEN = ""
            not_configured = client.post("/api/feedback", json={"message": "No token configured in this smoke case."})
            check("unconfigured bot is reported as saved but not sent",
                  not_configured.status_code == 200
                  and not_configured.json().get("saved") is True
                  and not_configured.json().get("telegram", {}).get("status") == "not_configured"
                  and not_configured.json().get("telegram", {}).get("sent") == 0)

            main._RATE_LIMIT_EVENTS[("feedback", "testclient")] = [time.monotonic()] * 8
            limited_feedback = client.post("/api/feedback", json={"message": "This request should be rate limited."})
            main._RATE_LIMIT_EVENTS.pop(("feedback", "testclient"), None)
            check("feedback rate limit blocks excess contact submissions before delivery",
                  limited_feedback.status_code == 429
                  and limited_feedback.json().get("detail") == "feedback_rate_limited")

            # Directly exercise window counting and the hard memory bound.
            main._RATE_LIMIT_EVENTS.clear()
            counted = [main._consume_rate_limit("unit", "smoke", 2, 60) for _ in range(3)]
            check("rate limiter admits the configured quota and rejects the next event",
                  counted == [True, True, False])
            prior_max = main._RATE_LIMIT_MAX_KEYS
            main._RATE_LIMIT_MAX_KEYS = 4
            main._RATE_LIMIT_EVENTS.clear()
            for index in range(10):
                main._consume_rate_limit("bucket-cap", f"client-{index}", 2, 60)
            bounded_keys = len(main._RATE_LIMIT_EVENTS) <= 4
            main._RATE_LIMIT_MAX_KEYS = prior_max
            main._RATE_LIMIT_EVENTS.clear()
            check("rate limiter bounds its in-memory client-key table", bounded_keys)

            logout = client.post("/api/creators/auth/logout")
            check("creator logout revokes only the creator session",
                  logout.status_code == 200
                  and client.get("/api/creators/auth/session").json().get("authenticated") is False
                  and client.get("/api/feeds").status_code == 200
                  and client.patch("/api/creators", json={"creator1_name": "After logout"}).status_code == 403)

            creator_two = client.post("/api/creators/auth/login", json={
                "username": "creator-two-smoke", "password": "creator-two-smoke-password-456",
            })
            check("second creator has an independent valid account", creator_two.status_code == 200)

    print("Creator authentication and contact delivery smoke test passed.")


if __name__ == "__main__":
    main()
