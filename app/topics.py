"""Keyword & tag-based topic matching + negative keyword filter.

No external ML dependency: each topic owns a keyword list editable in the panel,
enriched with RSS <category> tags and optional per-feed default topic fallback.
Persian text is normalised so Arabic Yeh/Kaf variants and ZWNJ half-spaces
never break matching.
"""

from __future__ import annotations

import re

_AR_MAP = str.maketrans(
    {"ي": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه", "ؤ": "و", "إ": "ا", "أ": "ا", "ٱ": "ا"}
)
_DIACRITICS = re.compile(r"[\u064B-\u0652\u0670\u0640]")
_NON_WORD = re.compile(r"[^\w\u0600-\u06FF\s]+", re.UNICODE)
_SPACE = re.compile(r"\s+")
_LATIN_KW = re.compile(r"^[a-z0-9][a-z0-9 .'\-+]*$")


def normalize(text: str) -> str:
    text = (text or "").translate(_AR_MAP)
    text = _DIACRITICS.sub("", text)
    text = text.replace("\u200c", " ").replace("\u200f", " ").replace("\u200e", " ")
    text = _NON_WORD.sub(" ", text)
    text = _SPACE.sub(" ", text)
    return text.strip().lower()


def split_keywords(raw: str | None) -> list[str]:
    if not raw:
        return []
    parts = re.split(r"[,،\n;]+", raw)
    return [p.strip() for p in parts if p.strip()]


def _keyword_hit(keyword: str, haystack_title: str, haystack_body: str, haystack_tags: str = "") -> int:
    kw = normalize(keyword)
    if not kw:
        return 0
    score = 0
    if _LATIN_KW.match(kw):
        pattern = re.compile(r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])")
        if pattern.search(haystack_title):
            score += 3
        elif haystack_tags and pattern.search(haystack_tags):
            score += 3
        elif pattern.search(haystack_body):
            score += 1
    else:
        if kw in haystack_title:
            score += 3
        elif haystack_tags and kw in haystack_tags:
            score += 3
        elif kw in haystack_body:
            score += 1
    return score


def score_topic(topic: dict, title: str, summary: str, tags: str = "") -> int:
    t_title = normalize(title)
    t_body = normalize(summary)
    t_tags = normalize(tags)
    total = 0
    for kw in split_keywords(topic.get("keywords")):
        total += _keyword_hit(kw, t_title, t_body, t_tags)
    return total


def classify(
    topics: list[dict], title: str, summary: str, tags: str = ""
) -> tuple[dict | None, int, list[str]]:
    """Return (best_topic, score, all_matched_topic_names)."""
    best: dict | None = None
    best_score = 0
    matched: list[str] = []
    for topic in topics:
        if not int(topic.get("enabled", 1)):
            continue
        score = score_topic(topic, title, summary, tags)
        if score > 0:
            matched.append(topic.get("name", ""))
        if score > best_score:
            best, best_score = topic, score
    return best, best_score, matched


def score_topics(
    topics: list[dict],
    title: str,
    summary: str,
    tags: str = "",
    default_topic_id: int = 0,
) -> tuple[dict | None, int, set[int]]:
    """Score every enabled topic once and return (best, best_score, matched_ids)."""
    best: dict | None = None
    best_score = 0
    matched: set[int] = set()
    default_topic: dict | None = None
    for topic in topics:
        if not int(topic.get("enabled", 1)):
            continue
        tid = int(topic["id"])
        if default_topic_id and tid == int(default_topic_id):
            default_topic = topic
        score = score_topic(topic, title, summary, tags)
        if score > 0:
            matched.add(tid)
        if score > best_score:
            best, best_score = topic, score

    if default_topic is not None:
        dt_id = int(default_topic["id"])
        matched.add(dt_id)
        if best is None or best_score < 2:
            best = default_topic
            best_score = max(best_score, 2)

    return best, best_score, matched


def check_excluded(exclude_raw: str | None, title: str, summary: str) -> str:
    """Return the first excluded keyword hit, or '' if clean."""
    kws = split_keywords(exclude_raw)
    if not kws:
        return ""
    t_title = normalize(title)
    t_body = normalize(summary)
    for kw in kws:
        if _keyword_hit(kw, t_title, t_body) > 0:
            return kw
    return ""


def topic_label(topic: dict | None) -> str:
    if not topic:
        return ""
    emoji = (topic.get("emoji") or "").strip()
    name = (topic.get("name") or "").strip()
    return f"{emoji} {name}".strip()


def hashtag(name: str) -> str:
    clean = re.sub(r"[^\w\u0600-\u06FF]+", "_", (name or "").strip())
    clean = re.sub(r"_+", "_", clean).strip("_")
    return f"#{clean}" if clean else ""
