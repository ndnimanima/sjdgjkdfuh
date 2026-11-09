"""Offline regression checks for photo-aware archive resends.

No real messaging, source URL, or image-generation service is contacted.
"""
from __future__ import annotations

import asyncio
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


async def exercise() -> None:
    from app import pipeline, publish

    original_query_one = pipeline.db.query_one
    original_query = pipeline.db.query
    original_update = pipeline._update_item
    original_enrich = pipeline._enrich_one
    original_generate = pipeline.imagegen.generate_news_image
    original_send_photo = publish.send_photo
    original_send_message = publish.send_message
    original_render_item = publish.render_item
    original_render_caption = publish.render_caption
    original_delay = pipeline.config_send_delay

    state = {"item": {}, "send_image": 1, "photo_calls": 0, "message_calls": 0, "updated": []}
    destination = {"id": 9, "name": "Smoke channel", "platform": "telegram", "parse_mode": "HTML", "footer": ""}

    def query_one(sql, params=()):
        if "FROM items" in sql:
            return dict(state["item"])
        if "FROM jobs" in sql:
            return {"send_image": state["send_image"]}
        return None

    def query(sql, params=()):
        return [dict(destination)]

    def update(item_id, **values):
        state["updated"].append((item_id, values))
        state["item"].update(values)
        return True

    async def enrich(item, *, want_body=True, want_image=True, want_date=False):
        return None

    async def generate(item):
        return ("", "not_configured")

    async def send_photo(dest, image, caption):
        state["photo_calls"] += 1
        return False, "image_rejected_or_unavailable"

    async def send_message(dest, text):
        state["message_calls"] += 1
        return True, "ok"

    publish.render_item = lambda item, dest: "single text message"
    publish.render_caption = lambda item, dest: "single photo caption"
    pipeline.db.query_one = query_one
    pipeline.db.query = query
    pipeline._update_item = update
    pipeline._enrich_one = enrich
    pipeline.imagegen.generate_news_image = generate
    publish.send_photo = send_photo
    publish.send_message = send_message
    pipeline.config_send_delay = lambda: 0

    def reset(*, image: str, send_image: int = 1):
        state.update({
            "item": {
                "id": 5,
                "job_id": 3,
                "feed_id": None,
                "title": "An explanatory technology story",
                "summary": "A source-grounded paragraph with enough context to publish in one message. " * 4,
                "summary_fa": "",
                "image": image,
                "link": "https://example.com/story",
                "status": "filtered",
            },
            "send_image": send_image,
            "photo_calls": 0,
            "message_calls": 0,
            "updated": [],
        })

    try:
        reset(image="https://example.com/source-photo.jpg", send_image=1)
        broken_photo = await pipeline.resend_item(5)
        check(
            "a failed enabled-photo resend is not downgraded to text",
            broken_photo.get("ok") is False
            and state["photo_calls"] == 1
            and state["message_calls"] == 0,
        )

        reset(image="", send_image=1)
        no_image = await pipeline.resend_item(5)
        check(
            "resend refuses text-only delivery when a destination requires a photo",
            no_image.get("ok") is False
            and no_image.get("error_code") == "image_required_unavailable"
            and state["photo_calls"] == 0
            and state["message_calls"] == 0,
        )

        reset(image="https://example.com/source-photo.jpg", send_image=0)
        text_only = await pipeline.resend_item(5)
        check(
            "a job with photo sending disabled resends as one text message",
            text_only.get("ok") is True and state["photo_calls"] == 0 and state["message_calls"] == 1,
        )
    finally:
        pipeline.db.query_one = original_query_one
        pipeline.db.query = original_query
        pipeline._update_item = original_update
        pipeline._enrich_one = original_enrich
        pipeline.imagegen.generate_news_image = original_generate
        publish.send_photo = original_send_photo
        publish.send_message = original_send_message
        publish.render_item = original_render_item
        publish.render_caption = original_render_caption
        pipeline.config_send_delay = original_delay


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rozaneh-delivery-smoke-") as tmp:
        os.environ.update(
            DATA_DIR=tmp,
            ADMIN_PASSWORD="rozaneh-delivery-smoke-password",
            COOKIE_SECURE="0",
            SCHEDULER_ENABLED="0",
            DEFAULT_TZ="UTC",
        )
        asyncio.run(exercise())
    print("Photo-aware delivery smoke test passed.")


if __name__ == "__main__":
    main()
