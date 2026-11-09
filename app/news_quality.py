"""Source-grounded news summaries and conservative publication quality checks.

The public-channel summary is deliberately extractive: it selects complete
sentences from the article/feed text instead of inventing context. Stories with
only a headline, a duplicate headline, or less than two useful sentences are
held back rather than published as filler.
"""

from __future__ import annotations

import html
import re
import unicodedata

TAG_RE = re.compile(r"<[^>]+>")
BLOCK_END_RE = re.compile(r"</(?:p|div|li|blockquote|h[1-6]|section|article)>|<br\s*/?>", re.I)
SPACE_RE = re.compile(r"[\t\u00a0\r ]+")
PARAGRAPH_RE = re.compile(r"\n+")
SENTENCE_RE = re.compile(r"(?<=[.!?؟؛…])\s+")

# Common feed/page calls-to-action are not news copy and should not leak into
# a channel post. Keep this list conservative; substantive article text stays.
NOISE_LINE_RE = re.compile(
    r"^(?:"
    r"ادامه\s+(?:مطلب|خبر|متن).*|بیشتر\s+بخوانید.*|اخبار\s+مرتبط.*|"
    r"همچنین\s+بخوانید.*|مطالب\s+مرتبط.*|کلیک\s+کنید.*|"
    r"برای\s+(?:مشاهده|دریافت|خواندن)\s+(?:متن\s+کامل|ادامه|خبر).*|"
    r"جهت\s+عضویت\s+در\s+کانال.*|عضویت\s+در\s+کانال.*|"
    r"ما\s+را\s+در\s+.+\s+دنبال\s+کنید.*|انتهای\s+پیام/?|"
    r"read\s+more.*|continue\s+reading.*|related\s+articles.*|"
    r"advertisement.*|subscribe\s+to\s+our\s+newsletter.*"
    r")$",
    re.I,
)

AI_TERMS = (
    "هوش مصنوعی",
    "یادگیری ماشین",
    "یادگیری عمیق",
    "مدل زبانی",
    "مدل‌های زبانی",
    "مدل های زبانی",
    "هوش مصنوعی مولد",
    "artificial intelligence",
    "machine learning",
    "deep learning",
    "large language model",
    "generative ai",
    "chatgpt",
    "openai",
    "deepseek",
    "anthropic",
    "gemini",
    "claude",
    "llama",
    "copilot",
)


def _normalise(value: str) -> str:
    value = unicodedata.normalize("NFKC", html.unescape(value or ""))
    value = value.translate(str.maketrans({"ي": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه"}))
    return re.sub(r"[\W_]+", "", value.casefold(), flags=re.UNICODE)


def _noise_line(value: str) -> bool:
    return bool(NOISE_LINE_RE.match((value or "").strip()))


def _paragraphs(raw: str, title: str = "") -> list[str]:
    if not raw:
        return []
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    raw = BLOCK_END_RE.sub("\n\n", raw)
    raw = html.unescape(TAG_RE.sub(" ", raw))
    title_key = _normalise(title)
    out: list[str] = []
    seen: set[str] = set()
    for line in PARAGRAPH_RE.split(raw):
        line = SPACE_RE.sub(" ", line).strip(" \t\u00a0•·")
        if not line or _noise_line(line):
            continue
        key = _normalise(line)
        if not key or key == title_key or key in seen:
            continue
        seen.add(key)
        out.append(line)
    return out


def _sentence_records(raw: str, title: str = "") -> list[tuple[int, str]]:
    title_key = _normalise(title)
    records: list[tuple[int, str]] = []
    seen: set[str] = set()
    for paragraph_index, paragraph in enumerate(_paragraphs(raw, title)):
        for fragment in SENTENCE_RE.split(paragraph):
            sentence = SPACE_RE.sub(" ", fragment).strip()
            key = _normalise(sentence)
            if not key or key == title_key or key in seen or _noise_line(sentence):
                continue
            # Tiny fragments are usually captions, link labels, or scraping debris.
            if len(key) < 24:
                continue
            seen.add(key)
            records.append((paragraph_index, sentence))
    return records


def is_ai_story(topic: str = "", title: str = "", tags: str = "") -> bool:
    """Recognise AI topics without matching the letters ``ai`` inside other words."""
    raw = f"{topic} {title} {tags}"
    normalized = _normalise(raw)
    if any(_normalise(term) in normalized for term in AI_TERMS):
        return True
    return bool(re.search(r"\b(?:AI|LLM|LLMs)\b", raw, re.I))


def _format_records(records: list[tuple[int, str]]) -> str:
    groups: list[str] = []
    current: list[str] = []
    current_paragraph: int | None = None
    for paragraph_index, sentence in records:
        if current and (paragraph_index != current_paragraph or len(current) >= 2):
            groups.append(" ".join(current))
            current = []
        current_paragraph = paragraph_index
        current.append(sentence)
    if current:
        groups.append(" ".join(current))
    return "\n\n".join(groups)


def summarize_news(
    text: str,
    title: str = "",
    *,
    max_chars: int = 1800,
    ai_story: bool = False,
) -> str:
    """Select complete, source-ordered sentences that fit one channel message."""
    if max_chars <= 0:
        return ""
    records = _sentence_records(text, title)
    if not records:
        return ""
    sentence_cap = 7 if ai_story else 5
    selected: list[tuple[int, str]] = []
    for record in records:
        if len(selected) >= sentence_cap:
            break
        candidate = selected + [record]
        if len(_format_records(candidate)) <= max_chars:
            selected = candidate
    return _format_records(selected)


def summary_issue(summary: str, title: str = "", *, min_chars: int = 150) -> str:
    """Return a Persian reason when copy is too weak for an explanatory post."""
    clean = "\n\n".join(_paragraphs(summary, title))
    if not clean:
        return "متن توضیحی در منبع پیدا نشد"
    if len(_normalise(clean)) < min_chars:
        return "خلاصه برای توضیح کافی کوتاه است"
    if len(_sentence_records(clean, title)) < 2:
        return "منبع کمتر از دو جملهٔ توضیحی دارد"
    return ""
