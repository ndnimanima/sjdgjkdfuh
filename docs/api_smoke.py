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
            check("health version", health.json().get("version") == "1.04")

            meta = client.get("/api/meta")
            check("public metadata", meta.status_code == 200 and meta.json().get("version") == "1.04")
            check("theme metadata", len(meta.json().get("themes", [])) == 4)
            check("auth protects feeds", client.get("/api/feeds").status_code == 401)

            login = client.post("/api/login", json={"password": "rozaneh-ci-smoke-password"})
            check("login and session cookie", login.status_code == 200 and bool(client.cookies))
            check("authenticated feed API", client.get("/api/feeds").status_code == 200)

            topics = client.get("/api/topics")
            check("seed topics", topics.status_code == 200 and len(topics.json().get("topics", [])) >= 5)
            analysis = client.get("/api/analyzer?limit=5")
            check("analyzer API", analysis.status_code == 200 and "analyses" in analysis.json())
            exported = client.get("/api/admin/export?include_items=0")
            check("admin export API", exported.status_code == 200 and exported.json().get("version") == "1.04")

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
