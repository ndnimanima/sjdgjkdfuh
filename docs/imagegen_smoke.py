"""Offline checks for the opt-in image-generation fallback and its cache.

Run from the repository root with ``python docs/imagegen_smoke.py``. The API
request is mocked; no credential or external image service is contacted.
"""
from __future__ import annotations

import asyncio
import base64
import os
import sys
import tempfile
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def check(label: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(label)
    print("  ok  ", label)


async def exercise() -> None:
    from PIL import Image
    from app import config, db, imagegen

    db.get_conn()
    db.set_setting("image_generation_enabled", "1")
    db.set_setting("image_api_base_url", "https://images.example/v1")
    db.set_setting("image_api_model", "image-test")
    db.set_setting("image_api_key", "smoke-only-secret")

    buf = BytesIO()
    Image.effect_noise((512, 512), 100).convert("RGB").save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {"data": [{"b64_json": encoded}]}

    calls = {"count": 0, "url": "", "payload": {}}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, *, json, headers):
            calls["count"] += 1
            calls["url"] = url
            calls["payload"] = json
            return FakeResponse()

    original_client = imagegen.httpx.AsyncClient
    imagegen.httpx.AsyncClient = FakeClient
    item = {
        "hash": "imagegen-smoke-hash",
        "title": "A sample technology story",
        "summary": "A detailed sample story used only by an offline API mock.",
        "image": "",
    }
    try:
        served_path, error = await imagegen.generate_news_image(item)
        cached_path, cache_error = await imagegen.generate_news_image(item)
        source_path, source_error = await imagegen.generate_news_image({**item, "image": "https://example.com/real-photo.jpg"})
    finally:
        imagegen.httpx.AsyncClient = original_client

    filename = Path(served_path).name
    stored = config.GENERATED_IMAGES_DIR / filename
    check("mock image API returns a persistent generated JPEG", bool(served_path) and not error and stored.exists() and stored.stat().st_size > 1500)
    check("generated asset is served from the generated-media route", served_path.startswith("/media/generated/ai_") and filename.endswith(".jpg"))
    check("retries reuse the cache instead of paying for another image", cached_path == served_path and not cache_error and calls["count"] == 1)
    check("the request uses the configured OpenAI-compatible endpoint", calls["url"] == "https://images.example/v1/images/generations" and calls["payload"].get("model") == "image-test")
    check("a real source photo prevents image generation", source_path == "" and source_error == "source_image_available" and calls["count"] == 1)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rozaneh-imagegen-smoke-") as tmp:
        os.environ.update(
            DATA_DIR=tmp,
            ADMIN_PASSWORD="rozaneh-imagegen-smoke-password",
            COOKIE_SECURE="0",
            SCHEDULER_ENABLED="0",
            DEFAULT_TZ="UTC",
        )
        asyncio.run(exercise())
    print("Image-generation smoke test passed.")


if __name__ == "__main__":
    main()
