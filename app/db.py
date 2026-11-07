"""Rozaneh storage layer — SQLite in WAL mode, one connection, zero ORM."""

from __future__ import annotations

import json
import secrets
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Iterable

from . import config

_LOCK = threading.RLock()
_CONN: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    user_agent TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS topics (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    name_en    TEXT DEFAULT '',
    emoji      TEXT DEFAULT '',
    keywords   TEXT DEFAULT '',
    enabled    INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feeds (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    title               TEXT NOT NULL,
    url                 TEXT NOT NULL,
    language            TEXT DEFAULT 'auto',
    icon                TEXT DEFAULT '📰',
    color               TEXT DEFAULT 'teal',
    show_url            INTEGER NOT NULL DEFAULT 1,
    show_source         INTEGER NOT NULL DEFAULT 0,
    custom_source_label TEXT DEFAULT '',
    default_topic_id    INTEGER NOT NULL DEFAULT 0,
    full_article        INTEGER NOT NULL DEFAULT 1,
    sort_order          INTEGER NOT NULL DEFAULT 0,
    enabled             INTEGER NOT NULL DEFAULT 1,
    created_at          TEXT NOT NULL,
    last_checked        TEXT DEFAULT '',
    last_status         TEXT DEFAULT '',
    last_count          INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS destinations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    platform      TEXT NOT NULL DEFAULT 'telegram',
    chat_id       TEXT NOT NULL,
    bot_token     TEXT DEFAULT '',
    topic_filter  TEXT DEFAULT '',
    footer        TEXT DEFAULT '',
    parse_mode    TEXT NOT NULL DEFAULT 'HTML',
    enabled       INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL,
    last_test_at  TEXT DEFAULT '',
    last_test_ok  INTEGER DEFAULT NULL,
    last_test_msg TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS jobs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL,
    enabled          INTEGER NOT NULL DEFAULT 1,
    schedule_times   TEXT DEFAULT '[]',
    interval_minutes INTEGER NOT NULL DEFAULT 0,
    window_hours     INTEGER NOT NULL DEFAULT 24,
    max_items        INTEGER NOT NULL DEFAULT 8,
    translate        INTEGER NOT NULL DEFAULT 1,
    include_summary  INTEGER NOT NULL DEFAULT 1,
    full_text        INTEGER NOT NULL DEFAULT 1,
    send_image       INTEGER NOT NULL DEFAULT 1,
    show_topic       INTEGER NOT NULL DEFAULT 1,
    only_unseen      INTEGER NOT NULL DEFAULT 1,
    filter_mode      TEXT DEFAULT 'smart',
    exclude_keywords TEXT DEFAULT '',
    feed_ids         TEXT DEFAULT '[]',
    topic_ids        TEXT DEFAULT '[]',
    destination_ids  TEXT DEFAULT '[]',
    last_run         TEXT DEFAULT '',
    last_result      TEXT DEFAULT '',
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    hash          TEXT NOT NULL UNIQUE,
    job_id        INTEGER DEFAULT NULL,
    feed_id       INTEGER DEFAULT NULL,
    feed_title    TEXT DEFAULT '',
    show_source   INTEGER DEFAULT 0,
    title         TEXT NOT NULL,
    link          TEXT DEFAULT '',
    summary       TEXT DEFAULT '',
    image         TEXT DEFAULT '',
    published     TEXT DEFAULT '',
    lang          TEXT DEFAULT '',
    tags          TEXT DEFAULT '',
    topic         TEXT DEFAULT '',
    topic_key     TEXT DEFAULT '',
    title_fa      TEXT DEFAULT '',
    summary_fa    TEXT DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'new',
    filter_reason TEXT DEFAULT '',
    error         TEXT DEFAULT '',
    destinations  TEXT DEFAULT '[]',
    created_at    TEXT NOT NULL,
    posted_at     TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS analyses (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    url            TEXT NOT NULL,
    platform       TEXT DEFAULT 'web',
    title          TEXT DEFAULT '',
    author         TEXT DEFAULT '',
    duration_sec   INTEGER DEFAULT 0,
    image          TEXT DEFAULT '',
    source_lang    TEXT DEFAULT '',
    word_count     INTEGER DEFAULT 0,
    summary        TEXT DEFAULT '',
    key_points     TEXT DEFAULT '[]',
    deep_analysis  TEXT DEFAULT '',
    timeline       TEXT DEFAULT '[]',
    channel_draft  TEXT DEFAULT '',
    transcript_len INTEGER DEFAULT 0,
    status         TEXT NOT NULL DEFAULT 'processing',
    progress_msg   TEXT DEFAULT '',
    error          TEXT DEFAULT '',
    include_link   INTEGER NOT NULL DEFAULT 0,
    send_image     INTEGER NOT NULL DEFAULT 1,
    published_to   TEXT DEFAULT '[]',
    created_at     TEXT NOT NULL,
    posted_at      TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id     INTEGER DEFAULT NULL,
    level      TEXT NOT NULL DEFAULT 'info',
    message    TEXT NOT NULL,
    code       TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS translations (
    hash       TEXT PRIMARY KEY,
    provider   TEXT NOT NULL,
    target     TEXT NOT NULL,
    source_txt TEXT DEFAULT '',
    result_txt TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_items_created    ON items(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_items_status     ON items(status);
CREATE INDEX IF NOT EXISTS idx_analyses_created ON analyses(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_logs_created     ON logs(created_at DESC);
"""

DEFAULT_TOPICS: list[tuple[str, str, str, str]] = [
    (
        "سیاست و حکومت",
        "Politics & Government",
        "🏛",
        "سیاست,سیاسی,دولت,مجلس,وزیر,وزارت,رئیس‌جمهور,انتخابات,تحریم,دیپلماسی,قوه قضائیه,شورای امنیت,لایحه,مصوبه,سخنگو,پارلمان,رهبر,احزاب,دیکتاتور,حکومت,قانون,مهریه,دستور کار,politics,government,parliament,election,sanction,minister,president,diplomacy,cabinet,senate,congress",
    ),
    (
        "اقتصاد و بازار",
        "Economy & Markets",
        "📈",
        "اقتصاد,اقتصادی,تورم,دلار,یورو,ارز,بورس,سهام,طلا,سکه,نفت,گاز,بانک,بودجه,مالیات,صادرات,واردات,قیمت,بازار,تجارت,سرمایه‌گذاری,بیت‌کوین,رمزارز,کریپتو,وام,مسکن,خودرو,یارانه,حقوق,دستمزد,معاملات,شاخص کل,economy,inflation,currency,dollar,euro,oil,bank,budget,market,trade,tariff,gold,bitcoin,crypto,stock,price",
    ),
    (
        "بین‌الملل و جهان",
        "World & International",
        "🌍",
        "بین‌الملل,جهان,سازمان ملل,آمریکا,اروپا,روسیه,چین,ترکیه,عربستان,اسرائیل,غزه,لبنان,اوکراین,آتش‌بس,مذاکرات,هسته‌ای,ناتو,خاورمیانه,آسیا,آفریقا,سفارت,مرز,محاصره,کارگروه,پوتین,ترامپ,international,united nations,white house,europe,european,nuclear,diplomat,russia,china,turkey,israel,gaza,lebanon,ukraine,ceasefire,world news,nato",
    ),
    (
        "فناوری و هوش مصنوعی",
        "Tech & AI",
        "💻",
        "فناوری,تکنولوژی,هوش مصنوعی,گوشی,موبایل,تبلت,لپ‌تاپ,کامپیوتر,رایانه,سخت‌افزار,سخت افزار,قطعات,نرم‌افزار,نرم افزار,گجت,دیجیتال,هدفون,هندزفری,هدست,نویز کنسلینگ,تجهیزات شبکه,شبکه,مودم,روتر,لوازم جانبی,راهنمای خرید,پردازنده,تراشه,کارت گرافیک,اپل,آیفون,گوگل,اندروید,مایکروسافت,ویندوز,لینوکس,سامسونگ,شیائومی,دیپ‌سیک,چت‌جی‌پی‌تی,مدل زبانی,متا,اینترنت,فضای مجازی,استارتاپ,هک,امنیت سایبری,ربات,برنامه‌نویسی,کدنویسی,گیمینگ,بازی ویدیویی,کنسول,پلی‌استیشن,ایکس‌باکس,دیجیاتو,زومیت,technology,tech,artificial intelligence,ai,llm,chatgpt,openai,deepseek,apple,iphone,google,android,microsoft,meta,internet,cyber,startup,smartphone,hardware,software,headphone,network,gadget,gaming",
    ),
    (
        "ورزش",
        "Sports",
        "⚽",
        "ورزش,ورزشی,فوتبال,فوتسال,لیگ,تیم ملی,المپیک,جام جهانی,کشتی,والیبال,بسکتبال,تنیس,فینال,مربی,سرمربی,ورزشکار,دربی,پرسپولیس,استقلال,سپاهان,تراکتور,بازیکن,گل,مسابقه,رقابت,قهرمان,مدال,بانوان,tennis,golf,nba,fifa,sport,sports,football,futsal,soccer,olympic,wrestling,volleyball,basketball,coach,player,premier league,champions league,world cup",
    ),
    (
        "سلامت و پزشکی",
        "Health & Medicine",
        "🩺",
        "سلامت,پزشکی,پزشک,کرونا,واکسن,بیمار,بیمارستان,دارو,درمان,وزارت بهداشت,آنفلوآنزا,دیابت,سرطان,تغذیه,رژیم,روانشناسی,سلامت روان,ژنتیک,جراحی,قلب,مغز,ویروس,بهداشت,health,medicine,medical,vaccine,hospital,drug,disease,covid,flu,diabetes,cancer,who,mental health,nutrition",
    ),
    (
        "علم و دانش",
        "Science",
        "🔬",
        "علم,علمی,دانش,پژوهش,تحقیق,ناسا,فضا,نجوم,ستاره,کهکشان,سیاهچاله,ماهواره,کشف,دانشگاه,مطالعه,فیزیک,کوانتوم,نسبیت,اینشتین,نور,زمان,اتم,زیست‌شناسی,شیمی,باستان‌شناسی,فسیل,آزمایشگاه,دانشمند,کیهان,جهان هستی,science,research,nasa,space,astronomy,quantum,relativity,einstein,physics,biology,chemistry,satellite,study,discovery,university,scientist",
    ),
    (
        "هنر و سینما",
        "Arts & Cinema",
        "🎬",
        "سینما,فیلم,سریال,انیمیشن,مستند,جشنواره,بازیگر,موسیقی,آهنگ,خواننده,کارگردان,تئاتر,کنسرت,هنر,هنرمند,کتاب,رمان,شعر,فرهنگ,نمایشگاه,نقاشی,عکاسی,پادکست,اون‌ساید,cinema,movie,film,festival,actor,actress,music,series,director,theater,concert,artist,book,culture,animation",
    ),
    (
        "حوادث و جامعه",
        "Society & Incidents",
        "🚨",
        "حادثه,حوادث,تصادف,زلزله,سیل,آتش‌سوزی,انفجار,امداد,اورژانس,جرم,دستگیری,پلیس,اعتراض,اعتصاب,قتل,سرقت,مهاجرت,جامعه,اجتماعی,آموزش,مدرسه,جمعیت,زندگی,شهروند,accident,crash,earthquake,flood,fire,police,protest,strike,crime,murder,arrest,migrant,society,emergency",
    ),
    (
        "محیط زیست و اقلیم",
        "Climate & Environment",
        "🌱",
        "محیط زیست,آب و هوا,هواشناسی,بارش,باران,برف,آلودگی,خشکسالی,تغییر اقلیم,گرمایش,انرژی تجدیدپذیر,خورشیدی,حیات وحش,جنگل,دریاچه,تالاب,بازیافت,طبیعت,اکوسیستم,climate,environment,pollution,drought,emissions,wildlife,renewable,solar,weather,nature,forest",
    ),
]

CREATOR_DEFAULTS = {
    "creator1_name": "نیما دلیر | Nima Dalir",
    "creator1_role_fa": "هم‌بنیان‌گذار · توسعه‌دهنده هوش مصنوعی، نرم‌افزار و تولیدکننده محتوا",
    "creator1_role_en": "Co-Founder · Applied Offline AI, Software Dev & Content Creator",
    "creator1_bio_fa": "دانشجوی مهندسی کامپیوتر با تمرکز بر هوش مصنوعی کاربردی، اجرای مدل‌های زبانی آفلاین (Ollama، llama.cpp، LM Studio)، ساخت ایجنت‌های محلی و اتوماسیون با n8n، توسعه با Python و Termux، بازی‌سازی (Godot/Unity) و طراحی سه‌بعدی در Blender.",
    "creator1_bio_en": "Computer Engineering student building practical offline AI & local LLM tools (Ollama, llama.cpp, LM Studio), RAG & n8n automations, Python/Termux utilities, Godot/Unity games, and Blender 3D educational visuals.",
    "creator1_quote_fa": "«ابزارهای قدرتمند، آزاد و آفلاین — برای همه»",
    "creator1_quote_en": "“Powerful, Free, Offline Tools — For Everyone”",
    "creator1_skills": "Python,Offline LLMs,Ollama & llama.cpp,LangChain & RAG,n8n Automation,Termux & Linux,Godot & Unity,Blender 3D",
    "creator1_avatar": "https://avatars.githubusercontent.com/u/342028048?v=4",
    "creator1_telegram": "https://t.me/ndnima",
    "creator1_github": "https://github.com/ndnima",
    "creator1_email": "dalirnima137@gmail.com",
    "creator1_website": "",
    "creator2_name": "علیرضا بخارائی | Alireza Bokharaei",
    "creator2_role_fa": "هم‌بنیان‌گذار · مهندس زیرساخت، بک‌اند و امنیت سایبری",
    "creator2_role_en": "Co-Founder · Backend, Linux Infrastructure & Cybersecurity",
    "creator2_bio_fa": "دانشجوی علوم کامپیوتر در دانشگاه آکسفورد با تمرکز بر توسعه نرم‌افزار با Python (FastAPI، Django، ابزارهای CLI)، مدیریت سرورهای Linux و شبکه، مجازی‌سازی (Proxmox، Docker، Kubernetes)، امنیت سایبری و Bug Bounty و ساخت ایجنت‌های هوش مصنوعی آفلاین با n8n.",
    "creator2_bio_en": "Computer Science student at the University of Oxford focusing on Python development (FastAPI, Django, AsyncIO), Linux SysAdmin & networking, virtualization (Proxmox, Docker, K8s), penetration testing & bug bounty, and self-hosted AI automation.",
    "creator2_quote_fa": "«کد تمیز، معماری مقیاس‌پذیر، یادگیری بی‌پایان»",
    "creator2_quote_en": "“Clean Code, Scalable Architecture, Continuous Learning”",
    "creator2_skills": "Python & FastAPI,Linux & Networking,Cybersecurity & OSCP,Docker & Kubernetes,Proxmox & Terraform,n8n & AI Agents,Go & Bash",
    "creator2_avatar": "https://avatars.githubusercontent.com/u/347124742?v=4",
    "creator2_telegram": "https://t.me/alireza_bokharaei_051",
    "creator2_github": "https://github.com/alireza-bokharaei",
    "creator2_email": "alireza.bokharaei.051@gmail.com",
    "creator2_website": "",
    # educational channels (extracted from both GitHub READMEs)
    "edu_youtube_id": "@nextgen-ain8n",
    "edu_youtube_url": "https://youtube.com/@nextgen-ain8n",
    "edu_telegram_id": "@nextgen_ain8n",
    "edu_telegram_url": "https://t.me/nextgen_ain8n",
    "edu_topics_fa": "هوش مصنوعی آفلاین (Ollama، llama.cpp، RAG) · ایجنت‌های هوشمند (LangChain، LangGraph، CrewAI) · اتوماسیون حرفه‌ای با n8n · امنیت در AI · لینوکس و Termux · بازی‌سازی و طراحی سه‌بعدی با Blender",
    "edu_topics_en": "Offline AI & Local LLMs (Ollama, llama.cpp, RAG) · AI Agents (LangChain, LangGraph, CrewAI) · Self-hosted n8n Automation · AI Security · Linux & Termux · Game Dev & Blender 3D",
}

DEFAULT_SETTINGS = {
    "panel_title": config.APP_NAME,
    "timezone": config.DEFAULT_TZ,
    # appearance
    "theme": "slate",
    "language": "fa",
    # translation
    "translate_provider": "deepseek",
    "translate_fallback": "google_free",
    "translate_target": "fa",
    "translate_post_edit": "1",
    "translate_preserve": "1",
    "translate_glossary": "دیپ‌سیک · اوپک · برنت · هوش مصنوعی مولد · n8n · Ollama",
    "deepseek_base_url": "https://api.deepseek.com/v1",
    "deepseek_model": "deepseek-chat",
    "deepseek_api_key": "",
    "openai_base_url": "https://api.openai.com/v1",
    "openai_model": "gpt-4o-mini",
    "openai_api_key": "",
    # publishing
    "global_footer": "",
    "max_message_chars": "3800",
    "signature_enabled": "1",
    "feedback_webhook": "",
    # security
    "password_hash": "",
    "password_salt": "",
    **CREATOR_DEFAULTS,
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_conn() -> sqlite3.Connection:
    global _CONN
    with _LOCK:
        if _CONN is None:
            config.DATA_DIR.mkdir(parents=True, exist_ok=True)
            _CONN = sqlite3.connect(str(config.DB_PATH), check_same_thread=False, timeout=30)
            _CONN.row_factory = sqlite3.Row
            _CONN.execute("PRAGMA journal_mode=WAL")
            _CONN.execute("PRAGMA synchronous=NORMAL")
            _CONN.executescript(SCHEMA)
            _migrate()
            _seed()
        return _CONN


def _migrate() -> None:
    """Add columns introduced after earlier releases (idempotent)."""
    assert _CONN is not None
    wanted = {
        "feeds": {
            "icon": "TEXT DEFAULT '📰'",
            "color": "TEXT DEFAULT 'teal'",
            "show_url": "INTEGER DEFAULT 1",
            "show_source": "INTEGER DEFAULT 0",
            "custom_source_label": "TEXT DEFAULT ''",
            "default_topic_id": "INTEGER DEFAULT 0",
            "full_article": "INTEGER DEFAULT 1",
            "sort_order": "INTEGER DEFAULT 0",
        },
        "topics": {"name_en": "TEXT DEFAULT ''"},
        "jobs": {
            "send_image": "INTEGER DEFAULT 1",
            "full_text": "INTEGER DEFAULT 1",
            "show_topic": "INTEGER DEFAULT 1",
            "filter_mode": "TEXT DEFAULT 'smart'",
            "exclude_keywords": "TEXT DEFAULT ''",
        },
        "items": {
            "topic_key": "TEXT DEFAULT ''",
            "filter_reason": "TEXT DEFAULT ''",
            "tags": "TEXT DEFAULT ''",
            "show_source": "INTEGER DEFAULT 0",
        },
        "logs": {"code": "TEXT DEFAULT ''"},
    }
    for table, columns in wanted.items():
        existing = {row["name"] for row in _CONN.execute(f"PRAGMA table_info({table})")}
        for name, ddl in columns.items():
            if name not in existing:
                _CONN.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
    _CONN.commit()


def _seed() -> None:
    assert _CONN is not None
    for key, value in DEFAULT_SETTINGS.items():
        _CONN.execute("INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)", (key, value))

    # Populate creator & educational channel profiles if slots were blank from v1.03
    for slot in (1, 2):
        cur_name = _CONN.execute(
            "SELECT value FROM settings WHERE key = ?", (f"creator{slot}_name",)
        ).fetchone()
        if not cur_name or not (cur_name["value"] or "").strip():
            prefix = f"creator{slot}_"
            for k, v in CREATOR_DEFAULTS.items():
                if k.startswith(prefix):
                    _CONN.execute(
                        "INSERT INTO settings(key, value) VALUES(?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                        (k, v),
                    )
    for k, v in CREATOR_DEFAULTS.items():
        if k.startswith("edu_"):
            row = _CONN.execute("SELECT value FROM settings WHERE key = ?", (k,)).fetchone()
            if not row or not (row["value"] or "").strip():
                _CONN.execute(
                    "INSERT INTO settings(key, value) VALUES(?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (k, v),
                )

    count = _CONN.execute("SELECT COUNT(*) AS c FROM topics").fetchone()["c"]
    if not count:
        stamp = now_iso()
        _CONN.executemany(
            "INSERT INTO topics(name, name_en, emoji, keywords, enabled, created_at) VALUES(?,?,?,?,1,?)",
            [(n, en, e, k, stamp) for n, en, e, k in DEFAULT_TOPICS],
        )
    else:
        # Enrich default topics with expanded keywords without losing user additions
        by_name = {n: k for n, _en, _e, k in DEFAULT_TOPICS}
        for row in _CONN.execute("SELECT id, name, keywords FROM topics").fetchall():
            target_kws = by_name.get(row["name"])
            if not target_kws:
                continue
            existing_list = [x.strip() for x in (row["keywords"] or "").replace("،", ",").split(",") if x.strip()]
            existing_lower = {x.lower() for x in existing_list}
            added = False
            for kw in target_kws.split(","):
                kw_s = kw.strip()
                if kw_s and kw_s.lower() not in existing_lower:
                    existing_list.append(kw_s)
                    existing_lower.add(kw_s.lower())
                    added = True
            if added:
                _CONN.execute(
                    "UPDATE topics SET keywords = ? WHERE id = ?",
                    (",".join(existing_list), row["id"]),
                )
    _CONN.commit()


# ── helpers ─────────────────────────────────────────────────────────────────


def query(sql: str, params: Iterable[Any] = ()) -> list[dict]:
    with _LOCK:
        return [dict(r) for r in get_conn().execute(sql, tuple(params)).fetchall()]


def query_one(sql: str, params: Iterable[Any] = ()) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: Iterable[Any] = ()) -> int:
    with _LOCK:
        conn = get_conn()
        cur = conn.execute(sql, tuple(params))
        conn.commit()
        return int(cur.lastrowid or 0)


def executemany(sql: str, rows: list[tuple]) -> None:
    with _LOCK:
        conn = get_conn()
        conn.executemany(sql, rows)
        conn.commit()


def get_setting(key: str, default: str = "") -> str:
    row = query_one("SELECT value FROM settings WHERE key = ?", (key,))
    return row["value"] if row else default


def all_settings() -> dict[str, str]:
    return {r["key"]: r["value"] for r in query("SELECT key, value FROM settings")}


def set_setting(key: str, value: str) -> None:
    execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def load_list(raw: str | None) -> list:
    if not raw:
        return []
    try:
        value = json.loads(raw)
        return value if isinstance(value, list) else []
    except (TypeError, ValueError):
        return []


def dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def log(job_id: int | None, message: str, level: str = "info", code: str = "") -> None:
    execute(
        "INSERT INTO logs(job_id, level, message, code, created_at) VALUES(?,?,?,?,?)",
        (job_id, level, message[:2000], code[:60], now_iso()),
    )
    execute("DELETE FROM logs WHERE id NOT IN (SELECT id FROM logs ORDER BY id DESC LIMIT 3000)")


def translate_cache_get(key: str) -> str | None:
    row = query_one("SELECT result_txt FROM translations WHERE hash = ?", (key,))
    return row["result_txt"] if row else None


def translate_cache_put(key: str, provider: str, target: str, source: str, result: str) -> None:
    execute(
        "INSERT OR REPLACE INTO translations(hash, provider, target, source_txt, result_txt, created_at) "
        "VALUES(?,?,?,?,?,?)",
        (key, provider, target, source[:2000], result, now_iso()),
    )
