"""Rozaneh — FastAPI application: panel API + SPA host (v1.08)."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from . import (
    analyzer,
    config,
    db,
    feeds,
    pipeline,
    publish,
    scheduler,
    security,
    secret_store,
    topics as topics_mod,
    translate,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
# Bot API credentials are part of Telegram request paths; suppress HTTPX request
# lines so neither those URLs nor webhook URLs can enter application logs.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("rozaneh")

STARTED_AT = time.time()
_BG_TASKS: set[asyncio.Task] = set()
_RATE_LIMIT_LOCK = threading.Lock()
_RATE_LIMIT_EVENTS: dict[tuple[str, str], list[float]] = {}
_RATE_LIMIT_MAX_KEYS = 4096


def _consume_rate_limit(scope: str, client_key: str, limit: int, window_seconds: int) -> bool:
    now = time.monotonic()
    key = (scope, client_key or "unknown")
    with _RATE_LIMIT_LOCK:
        recent = [stamp for stamp in _RATE_LIMIT_EVENTS.get(key, []) if now - stamp < window_seconds]
        if len(recent) >= limit:
            _RATE_LIMIT_EVENTS[key] = recent
            return False
        recent.append(now)
        _RATE_LIMIT_EVENTS[key] = recent
        if len(_RATE_LIMIT_EVENTS) > _RATE_LIMIT_MAX_KEYS:
            for item, stamps in list(_RATE_LIMIT_EVENTS.items()):
                if not stamps or now - stamps[-1] >= window_seconds:
                    _RATE_LIMIT_EVENTS.pop(item, None)
            if len(_RATE_LIMIT_EVENTS) > _RATE_LIMIT_MAX_KEYS:
                oldest = min(
                    _RATE_LIMIT_EVENTS,
                    key=lambda item: _RATE_LIMIT_EVENTS[item][-1] if _RATE_LIMIT_EVENTS[item] else float("-inf"),
                )
                _RATE_LIMIT_EVENTS.pop(oldest, None)
        return True


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.get_conn()
    secret_migration = secret_store.migrate_legacy_contact_bot_token()
    if secret_migration == "encrypted_legacy":
        logger.info("legacy contact-bot token migrated to encrypted storage")
    elif secret_migration == "discarded_without_key":
        logger.warning("discarded plaintext contact-bot token because encrypted storage is not configured")
    logger.info("Rozaneh %s starting — data dir %s", config.VERSION, config.DATA_DIR)
    scheduler.start()
    try:
        yield
    finally:
        await scheduler.stop()


app = FastAPI(
    title="Rozaneh",
    version=config.VERSION,
    docs_url="/api/docs",
    redoc_url=None,
    lifespan=lifespan,
)

config.GENERATED_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
if config.STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")
    app.mount("/assets", StaticFiles(directory=str(config.STATIC_DIR / "assets")), name="assets")
    app.mount("/media/generated", StaticFiles(directory=str(config.GENERATED_IMAGES_DIR)), name="generated_images")

auth = Depends(security.require_auth)
creator_auth = Depends(security.require_creator_auth)


def fail(code: str, status: int = 400) -> None:
    raise HTTPException(status_code=status, detail=code)


# ── schemas ─────────────────────────────────────────────────────────────────


class LoginPayload(BaseModel):
    password: str


class CreatorLoginPayload(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


class ContactBotTokenPayload(BaseModel):
    bot_token: str = Field(default="", max_length=4096)


class FeedPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str | None = None
    url: str | None = None
    enabled: int | bool | None = None
    icon: str | None = None
    color: str | None = None
    show_url: int | bool | None = None
    show_source: int | bool | None = None
    custom_source_label: str | None = None
    default_topic_id: int | None = None
    full_article: int | bool | None = None


class BulkFeedPayload(BaseModel):
    text: str = ""
    show_source: int | bool = 0


class ReorderPayload(BaseModel):
    ids: list[int] = []


class TopicPayload(BaseModel):
    name: str | None = None
    name_en: str | None = None
    emoji: str | None = None
    keywords: str | None = None
    enabled: int | bool | None = None


class TopicTestPayload(BaseModel):
    title: str = ""
    summary: str = ""


class DestinationPayload(BaseModel):
    name: str | None = None
    platform: str | None = None
    chat_id: str | None = None
    bot_token: str | None = None
    topic_filter: str | None = None
    footer: str | None = None
    parse_mode: str | None = None
    enabled: int | bool | None = None


class JobPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str | None = None
    enabled: int | bool | None = None
    schedule_times: str | list[str] | None = None
    interval_minutes: int | None = None
    window_hours: int | None = None
    max_items: int | None = None
    translate: int | bool | None = None
    include_summary: int | bool | None = None
    full_text: int | bool | None = None
    send_image: int | bool | None = None
    show_topic: int | bool | None = None
    only_unseen: int | bool | None = None
    filter_mode: str | None = None
    exclude_keywords: str | None = None
    feed_ids: list[int] | None = None
    topic_ids: list[int] | None = None
    destination_ids: list[int] | None = None


class RunPayload(BaseModel):
    dry_run: bool = False
    max_items: int | None = None


class AnalyzerCreatePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    url: str
    custom_text: str = ""
    include_link: int | bool = 0
    send_image: int | bool = 1
    wait: bool = False


class AnalyzerPatchPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str | None = None
    channel_draft: str | None = None
    include_link: int | bool | None = None
    send_image: int | bool | None = None


class AnalyzerPublishPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    destination_ids: list[int] | None = None
    channel_draft: str | None = None
    include_link: int | bool | None = None
    send_image: int | bool | None = None


class AnalyzerModelsPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    provider: str = "openai_compatible"
    base_url: str = Field(default="", max_length=500)
    api_key: str = Field(default="", max_length=4096)


class SettingsPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    panel_title: str | None = None
    timezone: str | None = None
    theme: str | None = None
    language: str | None = None
    translate_provider: str | None = None
    translate_fallback: str | None = None
    translate_target: str | None = None
    translate_post_edit: int | bool | None = None
    translate_preserve: int | bool | None = None
    translate_glossary: str | None = None
    deepseek_base_url: str | None = None
    deepseek_model: str | None = None
    deepseek_api_key: str | None = None
    openai_base_url: str | None = None
    openai_model: str | None = None
    openai_api_key: str | None = None
    analysis_api_provider: str | None = None
    analysis_api_base_url: str | None = None
    analysis_api_model: str | None = None
    analysis_api_key: str | None = None
    image_generation_enabled: int | bool | None = None
    image_api_base_url: str | None = None
    image_api_model: str | None = None
    image_api_key: str | None = None
    global_footer: str | None = None
    max_message_chars: str | int | None = None
    signature_enabled: int | bool | None = None
    feedback_webhook: str | None = None


class CreatorsPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    creator1_name: str | None = None
    creator1_role_fa: str | None = None
    creator1_role_en: str | None = None
    creator1_bio_fa: str | None = None
    creator1_bio_en: str | None = None
    creator1_quote_fa: str | None = None
    creator1_quote_en: str | None = None
    creator1_skills: str | None = None
    creator1_avatar: str | None = None
    creator1_telegram: str | None = None
    creator1_github: str | None = None
    creator1_email: str | None = None
    creator1_website: str | None = None
    creator2_name: str | None = None
    creator2_role_fa: str | None = None
    creator2_role_en: str | None = None
    creator2_bio_fa: str | None = None
    creator2_bio_en: str | None = None
    creator2_quote_fa: str | None = None
    creator2_quote_en: str | None = None
    creator2_skills: str | None = None
    creator2_avatar: str | None = None
    creator2_telegram: str | None = None
    creator2_github: str | None = None
    creator2_email: str | None = None
    creator2_website: str | None = None
    edu_youtube_id: str | None = None
    edu_youtube_url: str | None = None
    edu_telegram_id: str | None = None
    edu_telegram_url: str | None = None
    edu_topics_fa: str | None = None
    edu_topics_en: str | None = None


class PasswordPayload(BaseModel):
    current_password: str
    new_password: str = Field(min_length=5)


class ResendPayload(BaseModel):
    destination_ids: list[int] | None = None


class PreviewPayload(BaseModel):
    destination_id: int | None = None


class FeedbackPayload(BaseModel):
    kind: str = Field(default="message", max_length=20)
    name: str = Field(default="", max_length=60)
    contact: str = Field(default="", max_length=80)
    message: str = Field(default="", max_length=3500)


class ImportPayload(BaseModel):
    payload: dict[str, Any]
    confirm: bool = False


# ── helpers ─────────────────────────────────────────────────────────────────


def as_int(value: Any, default: int = 1) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        return 1 if value else 0
    try:
        return 1 if int(value) else 0
    except (TypeError, ValueError):
        return default


def mask_secret(token: str) -> str:
    token = token or ""
    if not token:
        return ""
    if len(token) <= 10:
        return "•" * len(token)
    return f"{token[:6]}••••{token[-4:]}"


def feed_public(row: dict) -> dict:
    data = dict(row)
    data["is_ok"] = str(data.get("last_status", "")).startswith("ok")
    data["show_source"] = int(data.get("show_source") or 0)
    data["default_topic_id"] = int(data.get("default_topic_id") or 0)
    data["full_article"] = int(data.get("full_article") if data.get("full_article") is not None else 1)
    return data


def destination_public(row: dict) -> dict:
    data = dict(row)
    data["bot_token"] = mask_secret(data.get("bot_token", ""))
    data["has_token"] = bool(row.get("bot_token"))
    return data


def destination_export(row: dict) -> dict:
    """Keep destination settings portable without exporting stored credentials."""
    data = dict(row)
    data["bot_token"] = ""
    return data


def topic_public(row: dict) -> dict:
    data = dict(row)
    data["name_en"] = data.get("name_en") or data.get("name")
    return data


def job_public(row: dict) -> dict:
    data = dict(row)
    data["feed_ids"] = [int(x) for x in db.load_list(row.get("feed_ids"))]
    data["topic_ids"] = [int(x) for x in db.load_list(row.get("topic_ids"))]
    data["destination_ids"] = [int(x) for x in db.load_list(row.get("destination_ids"))]
    data["filter_mode"] = data.get("filter_mode") or "smart"
    data["full_text"] = int(data.get("full_text") if data.get("full_text") is not None else 1)
    data["show_topic"] = int(data.get("show_topic") if data.get("show_topic") is not None else 1)
    nxt = scheduler.next_run(row)
    data["next_run"] = nxt.replace(microsecond=0).isoformat() if nxt else ""
    try:
        data["last_result_obj"] = db.load_list(row.get("last_result")) or _json_or_none(row.get("last_result"))
    except Exception:  # noqa: BLE001
        data["last_result_obj"] = None
    return data


def _json_or_none(raw: Any) -> Any:
    import json

    if not raw:
        return None
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else None
    except (TypeError, ValueError):
        return None


def clean_schedule(value: str | list[str] | None) -> str:
    if value is None:
        return "[]"
    parts = value if isinstance(value, list) else str(value).replace("،", ",").split(",")
    cleaned: list[str] = []
    for part in parts:
        part = str(part).strip()
        if ":" not in part:
            continue
        hh, _, mm = part.partition(":")
        try:
            hour, minute = int(hh), int(mm)
        except ValueError:
            continue
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            continue
        token = f"{hour:02d}:{minute:02d}"
        if token not in cleaned:
            cleaned.append(token)
    return db.dump(sorted(cleaned))


SECRET_SETTINGS = {
    "password_hash", "password_salt", "deepseek_api_key", "openai_api_key",
    "analysis_api_key", "image_api_key", "contact_bot_token", "contact_bot_encryption_key",
    "feedback_webhook",
}


def _contact_bot_token() -> str:
    # Creator-authenticated UI changes take precedence. UI-managed values are
    # encrypted at rest; a deployment-provided value remains in the host secret
    # store. The plaintext is never returned by an API response.
    stored = db.get_setting("contact_bot_token")
    if stored:
        decrypted = secret_store.decrypt_contact_bot_token(stored)
        if decrypted:
            return decrypted
    return (config.CONTACT_BOT_TOKEN or "").strip()


def settings_public() -> dict:
    data = db.all_settings()
    for key in SECRET_SETTINGS:
        data.pop(key, None)
    key_flags = {
        "deepseek_api_key": "deepseek_key_set",
        "openai_api_key": "openai_key_set",
        "analysis_api_key": "analysis_api_key_set",
        "image_api_key": "image_api_key_set",
        "feedback_webhook": "feedback_webhook_set",
    }
    for key, flag in key_flags.items():
        # Never send credential fragments back to the browser; the boolean flag
        # and input placeholder indicate whether a key is already configured.
        data[key] = ""
        data[flag] = bool(db.get_setting(key))
    data["password_is_bootstrap"] = security.password_is_bootstrap()
    return data


def creators_public() -> list[dict]:
    out = []
    for idx in (1, 2):
        skills_raw = db.get_setting(f"creator{idx}_skills")
        skills = [s.strip() for s in skills_raw.split(",") if s.strip()]
        out.append(
            {
                "slot": idx,
                "name": db.get_setting(f"creator{idx}_name"),
                "role_fa": db.get_setting(f"creator{idx}_role_fa"),
                "role_en": db.get_setting(f"creator{idx}_role_en"),
                "bio_fa": db.get_setting(f"creator{idx}_bio_fa"),
                "bio_en": db.get_setting(f"creator{idx}_bio_en"),
                "quote_fa": db.get_setting(f"creator{idx}_quote_fa"),
                "quote_en": db.get_setting(f"creator{idx}_quote_en"),
                "skills": skills,
                "skills_raw": skills_raw,
                "avatar": db.get_setting(f"creator{idx}_avatar"),
                "telegram": db.get_setting(f"creator{idx}_telegram"),
                "github": db.get_setting(f"creator{idx}_github"),
                "email": db.get_setting(f"creator{idx}_email"),
                "website": db.get_setting(f"creator{idx}_website"),
            }
        )
    return out


def edu_public() -> dict:
    return {
        "youtube_id": db.get_setting("edu_youtube_id") or "@nextgen-ain8n",
        "youtube_url": db.get_setting("edu_youtube_url") or "https://youtube.com/@nextgen-ain8n",
        "telegram_id": db.get_setting("edu_telegram_id") or "@nextgen_ain8n",
        "telegram_url": db.get_setting("edu_telegram_url") or "https://t.me/nextgen_ain8n",
        "topics_fa": db.get_setting("edu_topics_fa") or "",
        "topics_en": db.get_setting("edu_topics_en") or "",
    }


# ── meta / auth ─────────────────────────────────────────────────────────────


@app.get("/api/meta")
async def meta(request: Request) -> dict:
    return {
        "app": config.APP_NAME,
        "app_fa": config.APP_NAME_FA,
        "version": config.VERSION,
        "version_step": config.VERSION_STEP,
        "tagline": config.APP_TAGLINE,
        "tagline_fa": config.APP_TAGLINE_FA,
        "themes": config.THEMES,
        "languages": config.LANGUAGES,
        "platforms": config.PLATFORMS,
        "platform_rules": publish.rules_payload(),
        "translation_providers": config.TRANSLATION_PROVIDERS,
        "authenticated": security.is_authenticated(request),
        "bootstrap_password": security.password_is_bootstrap(),
        "defaults": {
            "theme": db.get_setting("theme") or "slate",
            "language": db.get_setting("language") or "fa",
            "timezone": db.get_setting("timezone") or config.DEFAULT_TZ,
            "panel_title": db.get_setting("panel_title") or config.APP_NAME,
        },
    }


@app.post("/api/login")
async def login(payload: LoginPayload, request: Request) -> JSONResponse:
    if not security.verify_password(payload.password):
        await asyncio.sleep(0.4)
        fail("password_wrong", 401)
    token = security.create_session(request.headers.get("user-agent", ""))
    response = JSONResponse({"ok": True})
    response.set_cookie(
        config.COOKIE_NAME,
        token,
        max_age=config.SESSION_DAYS * 86400,
        httponly=True,
        samesite="lax",
        secure=config.COOKIE_SECURE,
        path="/",
    )
    db.log(None, "login ok", level="auth", code="login_ok")
    return response


@app.post("/api/logout")
async def logout(request: Request) -> JSONResponse:
    token = security.current_token(request)
    if token:
        security.destroy_session(token)
    response = JSONResponse({"ok": True})
    response.delete_cookie(config.COOKIE_NAME, path="/")
    return response


@app.get("/api/me")
async def me(request: Request) -> dict:
    return {
        "authenticated": security.is_authenticated(request),
        "panel_title": db.get_setting("panel_title") or config.APP_NAME,
        "timezone": db.get_setting("timezone") or config.DEFAULT_TZ,
        "theme": db.get_setting("theme") or "slate",
        "language": db.get_setting("language") or "fa",
        "version": config.VERSION,
    }


@app.post("/api/password")
async def change_password(payload: PasswordPayload) -> dict:
    if not security.verify_password(payload.current_password):
        fail("password_current_wrong")
    security.set_password(payload.new_password)
    db.log(None, "password changed", level="auth", code="password_changed")
    return {"ok": True}


# ── settings & creators ─────────────────────────────────────────────────────


@app.get("/api/settings")
async def get_settings(_: None = auth) -> dict:
    return {"settings": settings_public()}


@app.patch("/api/settings")
async def patch_settings(payload: SettingsPayload, _: None = auth) -> dict:
    data = payload.model_dump(exclude_unset=True)

    for secret_key in ("deepseek_api_key", "openai_api_key", "analysis_api_key", "image_api_key"):
        if secret_key in data:
            value = (data.pop(secret_key) or "").strip()
            if value and "•" not in value:
                db.set_setting(secret_key, value)
            elif not value:
                db.set_setting(secret_key, "")

    for url_key in ("analysis_api_base_url", "image_api_base_url"):
        if data.get(url_key):
            parsed = urlparse(str(data[url_key]).strip())
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                fail("url_invalid")
            data[url_key] = str(data[url_key]).strip().rstrip("/")

    if data.get("timezone"):
        from zoneinfo import ZoneInfo

        try:
            ZoneInfo(str(data["timezone"]))
        except Exception:  # noqa: BLE001
            fail("timezone_invalid")

    if data.get("theme") and data["theme"] not in {t["id"] for t in config.THEMES}:
        fail("theme_invalid")
    if data.get("language") and data["language"] not in {l["id"] for l in config.LANGUAGES}:
        fail("language_invalid")
    if data.get("analysis_api_provider") and data["analysis_api_provider"] not in {"deepseek", "openai_compatible"}:
        fail("analysis_api_provider_invalid")

    flags = {"translate_post_edit", "translate_preserve", "signature_enabled", "image_generation_enabled"}
    for key, value in data.items():
        if key in flags:
            db.set_setting(key, str(as_int(value)))
        elif value is not None:
            db.set_setting(key, str(value).strip())
    return {"ok": True, "settings": settings_public()}


@app.get("/api/creators/auth/session")
async def creator_auth_session(request: Request) -> dict:
    slot = security.creator_session_slot(request)
    return {
        "configured": security.creator_auth_configured(),
        "authenticated": slot is not None,
    }


@app.post("/api/creators/auth/login")
async def creator_login(payload: CreatorLoginPayload, request: Request) -> JSONResponse:
    if not security.creator_auth_configured():
        await asyncio.sleep(0.3)
        fail("creator_auth_unconfigured", 503)
    client_key = request.client.host if request.client else "unknown"
    if not _consume_rate_limit("creator_login", client_key, limit=8, window_seconds=300):
        await asyncio.sleep(0.3)
        fail("creator_auth_rate_limited", 429)
    slot = security.authenticate_creator(payload.username, payload.password)
    if slot is None:
        await asyncio.sleep(0.4)
        fail("creator_auth_invalid", 401)
    token = security.create_creator_session(slot, request.headers.get("user-agent", ""))
    response = JSONResponse({"ok": True})
    response.set_cookie(
        config.CREATOR_COOKIE_NAME,
        token,
        max_age=config.CREATOR_SESSION_DAYS * 86400,
        httponly=True,
        samesite="lax",
        secure=config.COOKIE_SECURE,
        path="/",
    )
    db.log(None, f"creator editor login ok (slot {slot})", level="auth", code="creator_login_ok")
    return response


@app.post("/api/creators/auth/logout")
async def creator_logout(request: Request) -> JSONResponse:
    token = security.creator_current_token(request)
    if token:
        security.destroy_creator_session(token)
    response = JSONResponse({"ok": True})
    response.delete_cookie(config.CREATOR_COOKIE_NAME, path="/")
    return response


@app.get("/api/creators/contact-bot")
async def creator_contact_bot_status(_: int = creator_auth) -> dict:
    return {
        "configured": bool(_contact_bot_token()),
        "recipient_count": len(config.CONTACT_TELEGRAM_RECIPIENTS),
    }


@app.put("/api/creators/contact-bot")
async def creator_update_contact_bot(
    payload: ContactBotTokenPayload,
    _: int = creator_auth,
) -> dict:
    token = payload.bot_token.strip()
    if token:
        try:
            stored_token = secret_store.encrypt_contact_bot_token(token)
        except secret_store.SecretStorageUnavailable:
            fail("contact_bot_storage_unconfigured", 503)
    else:
        stored_token = ""
    db.set_setting("contact_bot_token", stored_token)
    db.log(
        None,
        "contact Telegram bot token updated" if token else "stored contact Telegram bot token cleared",
        level="auth",
        code="contact_bot_token_updated" if token else "contact_bot_token_cleared",
    )
    return {"ok": True, "configured": bool(_contact_bot_token())}


@app.get("/api/creators")
async def get_creators(_: None = auth) -> dict:
    return {"creators": creators_public(), "edu": edu_public()}


@app.patch("/api/creators")
async def patch_creators(payload: CreatorsPayload, creator_slot: int = creator_auth) -> dict:
    data = payload.model_dump(exclude_unset=True)
    editable = set(db.CREATOR_DEFAULTS)
    for key, value in data.items():
        if key not in editable or value is None:
            continue
        text = str(value).strip()
        limit = 6000 if "bio_" in key or key.startswith("edu_topics_") else 1200
        if len(text) > limit:
            fail("creator_field_too_long")
        db.set_setting(key, text)
    db.log(None, f"creator profile updated (slot {creator_slot})", level="auth", code="creator_profile_updated")
    return {"ok": True, "creators": creators_public(), "edu": edu_public()}


# ── feeds ───────────────────────────────────────────────────────────────────


@app.get("/api/feeds")
async def list_feeds(_: None = auth) -> dict:
    rows = db.query("SELECT * FROM feeds ORDER BY sort_order, id DESC")
    return {"feeds": [feed_public(r) for r in rows]}


@app.post("/api/feeds")
async def create_feed(payload: FeedPayload, _: None = auth) -> dict:
    url = (payload.url or "").strip()
    if not url.startswith(("http://", "https://")):
        fail("url_invalid")
    title = (payload.title or "").strip() or url.split("//", 1)[-1][:60]
    max_order = db.query_one("SELECT COALESCE(MAX(sort_order), 0) AS m FROM feeds")["m"]
    feed_id = db.execute(
        """INSERT INTO feeds
           (title, url, language, icon, color, show_url, show_source, custom_source_label,
            default_topic_id, full_article, sort_order, enabled, created_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            title,
            url,
            "auto",
            (payload.icon or "📰").strip()[:4],
            (payload.color or "teal").strip(),
            as_int(payload.show_url, 1),
            as_int(payload.show_source, 0),
            (payload.custom_source_label or "").strip()[:80],
            max(0, int(payload.default_topic_id or 0)),
            as_int(payload.full_article, 1),
            int(max_order) + 10,
            as_int(payload.enabled, 1),
            db.now_iso(),
        ),
    )
    return {"ok": True, "id": feed_id}


@app.post("/api/feeds/bulk")
async def bulk_feeds(payload: BulkFeedPayload, _: None = auth) -> dict:
    created = 0
    show_source = as_int(payload.show_source, 0)
    max_order = db.query_one("SELECT COALESCE(MAX(sort_order), 0) AS m FROM feeds")["m"]
    for line in (payload.text or "").splitlines():
        line = line.strip()
        if not line.startswith(("http://", "https://")):
            continue
        if db.query_one("SELECT id FROM feeds WHERE url = ?", (line,)):
            continue
        max_order += 10
        db.execute(
            """INSERT INTO feeds
               (title, url, language, icon, color, show_url, show_source, full_article, sort_order, enabled, created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                line.split("//", 1)[-1][:60],
                line,
                "auto",
                "📰",
                "teal",
                1,
                show_source,
                1,
                int(max_order),
                1,
                db.now_iso(),
            ),
        )
        created += 1
    return {"ok": True, "created": created}


@app.post("/api/feeds/reorder")
async def reorder_feeds(payload: ReorderPayload, _: None = auth) -> dict:
    for index, feed_id in enumerate(payload.ids):
        db.execute("UPDATE feeds SET sort_order = ? WHERE id = ?", ((index + 1) * 10, int(feed_id)))
    return {"ok": True}


@app.patch("/api/feeds/{feed_id}")
async def update_feed(feed_id: int, payload: FeedPayload, _: None = auth) -> dict:
    current = db.query_one("SELECT * FROM feeds WHERE id = ?", (feed_id,))
    if not current:
        fail("feed_not_found", 404)
    data = payload.model_dump(exclude_unset=True)
    fields: dict[str, Any] = {}
    for key in ("title", "url", "icon", "color", "custom_source_label"):
        if key in data and data[key] is not None:
            fields[key] = str(data[key]).strip()
    for bkey, default_v in (("show_url", 1), ("show_source", 0), ("full_article", 1), ("enabled", 1)):
        if bkey in data:
            fields[bkey] = as_int(data[bkey], default_v)
    if "default_topic_id" in data and data["default_topic_id"] is not None:
        fields["default_topic_id"] = max(0, int(data["default_topic_id"]))
    if fields:
        assignments = ", ".join(f"{k} = ?" for k in fields)
        db.execute(f"UPDATE feeds SET {assignments} WHERE id = ?", (*fields.values(), feed_id))
    return {"ok": True}


@app.delete("/api/feeds/{feed_id}")
async def delete_feed(feed_id: int, _: None = auth) -> dict:
    db.execute("DELETE FROM feeds WHERE id = ?", (feed_id,))
    return {"ok": True}


async def _validated_recent_items(items: list[dict], hours: int = 24, limit: int = 12) -> list[dict]:
    """Verify recent feed timestamps against canonical article metadata when available."""
    candidates = [item for item in items if feeds.within_window(item, hours, allow_missing=True)][:limit]
    sem = asyncio.Semaphore(4)

    async def inspect(item: dict) -> None:
        link = (item.get("link") or "").strip()
        if not link:
            return
        async with sem:
            info = await feeds.enrich_article(link)
        article_date = feeds.normalize_publication_date(info.get("published"))
        if article_date:
            item["published"] = article_date

    await asyncio.gather(*(inspect(item) for item in candidates))
    return [item for item in candidates if feeds.within_window(item, hours)]


@app.post("/api/feeds/test")
async def test_feed(payload: FeedPayload, _: None = auth) -> dict:
    url = (payload.url or "").strip()
    if not url.startswith(("http://", "https://")):
        fail("url_invalid")
    try:
        items = await feeds.fetch_source({"url": url, "title": "test"})
    except feeds.FeedError as exc:
        return {"ok": False, "error": str(exc)}
    window = await _validated_recent_items(items, 24, 12)
    return {
        "ok": True,
        "total": len(items),
        "in_window": len(window),
        "samples": [
            {
                "title": it["title"],
                "link": it["link"],
                "summary": (it.get("summary") or "")[:240],
                "published": it["published"],
                "image": it.get("image", ""),
            }
            for it in window[:6]
        ],
    }


@app.post("/api/feeds/{feed_id}/check")
async def check_feed(feed_id: int, _: None = auth) -> dict:
    feed = db.query_one("SELECT * FROM feeds WHERE id = ?", (feed_id,))
    if not feed:
        fail("feed_not_found", 404)
    try:
        items = await feeds.fetch_source(feed)
    except feeds.FeedError as exc:
        checked_at = db.now_iso()
        db.execute(
            "UPDATE feeds SET last_checked = ?, last_status = ? WHERE id = ?",
            (checked_at, f"error: {exc}"[:200], feed_id),
        )
        updated = db.query_one("SELECT * FROM feeds WHERE id = ?", (feed_id,))
        return {"ok": False, "error": str(exc), "feed": feed_public(updated) if updated else None}
    window = await _validated_recent_items(items, 24, 12)
    checked_at = db.now_iso()
    db.execute(
        "UPDATE feeds SET last_checked = ?, last_status = ?, last_count = ? WHERE id = ?",
        (checked_at, "ok", len(window), feed_id),
    )
    updated = db.query_one("SELECT * FROM feeds WHERE id = ?", (feed_id,))
    return {
        "ok": True,
        "total": len(items),
        "in_window": len(window),
        "feed": feed_public(updated) if updated else None,
        "samples": [{"title": it["title"], "published": it["published"]} for it in window[:5]],
    }


# ── topics ──────────────────────────────────────────────────────────────────


@app.get("/api/topics")
async def list_topics(_: None = auth) -> dict:
    return {"topics": [topic_public(r) for r in db.query("SELECT * FROM topics ORDER BY id")]}


@app.post("/api/topics")
async def create_topic(payload: TopicPayload, _: None = auth) -> dict:
    if not (payload.name or "").strip():
        fail("name_required")
    topic_id = db.execute(
        "INSERT INTO topics(name, name_en, emoji, keywords, enabled, created_at) VALUES(?,?,?,?,?,?)",
        (
            payload.name.strip(),
            (payload.name_en or payload.name).strip(),
            (payload.emoji or "").strip()[:4],
            (payload.keywords or "").strip(),
            as_int(payload.enabled, 1),
            db.now_iso(),
        ),
    )
    return {"ok": True, "id": topic_id}


@app.patch("/api/topics/{topic_id}")
async def update_topic(topic_id: int, payload: TopicPayload, _: None = auth) -> dict:
    data = payload.model_dump(exclude_unset=True)
    fields: dict[str, Any] = {}
    for key in ("name", "name_en", "emoji", "keywords"):
        if key in data and data[key] is not None:
            fields[key] = str(data[key]).strip()
    if "enabled" in data:
        fields["enabled"] = as_int(data["enabled"], 1)
    if fields:
        assignments = ", ".join(f"{k} = ?" for k in fields)
        db.execute(f"UPDATE topics SET {assignments} WHERE id = ?", (*fields.values(), topic_id))
    return {"ok": True}


@app.delete("/api/topics/{topic_id}")
async def delete_topic(topic_id: int, _: None = auth) -> dict:
    db.execute("DELETE FROM topics WHERE id = ?", (topic_id,))
    return {"ok": True}


@app.post("/api/topics/test")
async def test_topics(payload: TopicTestPayload, _: None = auth) -> dict:
    rows = db.query("SELECT * FROM topics ORDER BY id")
    scored = []
    for row in rows:
        score = topics_mod.score_topic(row, payload.title, payload.summary)
        if score:
            scored.append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "name_en": row.get("name_en") or row["name"],
                    "emoji": row.get("emoji", ""),
                    "score": score,
                }
            )
    scored.sort(key=lambda r: r["score"], reverse=True)
    best, _, _ = topics_mod.classify(rows, payload.title, payload.summary)
    return {"ok": True, "matches": scored, "best_id": best["id"] if best else 0}


# ── destinations ────────────────────────────────────────────────────────────


@app.get("/api/destinations")
async def list_destinations(_: None = auth) -> dict:
    rows = db.query("SELECT * FROM destinations ORDER BY id DESC")
    return {"destinations": [destination_public(r) for r in rows]}


@app.post("/api/destinations")
async def create_destination(payload: DestinationPayload, _: None = auth) -> dict:
    if not (payload.chat_id or "").strip():
        fail("chat_id_required")
    platform = (payload.platform or "telegram").lower()
    if platform not in publish.PLATFORMS:
        fail("platform_unsupported")
    destination_id = db.execute(
        """INSERT INTO destinations
           (name, platform, chat_id, bot_token, topic_filter, footer, parse_mode, enabled, created_at)
           VALUES(?,?,?,?,?,?,?,?,?)""",
        (
            (payload.name or "").strip() or platform,
            platform,
            payload.chat_id.strip(),
            (payload.bot_token or "").strip(),
            (payload.topic_filter or "").strip(),
            (payload.footer or "").strip(),
            (payload.parse_mode or "HTML").upper(),
            as_int(payload.enabled, 1),
            db.now_iso(),
        ),
    )
    return {"ok": True, "id": destination_id}


@app.patch("/api/destinations/{destination_id}")
async def update_destination(destination_id: int, payload: DestinationPayload, _: None = auth) -> dict:
    current = db.query_one("SELECT * FROM destinations WHERE id = ?", (destination_id,))
    if not current:
        fail("destination_not_found", 404)
    data = payload.model_dump(exclude_unset=True)
    fields: dict[str, Any] = {}
    for key in ("name", "chat_id", "topic_filter", "footer"):
        if key in data and data[key] is not None:
            fields[key] = str(data[key]).strip()
    if data.get("platform"):
        platform = str(data["platform"]).lower()
        if platform not in publish.PLATFORMS:
            fail("platform_unsupported")
        fields["platform"] = platform
    if data.get("parse_mode"):
        fields["parse_mode"] = str(data["parse_mode"]).upper()
    if "bot_token" in data:
        token = (data["bot_token"] or "").strip()
        if token and "•" not in token:
            fields["bot_token"] = token
    if "enabled" in data:
        fields["enabled"] = as_int(data["enabled"], 1)
    if fields:
        assignments = ", ".join(f"{k} = ?" for k in fields)
        db.execute(f"UPDATE destinations SET {assignments} WHERE id = ?", (*fields.values(), destination_id))
    return {"ok": True}


@app.delete("/api/destinations/{destination_id}")
async def delete_destination(destination_id: int, _: None = auth) -> dict:
    db.execute("DELETE FROM destinations WHERE id = ?", (destination_id,))
    return {"ok": True}


@app.post("/api/destinations/{destination_id}/verify")
async def verify_destination(destination_id: int, _: None = auth) -> dict:
    row = db.query_one("SELECT * FROM destinations WHERE id = ?", (destination_id,))
    if not row:
        fail("destination_not_found", 404)
    ok, detail, info = await publish.verify(row)
    db.execute(
        "UPDATE destinations SET last_test_at = ?, last_test_ok = ?, last_test_msg = ? WHERE id = ?",
        (db.now_iso(), 1 if ok else 0, (detail if ok else f"verify:{detail}")[:300], destination_id),
    )
    updated = db.query_one("SELECT * FROM destinations WHERE id = ?", (destination_id,))
    return {"ok": ok, "detail": detail, "info": info, "destination": destination_public(updated) if updated else None}


@app.post("/api/destinations/{destination_id}/test")
async def test_destination(destination_id: int, _: None = auth) -> dict:
    row = db.query_one("SELECT * FROM destinations WHERE id = ?", (destination_id,))
    if not row:
        fail("destination_not_found", 404)
    ok, detail = await publish.test_destination(row)
    db.execute(
        "UPDATE destinations SET last_test_at = ?, last_test_ok = ?, last_test_msg = ? WHERE id = ?",
        (db.now_iso(), 1 if ok else 0, detail[:300], destination_id),
    )
    updated = db.query_one("SELECT * FROM destinations WHERE id = ?", (destination_id,))
    return {"ok": ok, "detail": detail, "destination": destination_public(updated) if updated else None}


# ── jobs ────────────────────────────────────────────────────────────────────


@app.get("/api/jobs")
async def list_jobs(_: None = auth) -> dict:
    return {"jobs": [job_public(r) for r in db.query("SELECT * FROM jobs ORDER BY id DESC")]}


@app.post("/api/jobs")
async def create_job(payload: JobPayload, _: None = auth) -> dict:
    if not (payload.name or "").strip():
        fail("name_required")
    fmode = (payload.filter_mode or "smart").strip().lower()
    if fmode not in {"all", "smart", "strict"}:
        fmode = "smart"
    job_id = db.execute(
        """INSERT INTO jobs
           (name, enabled, schedule_times, interval_minutes, window_hours, max_items, translate,
            include_summary, full_text, send_image, show_topic, only_unseen, filter_mode,
            exclude_keywords, feed_ids, topic_ids, destination_ids, created_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            payload.name.strip(),
            as_int(payload.enabled, 1),
            clean_schedule(payload.schedule_times),
            max(0, int(payload.interval_minutes or 0)),
            max(1, int(payload.window_hours or 24)),
            max(0, int(payload.max_items if payload.max_items is not None else 8)),
            as_int(payload.translate, 1),
            as_int(payload.include_summary, 1),
            as_int(payload.full_text, 1),
            as_int(payload.send_image, 1),
            as_int(payload.show_topic, 1),
            as_int(payload.only_unseen, 1),
            fmode,
            (payload.exclude_keywords or "").strip(),
            db.dump(payload.feed_ids or []),
            db.dump(payload.topic_ids or []),
            db.dump(payload.destination_ids or []),
            db.now_iso(),
        ),
    )
    return {"ok": True, "id": job_id}


@app.patch("/api/jobs/{job_id}")
async def update_job(job_id: int, payload: JobPayload, _: None = auth) -> dict:
    current = db.query_one("SELECT * FROM jobs WHERE id = ?", (job_id,))
    if not current:
        fail("job_not_found", 404)
    data = payload.model_dump(exclude_unset=True)
    fields: dict[str, Any] = {}
    if data.get("name") is not None:
        fields["name"] = str(data["name"]).strip()
    if "enabled" in data:
        fields["enabled"] = as_int(data["enabled"], 1)
    if "schedule_times" in data:
        fields["schedule_times"] = clean_schedule(data["schedule_times"])
    if data.get("interval_minutes") is not None:
        fields["interval_minutes"] = max(0, int(data["interval_minutes"]))
    if data.get("window_hours") is not None:
        fields["window_hours"] = max(1, int(data["window_hours"]))
    if data.get("max_items") is not None:
        fields["max_items"] = max(0, int(data["max_items"]))
    if data.get("filter_mode") is not None:
        fm = str(data["filter_mode"]).strip().lower()
        fields["filter_mode"] = fm if fm in {"all", "smart", "strict"} else "smart"
    if data.get("exclude_keywords") is not None:
        fields["exclude_keywords"] = str(data["exclude_keywords"]).strip()
    for flag in ("translate", "include_summary", "full_text", "only_unseen", "send_image", "show_topic"):
        if flag in data:
            fields[flag] = as_int(data[flag], 1)
    for key in ("feed_ids", "topic_ids", "destination_ids"):
        if key in data and data[key] is not None:
            fields[key] = db.dump([int(x) for x in data[key]])
    if fields:
        assignments = ", ".join(f"{k} = ?" for k in fields)
        db.execute(f"UPDATE jobs SET {assignments} WHERE id = ?", (*fields.values(), job_id))
    updated = db.query_one("SELECT * FROM jobs WHERE id = ?", (job_id,))
    return {"ok": True, "job": job_public(updated) if updated else None}


@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: int, _: None = auth) -> dict:
    db.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    return {"ok": True}


@app.post("/api/jobs/{job_id}/run")
async def run_job(job_id: int, payload: RunPayload, _: None = auth) -> dict:
    job = db.query_one("SELECT * FROM jobs WHERE id = ?", (job_id,))
    if not job:
        fail("job_not_found", 404)
    return await pipeline.run_job(
        job, dry_run=payload.dry_run, force=True, max_items_override=payload.max_items
    )


@app.get("/api/jobs/{job_id}/logs")
async def job_logs(job_id: int, limit: int = 60, _: None = auth) -> dict:
    rows = db.query(
        "SELECT * FROM logs WHERE job_id = ? ORDER BY id DESC LIMIT ?", (job_id, min(limit, 300))
    )
    return {"logs": rows}


# ── smart link & media analyzer ─────────────────────────────────────────────


@app.get("/api/analyzer")
async def list_analyses(limit: int = 40, _: None = auth) -> dict:
    return {"analyses": analyzer.list_analyses(limit=limit)}


@app.post("/api/analyzer/llm/test")
async def test_analyzer_llm(_: None = auth) -> dict:
    return await analyzer.test_llm_connection()


@app.post("/api/analyzer/models")
async def analyzer_models(payload: AnalyzerModelsPayload, _: None = auth) -> dict:
    """Discover models using the entered key without saving or returning it."""
    provider = (payload.provider or "openai_compatible").strip().lower()
    if provider == "deepseek":
        base_url = analyzer.DEEPSEEK_API_BASE_URL
        saved_key = db.get_setting("deepseek_api_key")
    elif provider == "openai_compatible":
        base_url = (payload.base_url or db.get_setting("analysis_api_base_url") or "").strip().rstrip("/")
        saved_key = db.get_setting("openai_api_key")
    else:
        return {"ok": False, "error": "analysis_api_provider_invalid"}

    parsed = urlparse(base_url)
    if (parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password
            or parsed.query or parsed.fragment):
        return {"ok": False, "error": "analysis_api_url_invalid"}

    api_key = (payload.api_key or "").strip() or (db.get_setting("analysis_api_key") or "").strip() or (saved_key or "").strip()
    if not api_key:
        return {"ok": False, "error": "analysis_api_missing_key"}
    return await analyzer.fetch_api_models(base_url, api_key)


@app.post("/api/analyzer")
async def create_analysis(payload: AnalyzerCreatePayload, _: None = auth) -> dict:
    url = (payload.url or "").strip()
    if not url.startswith(("http://", "https://")):
        fail("url_invalid")
    plat = analyzer.detect_platform(url)
    aid = db.execute(
        """INSERT INTO analyses
           (url, platform, status, progress_msg, include_link, send_image, created_at)
           VALUES(?,?,?,?,?,?,?)""",
        (
            url,
            plat,
            "processing",
            "در صف تحلیل و استخراج محتوا…",
            as_int(payload.include_link, 0),
            as_int(payload.send_image, 1),
            db.now_iso(),
        ),
    )
    if payload.wait:
        result = await analyzer.run_analysis_task(aid, url, custom_text=payload.custom_text)
        return {"ok": True, "id": aid, "analysis": result}

    task = asyncio.create_task(analyzer.run_analysis_task(aid, url, custom_text=payload.custom_text))
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)
    return {"ok": True, "id": aid, "analysis": analyzer.get_analysis_public(aid)}


@app.get("/api/analyzer/{aid}")
async def get_analysis(aid: int, _: None = auth) -> dict:
    row = analyzer.get_analysis_public(aid)
    if not row:
        fail("item_not_found", 404)
    return {"ok": True, "analysis": row}


@app.patch("/api/analyzer/{aid}")
async def patch_analysis(aid: int, payload: AnalyzerPatchPayload, _: None = auth) -> dict:
    current = analyzer.get_analysis_public(aid)
    if not current:
        fail("item_not_found", 404)
    data = payload.model_dump(exclude_unset=True)
    fields: dict[str, Any] = {}
    if "title" in data and data["title"] is not None:
        fields["title"] = str(data["title"]).strip()
    if "channel_draft" in data and data["channel_draft"] is not None:
        fields["channel_draft"] = str(data["channel_draft"]).strip()
    if "include_link" in data:
        fields["include_link"] = as_int(data["include_link"], 0)
    if "send_image" in data:
        fields["send_image"] = as_int(data["send_image"], 1)
    if fields:
        analyzer._update_analysis(aid, **fields)
    return {"ok": True, "analysis": analyzer.get_analysis_public(aid)}


@app.post("/api/analyzer/{aid}/publish")
async def publish_analyzed(aid: int, payload: AnalyzerPublishPayload, _: None = auth) -> dict:
    return await analyzer.publish_analysis(
        aid,
        destination_ids=payload.destination_ids,
        channel_draft=payload.channel_draft,
        include_link=bool(as_int(payload.include_link, 0)) if payload.include_link is not None else None,
        send_image=bool(as_int(payload.send_image, 1)) if payload.send_image is not None else None,
    )


@app.delete("/api/analyzer/{aid}")
async def delete_analysis(aid: int, _: None = auth) -> dict:
    db.execute("DELETE FROM analyses WHERE id = ?", (aid,))
    return {"ok": True}


# ── items ───────────────────────────────────────────────────────────────────


@app.get("/api/items")
async def list_items(status: str = "", q: str = "", limit: int = 60, _: None = auth) -> dict:
    sql = "SELECT * FROM items WHERE 1=1"
    params: list[Any] = []
    if status and status != "all":
        sql += " AND status = ?"
        params.append(status)
    if q:
        sql += " AND (title LIKE ? OR title_fa LIKE ? OR summary LIKE ? OR summary_fa LIKE ?)"
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%", f"%{q}%"])
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(min(limit, 200))
    rows = db.query(sql, params)
    for row in rows:
        row["destinations"] = db.load_list(row.get("destinations"))
    counts = {
        r["status"]: r["c"]
        for r in db.query("SELECT status, COUNT(*) AS c FROM items GROUP BY status")
    }
    return {"items": rows, "total": sum(counts.values()), "counts": counts}


@app.post("/api/items/{item_id}/resend")
async def resend(item_id: int, payload: ResendPayload, _: None = auth) -> dict:
    return await pipeline.resend_item(item_id, payload.destination_ids)


@app.post("/api/items/{item_id}/preview")
async def preview(item_id: int, payload: PreviewPayload, _: None = auth) -> dict:
    return await pipeline.preview_item(item_id, payload.destination_id)


@app.delete("/api/items/{item_id}")
async def delete_item(item_id: int, _: None = auth) -> dict:
    db.execute("DELETE FROM items WHERE id = ?", (item_id,))
    return {"ok": True}


@app.post("/api/items/clear")
async def clear_items(_: None = auth) -> dict:
    db.execute("DELETE FROM items")
    return {"ok": True}


# ── logs / dashboard ────────────────────────────────────────────────────────


@app.get("/api/logs")
async def list_logs(limit: int = 80, _: None = auth) -> dict:
    return {"logs": db.query("SELECT * FROM logs ORDER BY id DESC LIMIT ?", (min(limit, 300),))}


@app.get("/api/dashboard")
async def dashboard(_: None = auth) -> dict:
    def count(sql: str) -> int:
        return int(db.query_one(sql)["c"])

    counts = {
        "feeds": count("SELECT COUNT(*) AS c FROM feeds WHERE enabled = 1"),
        "feeds_total": count("SELECT COUNT(*) AS c FROM feeds"),
        "topics": count("SELECT COUNT(*) AS c FROM topics WHERE enabled = 1"),
        "destinations": count("SELECT COUNT(*) AS c FROM destinations WHERE enabled = 1"),
        "jobs": count("SELECT COUNT(*) AS c FROM jobs WHERE enabled = 1"),
        "sent": count("SELECT COUNT(*) AS c FROM items WHERE status = 'sent'"),
        "failed": count("SELECT COUNT(*) AS c FROM items WHERE status = 'failed'"),
        "filtered": count("SELECT COUNT(*) AS c FROM items WHERE status = 'filtered'"),
        "translated": count("SELECT COUNT(*) AS c FROM items WHERE title_fa != '' OR summary_fa != ''"),
        "items": count("SELECT COUNT(*) AS c FROM items"),
        "with_image": count("SELECT COUNT(*) AS c FROM items WHERE image != ''"),
        "analyses": count("SELECT COUNT(*) AS c FROM analyses"),
    }
    jobs = [job_public(r) for r in db.query("SELECT * FROM jobs ORDER BY id")]
    upcoming = sorted([j for j in jobs if j["next_run"]], key=lambda j: j["next_run"])[:5]
    recent = db.query("SELECT * FROM items ORDER BY id DESC LIMIT 8")
    for row in recent:
        row["destinations"] = db.load_list(row.get("destinations"))
    activity = db.query(
        """SELECT substr(created_at, 1, 10) AS day,
                  SUM(CASE WHEN status = 'sent' THEN 1 ELSE 0 END) AS sent,
                  SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed,
                  SUM(CASE WHEN status = 'filtered' THEN 1 ELSE 0 END) AS filtered,
                  COUNT(*) AS total
           FROM items GROUP BY day ORDER BY day DESC LIMIT 14"""
    )
    return {
        "counts": counts,
        "jobs": jobs,
        "upcoming": [{"id": j["id"], "name": j["name"], "next_run": j["next_run"]} for j in upcoming],
        "recent_items": recent,
        "recent_analyses": analyzer.list_analyses(limit=3),
        "activity": activity,
        "logs": db.query("SELECT * FROM logs ORDER BY id DESC LIMIT 12"),
        "scheduler": scheduler.STATE,
        "settings": {
            "panel_title": db.get_setting("panel_title") or config.APP_NAME,
            "timezone": db.get_setting("timezone") or config.DEFAULT_TZ,
            "translate_provider": db.get_setting("translate_provider"),
            "global_footer": db.get_setting("global_footer"),
            "theme": db.get_setting("theme"),
            "language": db.get_setting("language"),
        },
    }


# ── admin ───────────────────────────────────────────────────────────────────


@app.get("/api/admin/overview")
async def admin_overview(_: None = auth) -> dict:
    size = 0
    try:
        size = config.DB_PATH.stat().st_size if config.DB_PATH.exists() else 0
    except OSError:
        size = 0
    sessions = db.query(
        "SELECT token, created_at, expires_at, user_agent FROM sessions ORDER BY created_at DESC"
    )
    return {
        "version": config.VERSION,
        "version_step": config.VERSION_STEP,
        "data_dir": str(config.DATA_DIR),
        "db_path": str(config.DB_PATH),
        "db_size": size,
        "uptime_seconds": int(time.time() - STARTED_AT),
        "python": __import__("sys").version.split(" ")[0],
        "scheduler": scheduler.STATE,
        "sessions": [{**s, "token": mask_secret(s["token"])} for s in sessions],
        "counts": {
            "feeds": db.query_one("SELECT COUNT(*) AS c FROM feeds")["c"],
            "topics": db.query_one("SELECT COUNT(*) AS c FROM topics")["c"],
            "destinations": db.query_one("SELECT COUNT(*) AS c FROM destinations")["c"],
            "jobs": db.query_one("SELECT COUNT(*) AS c FROM jobs")["c"],
            "items": db.query_one("SELECT COUNT(*) AS c FROM items")["c"],
            "analyses": db.query_one("SELECT COUNT(*) AS c FROM analyses")["c"],
            "logs": db.query_one("SELECT COUNT(*) AS c FROM logs")["c"],
        },
        "password_is_bootstrap": security.password_is_bootstrap(),
    }


@app.get("/api/admin/export")
async def admin_export(include_items: int = 0, _: None = auth) -> dict:
    payload: dict[str, Any] = {
        "app": "Rozaneh",
        "version": config.VERSION,
        "exported_at": db.now_iso(),
        "settings": {k: v for k, v in db.all_settings().items() if k not in SECRET_SETTINGS},
        "feeds": db.query("SELECT * FROM feeds ORDER BY sort_order, id"),
        "topics": db.query("SELECT * FROM topics ORDER BY id"),
        "destinations": [destination_export(row) for row in db.query("SELECT * FROM destinations ORDER BY id")],
        "jobs": db.query("SELECT * FROM jobs ORDER BY id"),
        "creators": creators_public(),
        "edu": edu_public(),
    }
    if include_items:
        payload["items"] = db.query("SELECT * FROM items ORDER BY id DESC LIMIT 1000")
        payload["analyses"] = db.query("SELECT * FROM analyses ORDER BY id DESC LIMIT 200")
    return payload


@app.post("/api/admin/import")
async def admin_import(payload: ImportPayload, _: None = auth) -> dict:
    if not payload.confirm:
        fail("confirm_required")
    data = payload.payload or {}
    imported = {"feeds": 0, "topics": 0, "destinations": 0, "jobs": 0}
    if data.get("feeds"):
        db.execute("DELETE FROM feeds")
        for row in data["feeds"]:
            db.execute(
                """INSERT INTO feeds(title, url, language, icon, color, show_url, show_source,
                                     custom_source_label, default_topic_id, full_article, sort_order,
                                     enabled, created_at, last_checked, last_status, last_count)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    row.get("title", ""),
                    row.get("url", ""),
                    row.get("language", "auto"),
                    row.get("icon", "📰"),
                    row.get("color", "teal"),
                    int(row.get("show_url", 1)),
                    int(row.get("show_source", 0)),
                    row.get("custom_source_label", ""),
                    int(row.get("default_topic_id", 0)),
                    int(row.get("full_article", 1)),
                    int(row.get("sort_order", 0)),
                    int(row.get("enabled", 1)),
                    row.get("created_at") or db.now_iso(),
                    "",
                    "",
                    0,
                ),
            )
            imported["feeds"] += 1
    if data.get("topics"):
        db.execute("DELETE FROM topics")
        for row in data["topics"]:
            db.execute(
                "INSERT INTO topics(name, name_en, emoji, keywords, enabled, created_at) VALUES(?,?,?,?,?,?)",
                (
                    row.get("name", ""),
                    row.get("name_en", ""),
                    row.get("emoji", ""),
                    row.get("keywords", ""),
                    int(row.get("enabled", 1)),
                    row.get("created_at") or db.now_iso(),
                ),
            )
            imported["topics"] += 1
    if data.get("destinations"):
        db.execute("DELETE FROM destinations")
        for row in data["destinations"]:
            db.execute(
                """INSERT INTO destinations(name, platform, chat_id, bot_token, topic_filter, footer,
                                            parse_mode, enabled, created_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    row.get("name", ""),
                    row.get("platform", "telegram"),
                    row.get("chat_id", ""),
                    "",  # Credentials are intentionally omitted from JSON backup/import.
                    row.get("topic_filter", ""),
                    row.get("footer", ""),
                    row.get("parse_mode", "HTML"),
                    int(row.get("enabled", 1)),
                    row.get("created_at") or db.now_iso(),
                ),
            )
            imported["destinations"] += 1
    if data.get("jobs"):
        db.execute("DELETE FROM jobs")
        for row in data["jobs"]:
            db.execute(
                """INSERT INTO jobs(name, enabled, schedule_times, interval_minutes, window_hours,
                                    max_items, translate, include_summary, full_text, send_image,
                                    show_topic, only_unseen, filter_mode, exclude_keywords,
                                    feed_ids, topic_ids, destination_ids, created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    row.get("name", ""),
                    int(row.get("enabled", 1)),
                    row.get("schedule_times", "[]"),
                    int(row.get("interval_minutes", 0)),
                    int(row.get("window_hours", 24)),
                    int(row.get("max_items", 8)),
                    int(row.get("translate", 1)),
                    int(row.get("include_summary", 1)),
                    int(row.get("full_text", 1)),
                    int(row.get("send_image", 1)),
                    int(row.get("show_topic", 1)),
                    int(row.get("only_unseen", 1)),
                    row.get("filter_mode", "smart"),
                    row.get("exclude_keywords", ""),
                    db.dump(row.get("feed_ids") or []),
                    db.dump(row.get("topic_ids") or []),
                    db.dump(row.get("destination_ids") or []),
                    row.get("created_at") or db.now_iso(),
                ),
            )
            imported["jobs"] += 1
    if isinstance(data.get("settings"), dict):
        for key, value in data["settings"].items():
            if key in SECRET_SETTINGS or key.startswith(("creator1_", "creator2_", "edu_")):
                continue
            db.set_setting(key, str(value))
    db.log(None, "settings imported", level="admin", code="import_done")
    return {"ok": True, "imported": imported}


@app.delete("/api/admin/sessions")
async def admin_clear_sessions(request: Request, _: None = auth) -> dict:
    current = security.current_token(request)
    db.execute("DELETE FROM sessions WHERE token != ?", (current or "",))
    return {"ok": True}


@app.post("/api/admin/archive/clear")
async def admin_clear_archive(_: None = auth) -> dict:
    items = db.query_one("SELECT COUNT(*) AS c FROM items")["c"]
    db.execute("DELETE FROM items")
    db.execute("DELETE FROM logs")
    return {"ok": True, "deleted": items}


async def _deliver_contact_to_telegram(kind: str, name: str, contact: str, message: str) -> dict[str, Any]:
    import httpx

    recipients = tuple(config.CONTACT_TELEGRAM_RECIPIENTS)
    token = _contact_bot_token()
    if not token:
        return {"status": "not_configured", "configured": False, "sent": 0, "total": len(recipients)}
    if not recipients:
        return {"status": "failed", "configured": True, "sent": 0, "total": 0}

    text = "\n".join(
        [
            "Rozaneh contact message",
            f"Category: {kind}",
            f"Name: {name or '—'}",
            f"Contact: {contact or '—'}",
            "",
            message,
        ]
    )[:3900]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    request_body = {"text": text, "disable_web_page_preview": True}

    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=4.0)) as client:
        async def send_one(chat_id: str) -> tuple[bool, str]:
            try:
                response = await client.post(url, json={**request_body, "chat_id": chat_id})
                if response.status_code >= 400:
                    return False, str(response.status_code)
                try:
                    body = response.json()
                except (ValueError, TypeError):
                    return False, "bad_response"
                return (isinstance(body, dict) and body.get("ok") is True), str(response.status_code)
            except httpx.TimeoutException:
                return False, "timeout"
            except httpx.RequestError:
                return False, "network"
            except Exception:  # noqa: BLE001 — do not log the token-bearing URL or exception
                return False, "delivery_error"

        results = await asyncio.gather(*(send_one(chat_id) for chat_id in recipients))

    sent = sum(1 for delivered, _status in results if delivered)
    total = len(recipients)
    status = "sent" if sent == total else "partial" if sent else "failed"
    for chat_id, (delivered, http_status) in zip(recipients, results):
        if not delivered:
            logger.warning("contact Telegram delivery failed for recipient %s (%s)", chat_id, http_status)
    db.log(None, f"contact Telegram delivery: {sent}/{total}", level="feedback", code=f"feedback_telegram_{status}")
    return {"status": status, "configured": True, "sent": sent, "total": total}


@app.post("/api/feedback")
async def feedback(payload: FeedbackPayload, request: Request) -> dict:
    message = (payload.message or "").strip()
    if len(message) < 3:
        fail("message_required")
    client_key = request.client.host if request.client else "unknown"
    if not _consume_rate_limit("feedback", client_key, limit=8, window_seconds=300):
        fail("feedback_rate_limited", 429)
    kind = (payload.kind or "message").strip()[:20] or "message"
    name = payload.name.strip()[:60]
    contact = payload.contact.strip()[:80]
    line = f"[{kind}] {name} | {contact} | {message}"
    db.log(None, line[:2000], level="feedback", code="feedback")

    telegram = await _deliver_contact_to_telegram(kind, name, contact, message)
    webhook_forwarded = False
    hook = (db.get_setting("feedback_webhook") or "").strip()
    if hook.startswith(("http://", "https://")):
        try:
            import httpx

            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    hook,
                    json={
                        "app": "Rozaneh",
                        "version": config.VERSION,
                        "kind": kind,
                        "name": name,
                        "contact": contact,
                        "message": message,
                    },
                )
                webhook_forwarded = resp.status_code < 400
        except Exception:  # noqa: BLE001 — webhook URLs can contain private credentials
            logger.warning("feedback webhook delivery failed")
    return {
        "ok": True,
        "saved": True,
        "forwarded": telegram["status"] == "sent",
        "telegram": telegram,
        "webhook_forwarded": webhook_forwarded,
    }


# ── misc ────────────────────────────────────────────────────────────────────


@app.post("/api/translate/test")
async def translate_test(payload: TopicTestPayload, _: None = auth) -> dict:
    text = payload.title or payload.summary or "Hello world, this is a translation test."
    return await translate.translate_with_report(text)


@app.get("/api/runtime")
async def runtime(_: None = auth) -> dict:
    return {
        "version": config.VERSION,
        "data_dir": str(config.DATA_DIR),
        "db_path": str(config.DB_PATH),
        "timezone": db.get_setting("timezone") or config.DEFAULT_TZ,
        "uptime_seconds": int(time.time() - STARTED_AT),
        "scheduler": scheduler.STATE,
        "platforms": config.PLATFORMS,
        "themes": config.THEMES,
        "languages": config.LANGUAGES,
    }


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True, "app": "Rozaneh", "version": config.VERSION}


@app.get("/")
async def index(request: Request):
    if not security.is_authenticated(request):
        return RedirectResponse("/login")
    return FileResponse(config.STATIC_DIR / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/login")
async def login_page(request: Request):
    if security.is_authenticated(request):
        return RedirectResponse("/")
    return FileResponse(config.STATIC_DIR / "login.html", headers={"Cache-Control": "no-store"})


@app.get("/favicon.svg")
async def favicon():
    return FileResponse(config.STATIC_DIR / "assets" / "logo.svg", media_type="image/svg+xml")
