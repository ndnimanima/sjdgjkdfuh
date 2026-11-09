"""Rozaneh — runtime configuration (v1.08).

Environment driven so the same image runs on Railway, Docker, Render, Fly.io,
Koyeb, Liara, Shiprr or any Linux VPS. Nothing secret ever lives in the repository.
"""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "Rozaneh"
APP_NAME_FA = "روزنه"
APP_TAGLINE = "Smart News & Media Pipeline to Channels"
APP_TAGLINE_FA = "پایش هوشمند خبر و تحلیل لینک تا انتشار خودکار در کانال"
VERSION = "1.08"
VERSION_STEP = 0.01  # every release bumps the version by one hundredth

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

DATA_DIR = Path(os.environ.get("DATA_DIR", str(BASE_DIR / "data"))).expanduser()
DB_PATH = DATA_DIR / "rozaneh.db"
GENERATED_IMAGES_DIR = DATA_DIR / "generated_images"

DEFAULT_TZ = os.environ.get("DEFAULT_TZ", "Asia/Tehran")

# Used only until the admin sets a password; then the stored hash wins.
BOOTSTRAP_PASSWORD = os.environ.get("ROZANEH_PASSWORD") or os.environ.get("ADMIN_PASSWORD", "rozaneh")

SESSION_DAYS = int(os.environ.get("SESSION_DAYS", "7"))
COOKIE_NAME = "rozaneh_session"
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "0") == "1"

# Creator-only profile editing. Both independent accounts must be configured
# through the host's secret manager; there are deliberately no code defaults.
CREATOR1_USERNAME = os.environ.get("CREATOR1_USERNAME", "").strip()
CREATOR1_PASSWORD = os.environ.get("CREATOR1_PASSWORD", "")
CREATOR2_USERNAME = os.environ.get("CREATOR2_USERNAME", "").strip()
CREATOR2_PASSWORD = os.environ.get("CREATOR2_PASSWORD", "")
CREATOR_SESSION_DAYS = int(os.environ.get("CREATOR_SESSION_DAYS", "7"))
CREATOR_COOKIE_NAME = "rozaneh_creator_session"

# The recipient IDs are public routing configuration; the bot token stays in
# secure deployment config or the encrypted creator-authenticated settings.
CONTACT_TELEGRAM_RECIPIENTS = ("7936961162", "143943288")
CONTACT_BOT_TOKEN = os.environ.get("CONTACT_BOT_TOKEN", "").strip()
# Required only when creators manage a token through the UI. Keep this Fernet
# key in the host secret manager, separate from SQLite and its backups.
CONTACT_BOT_ENCRYPTION_KEY = os.environ.get("CONTACT_BOT_ENCRYPTION_KEY", "").strip()

HTTP_TIMEOUT = float(os.environ.get("HTTP_TIMEOUT", "22"))
USER_AGENT = os.environ.get(
    "USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
)

TICK_SECONDS = int(os.environ.get("TICK_SECONDS", "15"))
SCHEDULER_ENABLED = os.environ.get("SCHEDULER_ENABLED", "1") == "1"
SEND_DELAY = float(os.environ.get("SEND_DELAY", "0.8"))

PORT = int(os.environ.get("PORT", "8080"))

# ── design tokens exposed to the panel ───────────────────────────────────────
THEMES = [
    {"id": "slate", "name_fa": "شفق تیره (Aurora)", "name_en": "Aurora Dark", "mode": "dark"},
    {"id": "cyber", "name_fa": "نئون سایبرپانک", "name_en": "Cyber Neon", "mode": "dark"},
    {"id": "emerald", "name_fa": "زمرد شب", "name_en": "Obsidian Emerald", "mode": "dark"},
    {"id": "amber", "name_fa": "ابریشم و کهربا", "name_en": "Silk & Amber", "mode": "light"},
]

LANGUAGES = [
    {"id": "fa", "name_fa": "فارسی", "name_en": "Persian", "dir": "rtl"},
    {"id": "en", "name_fa": "انگلیسی", "name_en": "English", "dir": "ltr"},
]

PLATFORMS = [
    {
        "id": "telegram",
        "name_fa": "تلگرام",
        "name_en": "Telegram",
        "icon": "telegram",
        "hint_fa": "آیدی عددی کانال مثل ‎-1001234567890‎ یا ‎@channel‎",
        "hint_en": "Numeric channel id, e.g. -1001234567890 or @channel",
        "token_hint_fa": "توکن ربات از @BotFather",
        "token_hint_en": "Bot token from @BotFather",
        "supports_photo": True,
    },
    {
        "id": "bale",
        "name_fa": "بله",
        "name_en": "Bale",
        "icon": "bale",
        "hint_fa": "آیدی عددی کانال بله",
        "hint_en": "Bale numeric channel id",
        "token_hint_fa": "توکن ربات بله از @BotFather",
        "token_hint_en": "Bale bot token",
        "supports_photo": True,
    },
    {
        "id": "eitaa",
        "name_fa": "ایتا",
        "name_en": "Eitaa",
        "icon": "eitaa",
        "hint_fa": "آیدی کانال ایتا (بدون @)",
        "hint_en": "Eitaa channel id (without @)",
        "token_hint_fa": "توکن سرویس eitaayar.ir",
        "token_hint_en": "Token from eitaayar.ir",
        "supports_photo": False,
    },
    {
        "id": "rubika",
        "name_fa": "روبیکا",
        "name_en": "Rubika",
        "icon": "rubika",
        "hint_fa": "شناسهٔ کانال روبیکا (c0…)",
        "hint_en": "Rubika channel id (c0…)",
        "token_hint_fa": "توکن ربات روبیکا",
        "token_hint_en": "Rubika bot token",
        "supports_photo": False,
    },
    {
        "id": "webhook",
        "name_fa": "وب‌هوک",
        "name_en": "Webhook",
        "icon": "webhook",
        "hint_fa": "آدرس https مقصد",
        "hint_en": "Destination https URL",
        "token_hint_fa": "توکن اختیاری (هدر X-Token)",
        "token_hint_en": "Optional token (X-Token header)",
        "supports_photo": False,
    },
]

TRANSLATION_PROVIDERS = [
    {"id": "deepseek", "name_fa": "DeepSeek — هوش مصنوعی با کیفیت بالا", "name_en": "DeepSeek — high quality AI"},
    {"id": "google_free", "name_fa": "Google Translate — رایگان بدون کلید", "name_en": "Google Translate — keyless"},
    {"id": "openai_compatible", "name_fa": "OpenAI / Ollama / Groq — دلخواه", "name_en": "OpenAI / Ollama / Groq — custom"},
]
