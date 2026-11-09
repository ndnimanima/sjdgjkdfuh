"""Offline tests for source-grounded multi-sentence news summaries.

Run from the repository root with: python docs/news_quality_smoke.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.news_quality import is_ai_story, summarize_news, summary_issue  # noqa: E402


ARTICLE = """OpenAI announces a new model for developers

The company introduced a model that can follow complex instructions and call external tools. The release is aimed at teams building software assistants.

Developers can test it through the company's API, with access rolling out in stages. Pricing and regional availability differ by plan.

OpenAI says the model performs better on coding and multi-step tasks than its previous release. The company has not published independent results for every benchmark.

Several researchers said the announcement should be judged against real-world reliability, not only the vendor's scores. They also recommended checking privacy and data-retention terms before using it at work.

The update adds controls for administrators and lets teams review tool calls. Existing applications may need small changes to use the new options.

Read more: click here to continue.
"""


def check(label: str, ok: bool) -> None:
    if not ok:
        raise AssertionError(label)
    print("  ok  ", label)


def sentence_count(text: str) -> int:
    return len([part for part in re.split(r"(?<=[.!?؟؛…])\s+", text.replace("\n", " ")) if part.strip()])


def main() -> None:
    title = "OpenAI announces a new model for developers"
    check("AI story detection by topic and article terms", is_ai_story("فناوری و هوش مصنوعی", title))
    check("AI acronym is matched as a word", is_ai_story("", "An AI update arrived today"))
    check("ordinary words containing 'ai' are not misclassified", not is_ai_story("", "The train arrives late"))

    ai_copy = summarize_news(ARTICLE, title, max_chars=820, ai_story=True)
    check("AI summary fits the requested Telegram body budget", 0 < len(ai_copy) <= 820)
    check("AI summary keeps explanatory multi-sentence context", 3 <= sentence_count(ai_copy) <= 7)
    check("AI summary contains product, access, and safety context", all(
        phrase in ai_copy for phrase in ("external tools", "rolling out in stages", "independent results")
    ))
    check("source call-to-action is omitted", "Read more" not in ai_copy and "click here" not in ai_copy)
    check("summary is acceptable for publication", not summary_issue(ai_copy, title))

    long_ai = summarize_news(ARTICLE, title, max_chars=1800, ai_story=True)
    regular = summarize_news(ARTICLE, title, max_chars=1800, ai_story=False)
    check("AI summaries may carry more context than ordinary stories", sentence_count(long_ai) > sentence_count(regular))
    check("summaries remain source-grounded", "external tools" in long_ai and "external tools" in regular and "independent results" in long_ai)

    headline_only = summarize_news(title, title, max_chars=820, ai_story=True)
    check("headline-only content is not turned into a fabricated summary", not headline_only)
    check("single-sentence teaser is flagged", bool(summary_issue("A single short teaser sentence about a product update.", title)))
    check("duplicate-headline body is flagged", bool(summary_issue(title, title)))

    print("News quality smoke test passed.")


if __name__ == "__main__":
    main()
