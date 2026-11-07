"""Translation layer.

Providers
---------
* ``deepseek``          — DeepSeek chat API (OpenAI compatible).  Default.
* ``openai_compatible`` — any OpenAI-style ``/chat/completions`` endpoint.
* ``google_free``       — keyless public endpoint, used as the automatic fallback.

Quality guards (all configurable from the panel)
------------------------------------------------
* post-edit pass  — instructs the model to output clean, fluent journalistic
  Persian, and repairs common machine-translation artefacts (broken words,
  stray Latin fragments, wrong spacing) before the text is stored.
* preserve pass   — names, organisations, numbers, dates and units are kept.
* glossary        — words that must never be translated (brands, tickers…).
* output validation — if a Persian target comes back without Persian letters,
  the result is rejected and the fallback provider is used instead.

Every successful translation is cached in SQLite, so nothing is paid twice.
"""

from __future__ import annotations

import hashlib
import re
from typing import Iterable

import httpx

from . import config, db

PERSIAN_RE = re.compile(r"[\u0600-\u06FF]")
LATIN_RE = re.compile(r"[A-Za-z]")
SENTENCE_SPLIT = re.compile(r"(?<=[.!?؟…])\s+")
FENCE_RE = re.compile(r"^```[a-zA-Z]*\n?|```$", re.MULTILINE)
PREFIX_RE = re.compile(r"^\s*(ترجمه|ترجمهٔ|Translation|ترجمه فارسی)\s*[:\-–]\s*", re.IGNORECASE)
SPACE_RE = re.compile(r"[ \t\u00a0]+")
BROKEN_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff]")


class TranslationError(RuntimeError):
    pass


# ── language helpers ────────────────────────────────────────────────────────


def detect_language(text: str) -> str:
    sample = (text or "")[:800]
    persian = len(PERSIAN_RE.findall(sample))
    latin = len(LATIN_RE.findall(sample))
    if persian == 0 and latin == 0:
        return "unknown"
    if persian >= latin:
        return "fa"
    return "en" if latin > persian * 3 else "mixed"


def needs_translation(text: str, target: str = "fa") -> bool:
    if not text or not text.strip():
        return False
    lang = detect_language(text)
    if target == "fa":
        return lang in {"en", "mixed"}
    return lang != target


def _chunks(text: str, size: int = 1600) -> Iterable[str]:
    text = text.strip()
    while len(text) > size:
        window = text[:size]
        cut = max(window.rfind("\n"), window.rfind(". "), window.rfind("؟ "), window.rfind("! "))
        cut = cut if cut > size * 0.5 else size
        yield text[:cut].strip()
        text = text[cut:].strip()
    if text:
        yield text


def _cache_key(provider: str, target: str, text: str) -> str:
    flags = "".join(
        [
            db.get_setting("translate_post_edit") or "0",
            db.get_setting("translate_preserve") or "0",
            db.get_setting("translate_glossary") or "",
        ]
    )
    return hashlib.sha1(f"{provider}|{target}|{flags}|{text}".encode("utf-8")).hexdigest()


def _clean_output(text: str, target: str) -> str:
    text = FENCE_RE.sub("", text or "")
    text = PREFIX_RE.sub("", text)
    text = BROKEN_RE.sub("", text)
    text = SPACE_RE.sub(" ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip().strip('"«').strip()


def _valid_output(source: str, result: str, target: str) -> bool:
    if not result or len(result.strip()) < 2:
        return False
    if target == "fa":
        if detect_language(source) == "en" and not PERSIAN_RE.search(result):
            return False
        if len(LATIN_RE.findall(result)) > 0.85 * len(result):
            return False
    return True


# ── providers ───────────────────────────────────────────────────────────────


async def _google_free(text: str, target: str) -> str:
    url = "https://translate.googleapis.com/translate_a/single"
    params = {"client": "gtx", "sl": "auto", "tl": target, "dt": "t", "q": text}
    async with httpx.AsyncClient(timeout=config.HTTP_TIMEOUT, follow_redirects=True) as client:
        response = await client.get(url, params=params, headers={"User-Agent": config.USER_AGENT})
    if response.status_code != 200:
        raise TranslationError(f"google_status_{response.status_code}")
    try:
        payload = response.json()
        return "".join(seg[0] for seg in payload[0] if seg and seg[0]).strip()
    except (ValueError, IndexError, TypeError) as exc:
        raise TranslationError("google_bad_response") from exc


def _build_prompt(target: str) -> str:
    language = "Persian (Farsi)" if target == "fa" else target
    post_edit = (db.get_setting("translate_post_edit") or "1") != "0"
    preserve = (db.get_setting("translate_preserve") or "1") != "0"
    glossary = [
        part.strip()
        for part in re.split(r"[·,،;\n]+", db.get_setting("translate_glossary") or "")
        if part.strip()
    ]

    rules = [
        f"You are a senior news editor translating news copy into {language}.",
        "Translate faithfully: never add, remove, explain or summarise information.",
        "Output only the translation — no quotes, no notes, no headings.",
    ]
    if post_edit:
        rules += [
            "Write natural, fluent journalistic Persian. Do not translate word by word.",
            "Never leave broken words, half-translated fragments, stray Latin letters,"
            " doubled spaces or mangled characters.",
            "Fix obvious OCR/feed glitches silently while keeping the meaning intact.",
            "Use Persian quotation marks «…» and standard Persian digits inside the text.",
        ]
    if preserve:
        rules += [
            "Keep personal names, organisation names, country names, numbers, dates,"
            " currencies, tickers and units exactly as they are.",
        ]
    if glossary:
        rules.append("Keep these terms untranslated and spelled exactly like this: " + ", ".join(glossary))
    return " ".join(rules)


async def _llm_translate(
    text: str,
    target: str,
    base_url: str,
    model: str,
    api_key: str,
    label: str,
) -> str:
    if not api_key:
        raise TranslationError(f"{label}_no_key")
    body = {
        "model": model,
        "temperature": 0.15,
        "messages": [
            {"role": "system", "content": _build_prompt(target)},
            {"role": "user", "content": text},
        ],
    }
    async with httpx.AsyncClient(timeout=max(40, config.HTTP_TIMEOUT * 3)) as client:
        response = await client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )
    if response.status_code >= 400:
        raise TranslationError(f"{label}_status_{response.status_code}")
    try:
        data = response.json()
        return (data["choices"][0]["message"]["content"] or "").strip()
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise TranslationError(f"{label}_bad_response") from exc


async def _deepseek(text: str, target: str) -> str:
    return await _llm_translate(
        text,
        target,
        db.get_setting("deepseek_base_url") or "https://api.deepseek.com/v1",
        db.get_setting("deepseek_model") or "deepseek-chat",
        db.get_setting("deepseek_api_key"),
        "deepseek",
    )


async def _openai(text: str, target: str) -> str:
    return await _llm_translate(
        text,
        target,
        db.get_setting("openai_base_url") or "https://api.openai.com/v1",
        db.get_setting("openai_model") or "gpt-4o-mini",
        db.get_setting("openai_api_key"),
        "openai",
    )


PROVIDERS = {
    "deepseek": _deepseek,
    "openai_compatible": _openai,
    "google_free": _google_free,
}


async def _run_provider(provider: str, text: str, target: str) -> str:
    handler = PROVIDERS.get(provider, _google_free)
    parts: list[str] = []
    for chunk in _chunks(text, 2600 if provider != "google_free" else 1600):
        if not chunk:
            continue
        if not needs_translation(chunk, target):
            parts.append(chunk)
            continue
        raw = await handler(chunk, target)
        cleaned = _clean_output(raw, target)
        parts.append(cleaned if _valid_output(chunk, cleaned, target) else chunk)
    return "\n".join(parts).strip()


async def translate(text: str, target: str | None = None) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    target = target or db.get_setting("translate_target") or "fa"
    provider = db.get_setting("translate_provider") or "deepseek"
    fallback = db.get_setting("translate_fallback") or "google_free"

    key = _cache_key(provider, target, text)
    cached = db.translate_cache_get(key)
    if cached:
        return cached

    try:
        result = await _run_provider(provider, text, target)
        used = provider
    except (TranslationError, httpx.HTTPError):
        if not fallback or fallback == provider:
            raise
        result = await _run_provider(fallback, text, target)
        used = fallback

    if not result:
        raise TranslationError("empty_result")
    db.translate_cache_put(key, used, target, text, result)
    return result


async def translate_with_report(text: str, target: str | None = None) -> dict:
    """Used by the “test translation” button — returns provider + result."""
    target = target or db.get_setting("translate_target") or "fa"
    provider = db.get_setting("translate_provider") or "deepseek"
    try:
        result = await translate(text, target)
    except Exception as exc:  # noqa: BLE001
        fallback = db.get_setting("translate_fallback") or "google_free"
        return {
            "ok": False,
            "error": str(exc),
            "provider": provider,
            "fallback": fallback,
            "lang": detect_language(text),
        }
    return {
        "ok": True,
        "provider": provider,
        "result": result,
        "lang": detect_language(text),
    }


async def maybe_translate(text: str, enabled: bool, target: str | None = None) -> tuple[str, bool]:
    """Return (text, was_translated). Never raises: the original is kept on failure."""
    if not enabled or not text or not text.strip():
        return text, False
    target = target or db.get_setting("translate_target") or "fa"
    if not needs_translation(text, target):
        return text, False
    try:
        translated = await translate(text, target)
        return (translated or text), bool(translated)
    except (TranslationError, httpx.HTTPError):
        return text, False
