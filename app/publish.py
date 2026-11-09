"""Destination adapters + message rendering — real delivery, real limits.

Every adapter shares one contract::

    await send_message(destination, text) -> (ok, detail)
    await send_photo(destination, photo_url, caption) -> (ok, detail)
    await verify(destination) -> (ok, detail, info)
"""

from __future__ import annotations

import asyncio
import html
import io
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from . import config, db, feeds

TAG_RE = re.compile(r"<[^>]+>")

PLATFORM_META = {p["id"]: p for p in config.PLATFORMS}

TELEGRAM_API = "https://api.telegram.org"
BALE_API = "https://tapi.bale.ai"
EITAA_API = "https://eitaayar.ir/api"
RUBIKA_API = "https://botapi.rubika.ir/v3"

PLATFORM_RULES: dict[str, dict[str, Any]] = {
    "telegram": {
        "text": 4096,
        "caption": 1024,
        "html": True,
        "markdown": True,
        "photo": "url_or_upload",
        "photo_max": 10 * 1024 * 1024,
        "min_interval": 2.5,
        "doc": "https://core.telegram.org/bots/api",
        "notes_fa": "متن تا ۴۰۹۶ کاراکتر، کپشن عکس تا ۱۰۲۴ کاراکتر با قالب‌بندی HTML؛ ربات باید در کانال ادمین باشد.",
        "notes_en": "4096-char text, 1024-char HTML caption; the bot must be an admin of the channel.",
    },
    "bale": {
        "text": 4096,
        "caption": 4096,
        "html": False,
        "markdown": False,
        "photo": "url_or_upload",
        "photo_max": 10 * 1024 * 1024,
        "min_interval": 1.5,
        "doc": "https://docs.bale.ai/",
        "notes_fa": "متن و کپشن تا ۴۰۹۶ کاراکتر. قالب‌بندی HTML ندارد و به‌صورت متن تمیز ارسال می‌شود.",
        "notes_en": "Text and caption up to 4096 characters. Plain text mode.",
    },
    "eitaa": {
        "text": 4096,
        "caption": 4096,
        "html": False,
        "markdown": False,
        "photo": "upload",
        "photo_max": 10 * 1024 * 1024,
        "min_interval": 2.0,
        "doc": "https://eitaayar.ir",
        "notes_fa": "روش ارسال sendMessage و sendFile است (sendPhoto ندارد)؛ آیدی کانال بدون @ و ربات باید ادمین باشد.",
        "notes_en": "Uses sendMessage/sendFile (no sendPhoto); channel id without @, bot must be admin.",
    },
    "rubika": {
        "text": 4000,
        "caption": 4000,
        "html": False,
        "markdown": False,
        "photo": "request_upload",
        "photo_max": 10 * 1024 * 1024,
        "min_interval": 2.0,
        "doc": "https://rubika.ir/botapi/methods",
        "notes_fa": "عکس سه مرحله آپلود می‌شود (requestSendFile → upload → sendFile)؛ متن ساده.",
        "notes_en": "Photos use 3-step upload (requestSendFile → upload → sendFile); plain text.",
    },
    "webhook": {
        "text": 20000,
        "caption": 20000,
        "html": True,
        "markdown": True,
        "photo": "none",
        "photo_max": 0,
        "min_interval": 0.0,
        "doc": "",
        "notes_fa": "هر آیتم به‌صورت JSON به آدرس شما POST می‌شود (متن، plain_text و تصویر).",
        "notes_en": "Each item is POSTed to your URL as JSON (text, plain_text and image).",
    },
}

MAX_IMAGE_BYTES = 10 * 1024 * 1024
_last_sent: dict[str, float] = {}


def rules_for(platform: str) -> dict[str, Any]:
    return PLATFORM_RULES.get((platform or "").lower(), PLATFORM_RULES["telegram"])


def supports_photo(platform: str) -> bool:
    platform = (platform or "").lower()
    if PLATFORM_META.get(platform, {}).get("supports_photo"):
        return True
    return rules_for(platform)["photo"] != "none"


def supports_html(platform: str) -> bool:
    return bool(rules_for(platform)["html"])


def strip_tags(text: str) -> str:
    return html.unescape(TAG_RE.sub("", text or ""))


def _truncate_clean(text: str, limit: int) -> str:
    """Truncate plain text cleanly at paragraph or sentence boundary."""
    text = (text or "").strip()
    if limit <= 0 or len(text) <= limit:
        return text
    cut = text[: max(1, limit - 1)]
    for sep in ("\n\n", ". ", "۔ ", "؟ ", "! ", "؛ ", "\n", " "):
        idx = cut.rfind(sep)
        if idx >= int(limit * 0.62):
            cut = cut[: idx + (1 if sep.strip() and sep.strip() != "؛" else 0)]
            break
    return cut.rstrip() + "…"


def platform_limit(platform: str, kind: str = "text") -> int:
    hard = int(rules_for(platform)[kind])
    if kind != "text":
        return hard
    configured = int(db.get_setting("max_message_chars") or 3800)
    return min(configured, hard)


# ── HTTP plumbing ───────────────────────────────────────────────────────────


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=config.HTTP_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": config.USER_AGENT},
    )


def _reply_error(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return (response.text or "").strip()[:300] or f"http {response.status_code}"
    if isinstance(data, dict):
        for key in ("description", "error", "status_det", "message", "detail"):
            if data.get(key):
                return str(data[key])[:300]
        return str(data)[:300]
    return str(data)[:300]


def _retry_after(response: httpx.Response) -> float:
    header = response.headers.get("retry-after")
    if header and header.isdigit():
        return min(float(header), 8.0)
    try:
        data = response.json()
        params = (data or {}).get("parameters") or {}
        if isinstance(params, dict) and params.get("retry_after"):
            return min(float(params["retry_after"]), 8.0)
    except ValueError:
        pass
    return 3.0


def _check_generic(response: httpx.Response) -> tuple[bool, str]:
    if response.status_code == 429:
        return False, f"rate_limited:{int(_retry_after(response))}s"
    if response.status_code >= 400:
        return False, f"http_{response.status_code}:{_reply_error(response)}"
    try:
        data = response.json()
    except ValueError:
        return True, "ok"
    if isinstance(data, dict) and data.get("ok") is False:
        return False, _reply_error(response)
    return True, "ok"


def _check_rubika(response: httpx.Response) -> tuple[bool, str]:
    if response.status_code >= 400:
        return False, f"http_{response.status_code}:{_reply_error(response)}"
    try:
        data = response.json()
    except ValueError:
        return True, "ok"
    if isinstance(data, dict):
        status = str(data.get("status", "")).upper()
        if status and status != "OK":
            return False, str(data.get("status_det") or data.get("dev_message") or status)[:300]
    return True, "ok"


async def _request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    json: dict | None = None,
    data: dict | None = None,
    files: dict | None = None,
    headers: dict | None = None,
    checker=_check_generic,
) -> tuple[bool, str, dict]:
    for attempt in (0, 1):
        try:
            response = await client.request(
                method, url, json=json, data=data, files=files, headers=headers or {}
            )
        except httpx.TimeoutException:
            return False, "network_error:timeout", {}
        except httpx.HTTPError as exc:
            return False, f"network_error:{exc.__class__.__name__}", {}
        if response.status_code == 429 and attempt == 0:
            await asyncio.sleep(_retry_after(response))
            continue
        ok, detail = checker(response)
        payload: dict = {}
        if ok:
            try:
                body = response.json()
                payload = body if isinstance(body, dict) else {"raw": body}
            except ValueError:
                payload = {}
        return ok, detail, payload
    return False, "rate_limited", {}


async def _throttle(destination: dict) -> None:
    key = str(destination.get("id") or destination.get("chat_id") or "")
    gap = float(rules_for(destination.get("platform", "")).get("min_interval") or 0)
    if not key or gap <= 0:
        return
    last = _last_sent.get(key)
    if last is not None:
        wait = gap - (time.monotonic() - last)
        if wait > 0:
            await asyncio.sleep(min(wait, gap))
    _last_sent[key] = time.monotonic()


def _token_of(destination: dict) -> str:
    return (destination.get("bot_token") or "").strip()


def _chat_of(destination: dict) -> str:
    return (destination.get("chat_id") or "").strip()


def _parse_mode(destination: dict) -> str | None:
    platform = (destination.get("platform") or "").lower()
    mode = (destination.get("parse_mode") or "HTML").upper()
    rules = rules_for(platform)
    if mode == "HTML" and rules["html"]:
        return "HTML"
    if mode == "MARKDOWN" and rules["markdown"]:
        return "Markdown"
    return None


# ── Real News Image Downloader & Validator ──────────────────────────────────


async def fetch_image(url: str) -> tuple[bytes, str, str] | None:
    """Load a source image or persistent generated asset; reject logos/tiny files."""
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.path.startswith("/media/generated/"):
        name = Path(parsed.path).name
        if not re.fullmatch(r"ai_[0-9a-f]{24}\.jpg", name):
            return None
        path = config.GENERATED_IMAGES_DIR / name
        try:
            data = path.read_bytes()
            if 1500 <= len(data) <= MAX_IMAGE_BYTES:
                return data, name, "image/jpeg"
        except OSError:
            return None
        return None
    if not url.startswith(("http://", "https://")) or feeds.is_logo_or_junk(url):
        return None
    try:
        async with _client() as client:
            async with client.stream("GET", url) as response:
                if response.status_code >= 400:
                    return None
                ctype = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
                if ctype and (not ctype.startswith("image/") or "svg" in ctype):
                    return None
                buffer = bytearray()
                async for chunk in response.aiter_bytes():
                    buffer.extend(chunk)
                    if len(buffer) > MAX_IMAGE_BYTES:
                        return None
    except (httpx.HTTPError, OSError):
        return None

    data = bytes(buffer)
    if len(data) < 1500:  # 1x1 pixels / tiny icons are < 1.5 KB
        return None

    try:
        from PIL import Image

        image = Image.open(io.BytesIO(data))
        image.load()
        w, h = image.size
        # Reject icons, avatars, tiny badges or ultra-wide header logo strips
        if w < 180 or h < 115:
            return None
        ratio = w / max(h, 1)
        if ratio > 4.6 or ratio < 0.22:
            return None

        if ctype in {"image/jpeg", "image/jpg", "image/png"} and len(data) <= 8.5 * 1024 * 1024 and image.mode in ("RGB", "L"):
            ext = "png" if ctype.endswith("png") else "jpg"
            return data, f"photo.{ext}", ctype

        if image.mode not in ("RGB", "L"):
            bg = Image.new("RGB", image.size, (15, 23, 42))
            if "A" in image.getbands():
                bg.paste(image, mask=image.split()[-1])
                image = bg
            else:
                image = image.convert("RGB")
        image.thumbnail((2560, 2560))
        out = io.BytesIO()
        image.save(out, format="JPEG", quality=88, optimize=True)
        return out.getvalue(), "photo.jpg", "image/jpeg"
    except Exception:
        if ctype in {"image/jpeg", "image/jpg", "image/png"} and len(data) <= 8.5 * 1024 * 1024:
            return data, "photo.jpg", ctype
        return None


# ── Platform Adapters ───────────────────────────────────────────────────────


async def _telegram_like(
    destination: dict, method: str, payload: dict, files: dict | None = None
) -> tuple[bool, str]:
    url = f"{TELEGRAM_API}/bot{_token_of(destination)}/{method}"
    async with _client() as client:
        ok, detail, _ = await _request(client, "POST", url, json=payload, files=files)
    return ok, detail


async def send_telegram(destination: dict, text: str) -> tuple[bool, str]:
    payload: dict[str, Any] = {
        "chat_id": _chat_of(destination),
        "text": text,
        "disable_web_page_preview": True,
    }
    mode = _parse_mode(destination)
    if mode:
        payload["parse_mode"] = mode
    return await _telegram_like(destination, "sendMessage", payload)


async def send_bale(destination: dict, text: str) -> tuple[bool, str]:
    url = f"{BALE_API}/bot{_token_of(destination)}/sendMessage"
    payload = {"chat_id": _chat_of(destination), "text": strip_tags(text)}
    async with _client() as client:
        ok, detail, _ = await _request(client, "POST", url, json=payload)
    return ok, detail


async def send_eitaa(destination: dict, text: str) -> tuple[bool, str]:
    url = f"{EITAA_API}/{_token_of(destination)}/sendMessage"
    payload = {"chat_id": _chat_of(destination), "text": strip_tags(text)}
    async with _client() as client:
        ok, detail, _ = await _request(client, "POST", url, json=payload)
    return ok, detail


async def send_rubika(destination: dict, text: str) -> tuple[bool, str]:
    url = f"{RUBIKA_API}/{_token_of(destination)}/sendMessage"
    payload = {"chat_id": _chat_of(destination), "text": strip_tags(text)}
    async with _client() as client:
        ok, detail, _ = await _request(client, "POST", url, json=payload, checker=_check_rubika)
    return ok, detail


async def send_webhook(destination: dict, text: str) -> tuple[bool, str]:
    url = _chat_of(destination)
    if not url.startswith("http"):
        return False, "webhook_url_invalid"
    payload = {
        "platform": "webhook",
        "chat_id": destination.get("name", ""),
        "text": text,
        "plain_text": strip_tags(text),
        "token": destination.get("bot_token", ""),
    }
    headers = {"X-Token": destination["bot_token"]} if destination.get("bot_token") else {}
    async with _client() as client:
        ok, detail, _ = await _request(client, "POST", url, json=payload, headers=headers)
    return ok, detail


PLATFORMS = {
    "telegram": send_telegram,
    "bale": send_bale,
    "eitaa": send_eitaa,
    "rubika": send_rubika,
    "webhook": send_webhook,
}


# ── Photo Delivery ──────────────────────────────────────────────────────────


async def _send_photo_telegram(destination: dict, image, caption: str) -> tuple[bool, str]:
    mode = _parse_mode(destination)
    chat_id = _chat_of(destination)
    payload: dict[str, Any] = {"chat_id": chat_id, "caption": caption}
    if mode:
        payload["parse_mode"] = mode
    if image:
        data, filename, mime = image
        files = {"photo": (filename, data, mime)}
        url = f"{TELEGRAM_API}/bot{_token_of(destination)}/sendPhoto"
        async with _client() as client:
            ok, detail, _ = await _request(client, "POST", url, data=payload, files=files)
        return ok, detail
    return False, "image_unavailable"


async def _send_photo_bale(destination: dict, image, caption: str, photo_url: str) -> tuple[bool, str]:
    chat_id = _chat_of(destination)
    url = f"{BALE_API}/bot{_token_of(destination)}/sendPhoto"
    plain_caption = _truncate_clean(strip_tags(caption), platform_limit("bale", "caption"))
    if image:
        data, filename, mime = image
        async with _client() as client:
            ok, detail, _ = await _request(
                client,
                "POST",
                url,
                data={"chat_id": chat_id, "caption": plain_caption},
                files={"photo": (filename, data, mime)},
            )
        return ok, detail
    if photo_url and not feeds.is_logo_or_junk(photo_url):
        async with _client() as client:
            ok, detail, _ = await _request(
                client,
                "POST",
                url,
                json={"chat_id": chat_id, "photo": photo_url, "caption": plain_caption},
            )
        return ok, detail
    return False, "image_unavailable"


async def _send_photo_eitaa(destination: dict, image, caption: str, photo_url: str) -> tuple[bool, str]:
    url = f"{EITAA_API}/{_token_of(destination)}/sendFile"
    chat_id = _chat_of(destination)
    plain_caption = _truncate_clean(strip_tags(caption), platform_limit("eitaa", "caption"))
    if image:
        data, filename, mime = image
        async with _client() as client:
            ok, detail, _ = await _request(
                client,
                "POST",
                url,
                data={"chat_id": chat_id, "caption": plain_caption},
                files={"file": (filename, data, mime)},
            )
        if ok:
            return ok, detail
    if photo_url and not feeds.is_logo_or_junk(photo_url):
        async with _client() as client:
            ok, detail, _ = await _request(
                client,
                "POST",
                url,
                data={"chat_id": chat_id, "file": photo_url, "caption": plain_caption},
            )
        return ok, detail
    return False, "image_unavailable"


async def _send_photo_rubika(destination: dict, image, caption: str) -> tuple[bool, str]:
    token = _token_of(destination)
    chat_id = _chat_of(destination)
    text = _truncate_clean(strip_tags(caption), platform_limit("rubika", "caption"))
    if not image:
        return False, "rubika_upload_unavailable"
    async with _client() as client:
        ok, detail, body = await _request(
            client,
            "POST",
            f"{RUBIKA_API}/{token}/requestSendFile",
            json={"type": "Image"},
            checker=_check_rubika,
        )
        if not ok:
            return ok, detail
        info = (body.get("data") or {}) if isinstance(body, dict) else {}
        upload_url = info.get("upload_url") or ""
        file_id = info.get("file_id") or ""
        if not upload_url or not file_id:
            return False, "rubika_upload_unavailable"
        data, filename, mime = image
        up = await client.request("POST", upload_url, files={"file": (filename, data, mime)})
        if up.status_code >= 400:
            return False, f"http_{up.status_code}:{_reply_error(up)}"
        ok, detail, _ = await _request(
            client,
            "POST",
            f"{RUBIKA_API}/{token}/sendFile",
            json={"chat_id": chat_id, "file_id": file_id, "text": text},
            checker=_check_rubika,
        )
    return ok, detail


async def send_photo(destination: dict, photo_url: str, caption: str) -> tuple[bool, str]:
    """Send real news photo + HTML/plain caption; returns (False, ...) if image is logo/broken."""
    platform = (destination.get("platform") or "telegram").lower()
    rules = rules_for(platform)
    if rules["photo"] == "none":
        return await send_message(destination, caption)
    image = await fetch_image(photo_url) if photo_url else None
    if image is None:
        return False, "image_rejected_or_unavailable"

    await _throttle(destination)
    if platform == "telegram":
        # Preserve HTML formatting in Telegram captions when within 1024 visible chars
        visible_len = len(strip_tags(caption))
        safe_caption = (
            caption
            if visible_len <= platform_limit("telegram", "caption")
            else _truncate_clean(strip_tags(caption), platform_limit("telegram", "caption"))
        )
        return await _send_photo_telegram(destination, image, safe_caption)
    if platform == "bale":
        return await _send_photo_bale(destination, image, caption, photo_url)
    if platform == "eitaa":
        return await _send_photo_eitaa(destination, image, caption, photo_url)
    if platform == "rubika":
        return await _send_photo_rubika(destination, image, caption)
    return await send_message(destination, caption)


# ── Public Send & Verify API ────────────────────────────────────────────────


async def send_message(destination: dict, text: str) -> tuple[bool, str]:
    platform = (destination.get("platform") or "telegram").lower()
    handler = PLATFORMS.get(platform)
    if handler is None:
        return False, "platform_unsupported"
    if platform != "webhook" and not _token_of(destination):
        return False, "token_missing"
    if not _chat_of(destination):
        return False, "chat_id_missing"
    limit = platform_limit(platform, "text")
    if not supports_html(platform):
        text = _truncate_clean(strip_tags(text), limit)
    elif len(strip_tags(text)) > limit:
        text = _truncate_clean(strip_tags(text), limit)
    if not text.strip():
        return False, "empty_message"
    await _throttle(destination)
    return await handler(destination, text)


async def verify(destination: dict) -> tuple[bool, str, dict]:
    platform = (destination.get("platform") or "telegram").lower()
    token = _token_of(destination)
    chat_id = _chat_of(destination)
    if platform == "webhook":
        return (
            (True, "webhook_ready", {"url": chat_id})
            if chat_id.startswith("http")
            else (False, "webhook_url_invalid", {})
        )
    if not token:
        return False, "token_missing", {}
    if not chat_id:
        return False, "chat_id_missing", {}

    async with _client() as client:
        if platform in {"telegram", "bale"}:
            base = TELEGRAM_API if platform == "telegram" else BALE_API
            ok, detail, body = await _request(client, "GET", f"{base}/bot{token}/getMe")
            if not ok:
                return False, f"getMe:{detail}", {}
            me = body.get("result") or {}
            info = {"bot": me.get("username") or me.get("first_name") or "", "id": me.get("id")}
            if platform == "telegram":
                ok, detail, body = await _request(
                    client,
                    "POST",
                    f"{base}/bot{token}/getChat",
                    json={"chat_id": chat_id},
                )
                if not ok:
                    return False, f"getChat:{detail}", info
                chat = body.get("result") or {}
                info["chat"] = chat.get("title") or chat.get("username") or chat_id
                info["type"] = chat.get("type") or ""
            return True, "ready", info

        if platform == "eitaa":
            ok, detail, body = await _request(client, "GET", f"{EITAA_API}/{token}/getMe")
            if ok:
                me = body.get("result") or body.get("data") or {}
                return True, "ready", {"bot": me.get("bot") or me.get("name") or "eitaa"}
            if detail.startswith("network_error"):
                return False, detail, {}
            return True, "token_unverified", {"chat": chat_id, "note": detail}

        if platform == "rubika":
            ok, detail, body = await _request(
                client, "POST", f"{RUBIKA_API}/{token}/getMe", json={}, checker=_check_rubika
            )
            if not ok:
                return False, f"getMe:{detail}", {}
            data = (body.get("data") or {}) if isinstance(body, dict) else {}
            bot = data.get("bot") or {}
            return True, "ready", {"bot": bot.get("bot_title") or bot.get("username") or "rubika"}

    return False, "platform_unsupported", {}


async def test_destination(destination: dict) -> tuple[bool, str]:
    text = (
        "✅ <b>روزنه با موفقیت متصل شد.</b>\n"
        "این یک پیام آزمایشی است؛ خبرهای کامل، عکس‌های واقعی خبر و تحلیل‌های هوشمند طبق تنظیمات شما در این کانال منتشر می‌شوند.\n\n"
        "✅ Rozaneh is connected and ready."
    )
    return await send_message(destination, text)


# ── Message & Caption Rendering ─────────────────────────────────────────────


def _signature_enabled() -> bool:
    return (db.get_setting("signature_enabled") or "1") != "0"


def _use_html(destination: dict) -> bool:
    return _parse_mode(destination) == "HTML"


def _generated_image_label(item: dict) -> str:
    image_path = urlparse(str(item.get("image") or "")).path
    if not image_path.startswith("/media/generated/ai_"):
        return ""
    return "🖼️ AI-generated editorial illustration" if str(item.get("lang") or "").startswith("en") else "🖼️ تصویر تولیدشده با هوش مصنوعی"


def _body_overhead(item: dict, destination: dict, with_signature: bool | None = None) -> int:
    """Estimate the visible non-body text so a summary can be authored to fit."""
    if with_signature is None:
        with_signature = _signature_enabled()
    use_html = _use_html(destination)
    title = (item.get("title_fa") or item.get("title") or "").strip()
    show_topic = int(item.get("show_topic", 1)) != 0
    topic = (item.get("topic") or "").strip() if show_topic else ""
    show_source = bool(int(item.get("show_source") or 0))
    link = (item.get("link") or "").strip()
    source_label = (item.get("custom_source_label") or item.get("feed_title") or "منبع خبر").strip()
    footer = (destination.get("footer") or "").strip() if with_signature else ""
    global_footer = (db.get_setting("global_footer") or "").strip() if with_signature else ""

    tail_plain_parts: list[str] = []
    image_label = _generated_image_label(item)
    if image_label:
        tail_plain_parts.append(image_label)
    if topic:
        tail_plain_parts.append(topic)
    if footer:
        tail_plain_parts.append(footer if use_html else f"— {footer}")
    if global_footer and global_footer != footer:
        tail_plain_parts.append(global_footer)
    if show_source and link:
        tail_plain_parts.append(f"🔗 منبع: {source_label}" if use_html else f"🔗 منبع ({source_label}): {link}")
    return len(title) + sum(len(p) for p in tail_plain_parts) + (len(tail_plain_parts) + 2) * 2 + 8


def body_budget(
    item: dict,
    destination: dict,
    kind: str = "text",
    with_signature: bool | None = None,
) -> int:
    """Available visible characters for the body within a text post or photo caption."""
    platform = (destination.get("platform") or "telegram").lower()
    return max(0, platform_limit(platform, kind) - _body_overhead(item, destination, with_signature))


def _build_message(
    item: dict,
    destination: dict,
    *,
    char_limit: int,
    with_signature: bool | None = None,
) -> str:
    """Assemble title + news body + optional topic + optional signature + optional source at bottom."""
    if with_signature is None:
        with_signature = _signature_enabled()
    use_html = _use_html(destination)

    title = (item.get("title_fa") or item.get("title") or "").strip()
    body = (item.get("summary_fa") or item.get("summary") or "").strip()
    # Avoid duplicating headline verbatim if body starts with the exact same title
    if body and title and body.startswith(title):
        body = body[len(title) :].lstrip(" :—–-\n")

    show_topic = int(item.get("show_topic", 1)) != 0
    topic = (item.get("topic") or "").strip() if show_topic else ""

    # CRITICAL FIX: Source name/link is ONLY appended at the bottom if explicitly enabled!
    show_source = bool(int(item.get("show_source") or 0))
    link = (item.get("link") or "").strip()
    source_label = (item.get("custom_source_label") or item.get("feed_title") or "منبع خبر").strip()

    footer = (destination.get("footer") or "").strip() if with_signature else ""
    global_footer = (db.get_setting("global_footer") or "").strip() if with_signature else ""

    # Reserve the same fixed visible overhead used by body_budget().
    body_budget = max(0, char_limit - _body_overhead(item, destination, with_signature))
    fitted_body = _truncate_clean(body, body_budget) if (body and body_budget >= 45) else ""

    if use_html:
        parts: list[str] = []
        if title:
            parts.append(f"<b>{html.escape(title, quote=False)}</b>")
        if fitted_body:
            parts.append(html.escape(fitted_body, quote=False))
        image_label = _generated_image_label(item)
        if image_label:
            parts.append(html.escape(image_label, quote=False))
        if topic:
            parts.append(html.escape(topic, quote=False))
        if footer:
            parts.append(f"<i>{html.escape(footer, quote=False)}</i>")
        if global_footer and global_footer != footer:
            parts.append(f"<i>{html.escape(global_footer, quote=False)}</i>")
        if show_source and link:
            parts.append(
                f'🔗 منبع: <a href="{html.escape(link, quote=True)}">'
                f"{html.escape(source_label, quote=False)}</a>"
            )
    else:
        parts = []
        if title:
            parts.append(title)
        if fitted_body:
            parts.append(fitted_body)
        image_label = _generated_image_label(item)
        if image_label:
            parts.append(image_label)
        if topic:
            parts.append(topic)
        if footer:
            parts.append(f"— {footer}")
        if global_footer and global_footer != footer:
            parts.append(global_footer)
        if show_source and link:
            parts.append(f"🔗 منبع ({source_label}): {link}")

    return "\n\n".join(p for p in parts if p)


def render_item(item: dict, destination: dict, with_signature: bool | None = None) -> str:
    """Full text message for one news item (up to platform text limit)."""
    platform = (destination.get("platform") or "telegram").lower()
    limit = platform_limit(platform, "text")
    return _build_message(item, destination, char_limit=limit, with_signature=with_signature)


def render_caption(item: dict, destination: dict, with_signature: bool | None = None) -> str:
    """Rich multi-paragraph photo caption fitted cleanly to platform caption limit."""
    platform = (destination.get("platform") or "telegram").lower()
    limit = platform_limit(platform, "caption")
    return _build_message(item, destination, char_limit=limit, with_signature=with_signature)


def rules_payload() -> list[dict]:
    out = []
    for pid, rule in PLATFORM_RULES.items():
        meta = PLATFORM_META.get(pid, {})
        out.append(
            {
                "id": pid,
                "text": rule["text"],
                "caption": rule["caption"],
                "html": rule["html"],
                "photo": rule["photo"],
                "min_interval": rule["min_interval"],
                "doc": rule["doc"],
                "notes_fa": rule["notes_fa"],
                "notes_en": rule["notes_en"],
                "name_fa": meta.get("name_fa", pid),
                "name_en": meta.get("name_en", pid),
            }
        )
    return out
