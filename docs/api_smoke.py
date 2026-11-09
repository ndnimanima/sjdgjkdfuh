"""Offline FastAPI/API smoke test using a temporary database.

Run from the repository root with:
    python docs/api_smoke.py

No external feed, translation, or messaging service is contacted.
"""
from __future__ import annotations

import os
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
            check("health version", health.json().get("version") == "1.06")

            meta = client.get("/api/meta")
            check("public metadata", meta.status_code == 200 and meta.json().get("version") == "1.06")
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

            async def fake_llm_chat(base_url, model, api_key, system, user, timeout=55.0):
                return "OK"

            analyzer._llm_chat = fake_llm_chat
            try:
                configured = client.patch(
                    "/api/settings",
                    json={
                        "analysis_api_base_url": "https://llm.example/v1",
                        "analysis_api_model": "smoke-model",
                        "analysis_api_key": "test-analysis-secret",
                        "image_generation_enabled": 1,
                        "image_api_base_url": "https://image.example/v1",
                        "image_api_model": "smoke-image-model",
                        "image_api_key": "test-image-secret",
                    },
                )
                public_settings = configured.json().get("settings", {})
                check("analyzer and image API settings save without exposing keys", configured.status_code == 200
                      and public_settings.get("analysis_api_key_set") is True
                      and public_settings.get("image_api_key_set") is True
                      and "test-analysis-secret" not in str(public_settings)
                      and "test-image-secret" not in str(public_settings))
                llm_test = client.post("/api/analyzer/llm/test")
                check("analyzer connection test uses configured OpenAI-compatible API", llm_test.status_code == 200
                      and llm_test.json().get("ok") is True
                      and llm_test.json().get("model") == "smoke-model")
            finally:
                analyzer._llm_chat = original_llm_chat

            creator_before = client.get("/api/creators").json()
            creator_patch = client.patch("/api/creators", json={"creator1_name": "Unauthorized edit"})
            creator_import = client.post(
                "/api/admin/import",
                json={"confirm": True, "payload": {"settings": {
                    "creator1_name": "Import bypass attempt",
                    "edu_youtube_id": "@import-bypass-attempt",
                }}},
            )
            creator_after = client.get("/api/creators").json()
            check("creator/team profiles are read-only, including backup import", creator_patch.status_code == 403
                  and creator_import.status_code == 200
                  and creator_after["creators"][0]["name"] == creator_before["creators"][0]["name"]
                  and creator_after["edu"]["youtube_id"] == creator_before["edu"]["youtube_id"])

            invalid_image_url = client.patch("/api/settings", json={"image_api_base_url": "not a URL"})
            check("image API endpoint rejects malformed URLs", invalid_image_url.status_code == 400)

            asset_name = "ai_0123456789abcdef01234567.jpg"
            config.GENERATED_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
            (config.GENERATED_IMAGES_DIR / asset_name).write_bytes(b"persistent-media-smoke")
            media = client.get(f"/media/generated/{asset_name}")
            check("generated-media mount serves an asset from persistent DATA_DIR", media.status_code == 200
                  and media.content == b"persistent-media-smoke"
                  and str(config.GENERATED_IMAGES_DIR).startswith(tmp))

            exported = client.get("/api/admin/export?include_items=0")
            check("admin export API", exported.status_code == 200 and exported.json().get("version") == "1.06")

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
