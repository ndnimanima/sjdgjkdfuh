"""Optional, source-aware AI illustration fallback for articles without photos.

Generated assets live under DATA_DIR (the application's persistent writable
volume), are served from /media/generated/, and are never used when a real
source image is available.
"""
from __future__ import annotations

import base64
import hashlib
import io
import os
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx

from . import config, db

GENERATED_NAME_RE = re.compile(r"^ai_[0-9a-f]{24}\.jpg$")


def _settings() -> tuple[str, str, str] | None:
    enabled = str(db.get_setting("image_generation_enabled") or "0").strip() == "1"
    api_key = (db.get_setting("image_api_key") or "").strip()
    base_url = (db.get_setting("image_api_base_url") or "https://api.openai.com/v1").strip().rstrip("/")
    model = (db.get_setting("image_api_model") or "gpt-image-1").strip()
    parsed = urlparse(base_url)
    if not enabled or not api_key or not model or parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return base_url, model, api_key


def is_configured() -> bool:
    """True only when image generation is explicitly enabled and credentials exist."""
    return _settings() is not None


def _normalize_image(raw: bytes) -> bytes | None:
    if len(raw) < 1500 or len(raw) > 10 * 1024 * 1024:
        return None
    try:
        from PIL import Image

        image = Image.open(io.BytesIO(raw))
        image.load()
        if image.width < 180 or image.height < 115:
            return None
        image = image.convert("RGB")
        image.thumbnail((1600, 1600))
        out = io.BytesIO()
        image.save(out, format="JPEG", quality=88, optimize=True)
        normalized = out.getvalue()
        return normalized if 1500 <= len(normalized) <= 10 * 1024 * 1024 else None
    except Exception:  # noqa: BLE001 — invalid or unsupported image bytes
        return None


def _asset_path(item: dict) -> Path:
    seed = str(item.get("hash") or item.get("link") or item.get("title") or "news").strip()
    digest = hashlib.sha256(seed.encode("utf-8", errors="ignore")).hexdigest()[:24]
    return config.GENERATED_IMAGES_DIR / f"ai_{digest}.jpg"


def _prompt(item: dict) -> str:
    title = str(item.get("title_fa") or item.get("title") or "").strip()[:300]
    summary = str(item.get("summary_fa") or item.get("summary") or "").strip()[:1000]
    topic = str(item.get("topic") or "").strip()[:140]
    return (
        "Create a polished, square editorial illustration for a technology/news article. "
        "Make it clearly illustrative rather than a documentary photograph. Use a tasteful, "
        "professional magazine-art direction and a composition that remains legible as a small "
        "channel thumbnail. Do not include words, letters, logos, watermarks, UI text, or an "
        "identifiable real person's face. Do not invent extra factual details.\n\n"
        f"Topic: {topic or 'news'}\nHeadline: {title}\nStory context: {summary}"
    )


async def generate_news_image(item: dict) -> tuple[str, str]:
    """Create/cache an editorial illustration and return (served path, error code).

    This must only be called after source/RSS images have been checked and found
    absent. A stable file name makes retries and archive resends reuse the same
    image instead of generating repeatedly.
    """
    # A genuine publisher image always wins; this helper is only a fallback.
    if str(item.get("image") or "").strip():
        return "", "source_image_available"
    settings = _settings()
    if not settings:
        return "", "not_configured"
    base_url, model, api_key = settings
    destination = _asset_path(item)
    config.GENERATED_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.stat().st_size >= 1500:
        return f"/media/generated/{destination.name}", ""

    payload = {
        "model": model,
        "prompt": _prompt(item),
        "size": "1024x1024",
        "n": 1,
        "response_format": "b64_json",
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(90.0), follow_redirects=True) as client:
            response = await client.post(f"{base_url}/images/generations", json=payload, headers=headers)
            # Some OpenAI-compatible image services return base64 by default and
            # reject response_format. Retry only for that compatibility error.
            if response.status_code in (400, 422) and "response_format" in response.text.lower():
                payload.pop("response_format", None)
                response = await client.post(f"{base_url}/images/generations", json=payload, headers=headers)
            if response.status_code >= 400:
                return "", f"image_api_http_{response.status_code}"
            data = response.json()
            rows = data.get("data") or data.get("images") or []
            first = rows[0] if isinstance(rows, list) and rows else {}
            raw = b""
            if isinstance(first, dict):
                encoded = first.get("b64_json") or first.get("base64")
                if encoded:
                    raw = base64.b64decode(str(encoded), validate=True)
                else:
                    image_url = str(first.get("url") or first.get("image_url") or "").strip()
                    if image_url.startswith(("http://", "https://")):
                        image_response = await client.get(image_url)
                        if image_response.status_code < 400:
                            raw = image_response.content
            elif isinstance(first, str) and first.startswith("data:image/") and "," in first:
                raw = base64.b64decode(first.split(",", 1)[1], validate=True)
            normalized = _normalize_image(raw)
            if not normalized:
                return "", "image_api_invalid_image"
            temp_path = destination.with_suffix(".tmp")
            temp_path.write_bytes(normalized)
            os.replace(temp_path, destination)
            return f"/media/generated/{destination.name}", ""
    except (httpx.HTTPError, OSError, ValueError, KeyError, IndexError):
        return "", "image_api_request_failed"
    except Exception:  # noqa: BLE001 — image fallback must never crash a news run
        return "", "image_api_request_failed"
