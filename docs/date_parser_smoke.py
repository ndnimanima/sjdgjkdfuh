"""Offline publication-date and Digiato article extraction regression checks.

Run from the repository root with ``python docs/date_parser_smoke.py``.
The parser test uses a compact HTML fixture modeled on the Digiato article page;
no external network request is made.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("DEFAULT_TZ", "Asia/Tehran")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import feeds  # noqa: E402


def check(label: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(label)
    print("  ok  ", label)


def main() -> None:
    expected = datetime(2026, 10, 29, 11, 55, tzinfo=timezone.utc)
    date_variants = (
        "7 آبان 1405 · 15:25",
        "۷ آبان ۱۴۰۵ ساعت ۱۵:۲۵",
        "7 Aban 1405 15:25",
        "1405-08-07T15:25:00",
        "2026-10-29T15:25:00+03:30",
        "Thu, 29 Oct 2026 15:25:00 +0330",
    )
    for value in date_variants:
        check(f"date parses correctly: {value}", feeds.parse_publication_datetime(value) == expected)

    now = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)
    check(
        "7 Aban is older than the 24-hour window on 7 November",
        not feeds.within_window({"published": "7 آبان 1405 · 15:25"}, 24, now),
    )
    check(
        "a recent explicit-offset date remains in the 24-hour window",
        feeds.within_window({"published": "2026-11-07T14:00:00+03:30"}, 24, now),
    )

    url = "https://digiato.com/laptop/ternus-explains-touchscreen-macbook-pro-decision"
    fixture = """<!doctype html>
    <html><head>
      <meta property="og:title" content="Why Apple chose a touchscreen MacBook Pro">
      <meta property="og:image" content="https://static.digiato.com/digiato/2026/10/John-Ternus-Macbook-Pro-644x424.jpg.webp">
    </head><body><main>
      <h1>Why Apple chose a touchscreen MacBook Pro</h1>
      <div class="article-meta">7 Aban 1405 · 15:25</div>
      <article class="article-content">
        <p>Apple explained its decision to add touchscreen support to the MacBook Pro after years of relying on a keyboard and trackpad. The change reflects how customers use its computers and the capabilities of modern software.</p>
        <p>John Ternus said the company evaluated the interaction alongside the existing Mac experience, rather than treating touch as a replacement for the trackpad. That context explains why the feature is an option instead of a redesign of the whole laptop interface.</p>
        <p>The move connects Apple's laptop strategy with its work on touch interfaces across tablets and computers. It also gives developers another input method while keeping the familiar keyboard workflow available.</p>
      </article>
    </main></body></html>"""
    article = feeds.parse_article_html(fixture, url)
    check("Digiato fixture yields a useful title", "touchscreen MacBook Pro" in article.get("title", ""))
    check("Digiato fixture yields multi-paragraph source text", len(article.get("body", "")) > 320 and article["body"].count("\n\n") >= 2)
    check(
        "Digiato real hero image is retained",
        article.get("image") == "https://static.digiato.com/digiato/2026/10/John-Ternus-Macbook-Pro-644x424.jpg.webp",
    )
    check("unlabelled Digiato byline date is normalized", article.get("published") == expected.isoformat())
    print("Date parser smoke test passed.")


if __name__ == "__main__":
    main()
