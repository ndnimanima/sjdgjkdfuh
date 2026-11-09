"""Offline FastAPI/API smoke test using a temporary database.

Run from the repository root with:
    python docs/api_smoke.py

No external feed, translation, or messaging service is contacted.
"""
from __future__ import annotations

import os
import secrets
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def check(label: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(label)
    print("  ok  ", label)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rozaneh-api-smoke-") as tmp:
        os.environ.update(
            DATA_DIR=tmp,
            ADMIN_PASSWORD="rozaneh-ci-smoke-password",
            COOKIE_SECURE="0",
            SCHEDULER_ENABLED="0",
            DEFAULT_TZ="UTC",
        )

        from fastapi.testclient import TestClient
        from app.main import app

        with TestClient(app, base_url="http://testserver") as client:
            health = client.get("/healthz")
            check("health endpoint", health.status_code == 200 and health.json().get("ok") is True)
            check("health version", health.json().get("version") == "1.08")

            meta = client.get("/api/meta")
            check("public metadata", meta.status_code == 200 and meta.json().get("version") == "1.08")
            check("theme metadata", len(meta.json().get("themes", [])) == 4)
            check("auth protects feeds", client.get("/api/feeds").status_code == 401)

            login = client.post("/api/login", json={"password": "rozaneh-ci-smoke-password"})
            check("login and session cookie", login.status_code == 200 and bool(client.cookies))
            check("authenticated feed API", client.get("/api/feeds").status_code == 200)

            topics = client.get("/api/topics")
            check("seed topics", topics.status_code == 200 and len(topics.json().get("topics", [])) >= 5)
            analysis = client.get("/api/analyzer?limit=5")
            check("analyzer API", analysis.status_code == 200 and "analyses" in analysis.json())
            missing_llm = client.post("/api/analyzer/llm/test")
            check("analyzer reports missing dedicated/fallback API key", missing_llm.status_code == 200 and missing_llm.json().get("error") == "analysis_api_missing")

            from app import analyzer, config, db
            original_llm_chat = analyzer._llm_chat
            original_fetch_api_models = analyzer.fetch_api_models
            model_calls = []
            webhook_value = "https://hooks.example/" + secrets.token_urlsafe(24)

            async def fake_llm_chat(base_url, model, api_key, system, user, timeout=55.0):
                return "OK"

            async def fake_fetch_api_models(base_url, api_key, timeout=20.0):
                model_calls.append((base_url, api_key))
                return {"ok": True, "models": ["deepseek-flash", "deepseek-v4-pro"]}

            analyzer._llm_chat = fake_llm_chat
            analyzer.fetch_api_models = fake_fetch_api_models
            try:
                configured = client.patch(
                    "/api/settings",
                    json={
                        "analysis_api_provider": "openai_compatible",
                        "analysis_api_base_url": "https://llm.example/v1",
                        "analysis_api_model": "smoke-model",
                        "analysis_api_key": "test-analysis-secret",
                        "image_generation_enabled": 1,
                        "image_api_base_url": "https://image.example/v1",
                        "image_api_model": "smoke-image-model",
                        "image_api_key": "test-image-secret",
                        "feedback_webhook": webhook_value,
                    },
                )
                public_settings = configured.json().get("settings", {})
                check("analyzer and image API settings save without exposing keys", configured.status_code == 200
                      and public_settings.get("analysis_api_key_set") is True
                      and public_settings.get("image_api_key_set") is True
                      and "test-analysis-secret" not in str(public_settings)
                      and "test-image-secret" not in str(public_settings))
                check("feedback webhook URL is masked in settings and omitted from JSON backup",
                      public_settings.get("feedback_webhook") == ""
                      and public_settings.get("feedback_webhook_set") is True
                      and webhook_value not in configured.text
                      and webhook_value not in client.get("/api/admin/export").text
                      and "feedback_webhook" not in client.get("/api/admin/export").json().get("settings", {}))
                client.patch("/api/settings", json={"feedback_webhook": ""})
                llm_test = client.post("/api/analyzer/llm/test")
                check("analyzer connection test uses configured OpenAI-compatible API", llm_test.status_code == 200
                      and llm_test.json().get("ok") is True
                      and llm_test.json().get("model") == "smoke-model")

                async def failed_llm_chat(base_url, model, api_key, system, user, timeout=55.0):
                    raise RuntimeError("llm_http_402")

                analyzer._llm_chat = failed_llm_chat
                llm_balance_error = client.post("/api/analyzer/llm/test")
                check("analyzer test returns a bounded 402 code for localized balance guidance", llm_balance_error.status_code == 200
                      and llm_balance_error.json().get("error") == "llm_http_402"
                      and "test-analysis-secret" not in llm_balance_error.text)
                analyzer._llm_chat = fake_llm_chat

                discovered = client.post("/api/analyzer/models", json={
                    "provider": "deepseek",
                    "base_url": "https://attacker.invalid/v1",
                    "api_key": "temporary-discovery-secret",
                })
                check("DeepSeek model discovery forces the official API base and never echoes the key", discovered.status_code == 200
                      and discovered.json().get("ok") is True
                      and discovered.json().get("models") == ["deepseek-flash", "deepseek-v4-pro"]
                      and model_calls[-1] == ("https://api.deepseek.com", "temporary-discovery-secret")
                      and "temporary-discovery-secret" not in discovered.text)

                async def failed_model_fetch(base_url, api_key, timeout=20.0):
                    return {"ok": False, "error": "models_http_402"}

                analyzer.fetch_api_models = failed_model_fetch
                balance_error = client.post("/api/analyzer/models", json={
                    "provider": "deepseek", "api_key": "temporary-discovery-secret",
                })
                check("DeepSeek 402 model-discovery error remains key-safe", balance_error.status_code == 200
                      and balance_error.json().get("error") == "models_http_402"
                      and "temporary-discovery-secret" not in balance_error.text)
            finally:
                analyzer._llm_chat = original_llm_chat
                analyzer.fetch_api_models = original_fetch_api_models

            creator_before = client.get("/api/creators").json()
            editor_state = client.get("/api/creators/auth/session")
            creator_patch = client.patch("/api/creators", json={"creator1_name": "Admin bypass attempt"})
            creator_import = client.post(
                "/api/admin/import",
                json={"confirm": True, "payload": {"settings": {
                    "creator1_name": "Import bypass attempt",
                    "edu_youtube_id": "@import-bypass-attempt",
                    "contact_bot_token": "import-secret-must-not-persist",
                }, "destinations": [{
                    "name": "Imported without credential",
                    "platform": "telegram",
                    "chat_id": "-1000000000001",
                    "bot_token": "import-destination-secret-must-not-persist",
                }]}},
            )
            creator_after = client.get("/api/creators").json()
            settings_after_import = client.get("/api/settings").json().get("settings", {})
            check("creator edits require separately configured creator authentication", editor_state.status_code == 200
                  and editor_state.json() == {"configured": False, "authenticated": False}
                  and creator_patch.status_code == 403
                  and creator_patch.json().get("detail") == "creator_auth_required")
            check("backup import cannot bypass creator-only fields or store the contact token", creator_import.status_code == 200
                  and creator_after["creators"][0]["name"] == creator_before["creators"][0]["name"]
                  and creator_after["edu"]["youtube_id"] == creator_before["edu"]["youtube_id"]
                  and "contact_bot_token" not in settings_after_import
                  and db.get_setting("contact_bot_token") == "")
            imported_destination = db.query_one(
                "SELECT bot_token FROM destinations WHERE name = ?", ("Imported without credential",)
            )
            check("JSON import ignores supplied destination bot credentials",
                  imported_destination is not None and imported_destination.get("bot_token") == "")
            contact_not_configured = client.post("/api/feedback", json={"message": "offline smoke feedback"})
            check("feedback reports saved-but-not-delivered when contact bot is absent", contact_not_configured.status_code == 200
                  and contact_not_configured.json().get("saved") is True
                  and contact_not_configured.json().get("forwarded") is False
                  and contact_not_configured.json().get("telegram", {}).get("status") == "not_configured")

            invalid_image_url = client.patch("/api/settings", json={"image_api_base_url": "not a URL"})
            check("image API endpoint rejects malformed URLs", invalid_image_url.status_code == 400)

            asset_name = "ai_0123456789abcdef01234567.jpg"
            config.GENERATED_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
            (config.GENERATED_IMAGES_DIR / asset_name).write_bytes(b"persistent-media-smoke")
            media = client.get(f"/media/generated/{asset_name}")
            check("generated-media mount serves an asset from persistent DATA_DIR", media.status_code == 200
                  and media.content == b"persistent-media-smoke"
                  and str(config.GENERATED_IMAGES_DIR).startswith(tmp))

            export_secret = "smoke-" + secrets.token_urlsafe(24)
            db.execute(
                "UPDATE destinations SET bot_token = ? WHERE name = ?",
                (export_secret, "Imported without credential"),
            )
            exported = client.get("/api/admin/export?include_items=0")
            export_payload = exported.json()
            exported_destination = next(
                (row for row in export_payload.get("destinations", [])
                 if row.get("name") == "Imported without credential"),
                {},
            )
            check("admin JSON backup excludes contact and destination credentials", exported.status_code == 200
                  and export_payload.get("version") == "1.08"
                  and "contact_bot_token" not in export_payload.get("settings", {})
                  and exported_destination.get("bot_token") == ""
                  and export_secret not in exported.text)

            topic = client.post(
                "/api/topics",
                json={"name": "CI smoke topic", "name_en": "CI smoke topic", "keywords": "ci,smoke"},
            )
            topic_id = topic.json().get("id") if topic.status_code == 200 else None
            check("topic create API", bool(topic_id))
            deleted = client.delete(f"/api/topics/{topic_id}") if topic_id else None
            check("topic delete API", bool(deleted and deleted.status_code == 200))

            page = client.get("/")
            check("authenticated panel shell", page.status_code == 200 and b"themeSwitch" in page.content)
            client.post("/api/logout")
            check("logout revokes session", client.get("/api/feeds").status_code == 401)

    print("API smoke test passed.")


if __name__ == "__main__":
    main()
