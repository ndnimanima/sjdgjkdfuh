"""Integration test for the news-quality gate and Telegram photo-caption sizing.

Runs a dry-run pipeline against a temporary database with synthetic feed data.
It does not contact feeds, translation services, or messaging platforms.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def check(label: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(label)
    print("  ok  ", label)


async def exercise_pipeline() -> None:
    now = datetime.now(timezone.utc).isoformat()
    source_items = [
        {
            "title": "OpenAI launches a new assistant model",
            "link": "https://example.com/openai-assistant",
            "summary": (
                "The company introduced a model that can follow complex instructions and call external tools. "
                "The release is aimed at software teams building assistants. "
                "Developers can access it through an API, with rollout beginning this week. "
                "The service includes new administrative controls for organizations. "
                "OpenAI says it improves coding and multi-step work compared with the prior release. "
                "Independent researchers have not tested every claim yet. "
                "Teams should review privacy, data retention, and permission settings before deployment."
            ),
            "image": "https://example.com/openai-hero.jpg",
            "tags": "OpenAI, AI",
            "published": now,
        },
        {
            "title": "OpenAI announces a feature update",
            "link": "https://example.com/openai-short",
            "summary": "OpenAI announces a feature update.",
            "image": "",
            "tags": "OpenAI",
            "published": now,
        },
        {
            "title": "Digiato explains the MacBook Pro touchscreen decision",
            "link": "https://digiato.com/laptop/ternus-explains-touchscreen-macbook-pro-decision",
            "summary": (
                "Apple explained why it is adding touchscreen support to the MacBook Pro after years of relying on a keyboard and trackpad. "
                "John Ternus said the choice reflects how customers use the products and the capabilities of modern software. "
                "The decision connects Apple's laptop strategy with its work on touch interfaces across tablets and computers. "
                "The company says the implementation keeps the established Mac experience while adding an optional direct input method."
            ),
            "image": "https://static.digiato.com/digiato/2026/10/John-Ternus-Macbook-Pro-644x424.jpg.webp",
            "tags": "Apple, MacBook",
            "published": now,
        },
    ]

    from app import db, feeds, pipeline, publish  # import after temporary DATA_DIR is set

    db.get_conn()  # initialize isolated schema and default topics
    original_load_feeds = pipeline._load_feeds
    original_load_dests = pipeline._load_destinations
    original_fetch = feeds.fetch_source
    original_enrich = pipeline._enrich_one
    original_article_enrich = feeds.enrich_article

    pipeline._load_feeds = lambda job: [
        {"id": 1, "url": "https://example.com/rss", "title": "Synthetic source", "show_source": 0, "full_article": 0}
    ]
    pipeline._load_destinations = lambda job: [
        {"id": 1, "platform": "telegram", "name": "Test channel", "parse_mode": "HTML", "footer": "", "topic_filter": ""}
    ]

    async def fake_fetch(_feed: dict) -> list[dict]:
        return [dict(item) for item in source_items]

    async def no_enrichment(
        _item: dict,
        *,
        want_body: bool = True,
        want_image: bool = True,
        want_date: bool = False,
    ) -> None:
        if want_date and "ternus-explains" in (_item.get("link") or ""):
            _item["published"] = feeds.normalize_publication_date("7 Aban 1405 | 15:25")

    feeds.fetch_source = fake_fetch
    pipeline._enrich_one = no_enrichment
    try:
        report = await pipeline.run_job(
            {
                "id": 1,
                "name": "Quality smoke",
                "enabled": 1,
                "window_hours": 24,
                "max_items": 8,
                "translate": 0,
                "include_summary": 1,
                "full_text": 1,
                "send_image": 1,
                "show_topic": 1,
                "only_unseen": 0,
                "filter_mode": "all",
                "feed_ids": [],
                "destination_ids": [],
                "topic_ids": [],
            },
            dry_run=True,
        )

        # A stale canonical article date should be rejected before max_items is
        # consumed; the next genuinely recent story must still reach preview.
        stale_first = dict(source_items[2])
        stale_first["published"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        current_after = {
            "title": "OpenAI announces a current assistant release",
            "link": "https://example.com/openai-current",
            "summary": source_items[0]["summary"],
            "image": "https://example.com/current-hero.jpg",
            "tags": "OpenAI, AI",
            "published": now,
        }
        source_items = [stale_first, current_after]
        cap_report = await pipeline.run_job(
            {
                "id": 2,
                "name": "Date-cap smoke",
                "enabled": 1,
                "window_hours": 24,
                "max_items": 1,
                "translate": 0,
                "include_summary": 1,
                "full_text": 1,
                "send_image": 1,
                "show_topic": 1,
                "only_unseen": 0,
                "filter_mode": "all",
                "feed_ids": [],
                "destination_ids": [],
                "topic_ids": [],
            },
            dry_run=True,
        )
    finally:
        pipeline._load_feeds = original_load_feeds
        pipeline._load_destinations = original_load_dests
        feeds.fetch_source = original_fetch
        pipeline._enrich_one = original_enrich

    async def fake_article(_link: str, site_logo: str = "") -> dict:
        return {"body": "", "image": "https://example.com/article-hero.jpg", "tags": ""}

    feeds.enrich_article = fake_article
    image_item = {
        "link": "https://example.com/story",
        "summary": "An RSS excerpt that already has enough text for a story.",
        "image": "https://example.com/rss-thumbnail.jpg",
        "_full_article": 0,
    }
    try:
        await pipeline._enrich_one(image_item, want_body=False, want_image=True)
    finally:
        feeds.enrich_article = original_article_enrich

    check("article hero image is preferred over an RSS thumbnail", image_item.get("image") == "https://example.com/article-hero.jpg")
    check("pipeline dry run succeeds", report.get("ok") is True)
    check("headline-only story is filtered", report.get("quality_skipped") == 1 and report.get("skipped") >= 2)
    check("old Persian-dated Digiato story is excluded", report.get("date_skipped") == 1)
    check("only explanatory story appears in preview", len(report.get("previews", [])) == 1)
    check(
        "canonical date rejection does not consume the item cap",
        cap_report.get("date_skipped") == 1
        and len(cap_report.get("previews", [])) == 1
        and cap_report["previews"][0].get("title") == "OpenAI announces a current assistant release",
    )
    preview = report["previews"][0]
    check("real source image is retained", preview.get("image") == "https://example.com/openai-hero.jpg")
    check("AI summary includes useful source details", all(
        phrase in preview.get("summary", "")
        for phrase in ("external tools", "rollout beginning this week", "Independent researchers")
    ))
    check("photo caption fits Telegram's visible character limit", len(publish.strip_tags(preview.get("caption", ""))) <= 1024)
    check("quality skip appears in run events", any(e.get("code") == "quality_skip" for e in report.get("events", [])))


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rozaneh-pipeline-quality-") as tmp:
        os.environ.update(
            DATA_DIR=tmp,
            ADMIN_PASSWORD="rozaneh-quality-smoke-password",
            COOKIE_SECURE="0",
            SCHEDULER_ENABLED="0",
            DEFAULT_TZ="UTC",
        )
        asyncio.run(exercise_pipeline())
    print("Pipeline quality smoke test passed.")


if __name__ == "__main__":
    main()
