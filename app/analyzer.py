"""Smart Link & Long-Media Analyzer (YouTube 10m–3h+, Instagram, X, Telegram, Aparat, Web).

Extracts full transcripts/captions/articles, performs hierarchical chunked
summarisation & analysis (LLM-powered when DeepSeek/OpenAI is configured, or
keyless TF-IDF + Google Translate fallback out of the box), and prepares an
editable draft that the admin can approve & publish to any connected channel.
"""

from __future__ import annotations

import asyncio
import html
import json
import math
import re
from collections import Counter
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
from bs4 import BeautifulSoup

from . import config, db, feeds, publish, topics as topics_mod, translate

YT_ID_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?.*?v=|shorts/|live/|embed/|v/)|youtu\.be/)([A-Za-z0-9_-]{11})"
)
IG_CODE_RE = re.compile(r"instagram\.com/(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)")
TW_STATUS_RE = re.compile(r"(?:twitter\.com|x\.com)/([^/?#]+)/status/(\d+)")
TG_POST_RE = re.compile(r"t\.me/(?:s/)?([A-Za-z0-9_]{4,})/(\d+)")

STOPWORDS = {
    "the", "and", "for", "that", "this", "with", "you", "are", "was", "were", "have", "has",
    "had", "not", "but", "from", "they", "what", "when", "where", "which", "who", "will",
    "would", "could", "should", "about", "into", "there", "their", "them", "then", "than",
    "your", "just", "like", "very", "more", "some", "also", "been", "being", "going", "know",
    "think", "really", "actually", "because", "something", "everything", "people", "things",
    "این", "آن", "در", "به", "از", "که", "را", "با", "برای", "است", "بود", "شد", "شود",
    "دارد", "هم", "یک", "تا", "بر", "یا", "اما", "اگر", "هر", "همه", "ما", "شما", "آنها",
    "ایشان", "من", "تو", "وی", "پس", "پیش", "بی", "چون", "چرا", "چگونه", "می", "های", "ها",
}


def detect_platform(url: str) -> str:
    host = urlparse(url or "").netloc.lower()
    if "youtube.com" in host or "youtu.be" in host:
        return "youtube"
    if "instagram.com" in host:
        return "instagram"
    if "twitter.com" in host or "x.com" in host:
        return "twitter"
    if host in ("t.me", "telegram.me"):
        return "telegram"
    if "aparat.com" in host:
        return "aparat"
    if "tiktok.com" in host:
        return "tiktok"
    if "reddit.com" in host or "redd.it" in host:
        return "reddit"
    return "web"


def fmt_duration(seconds: int | float | None) -> str:
    sec = max(0, int(seconds or 0))
    if sec <= 0:
        return ""
    hrs, rem = divmod(sec, 3600)
    mins, s = divmod(rem, 60)
    if hrs > 0:
        return f"{hrs:02d}:{mins:02d}:{s:02d}"
    return f"{mins:02d}:{s:02d}"


def _update_analysis(aid: int, **fields: Any) -> None:
    if not fields:
        return
    for json_col in ("key_points", "timeline", "published_to"):
        if json_col in fields and not isinstance(fields[json_col], str):
            fields[json_col] = db.dump(fields[json_col])
    assignments = ", ".join(f"{k} = ?" for k in fields)
    db.execute(f"UPDATE analyses SET {assignments} WHERE id = ?", (*fields.values(), aid))


# ── Multi-Platform Content Extraction ───────────────────────────────────────


def _extract_yt_id(url: str) -> str:
    m = YT_ID_RE.search(url or "")
    if m:
        return m.group(1)
    parsed = urlparse(url or "")
    qs = parse_qs(parsed.query)
    if qs.get("v"):
        return qs["v"][0][:11]
    return ""


def _fetch_yt_transcript_sync(video_id: str) -> list[dict]:
    """Fetch timed transcript segments using youtube-transcript-api (v0.6.x & v1.x compatible)."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except Exception:
        return []

    pref_langs = ["fa", "en", "en-US", "en-GB", "ar", "tr", "de", "fr", "es", "ru"]
    raw_items: Any = None

    try:
        # v1.x instance API: YouTubeTranscriptApi().list(video_id) / .fetch(video_id, languages=...)
        if hasattr(YouTubeTranscriptApi, "list") and not hasattr(YouTubeTranscriptApi, "list_transcripts"):
            api = YouTubeTranscriptApi()
            try:
                raw_items = api.fetch(video_id, languages=pref_langs)
            except Exception:
                tlist = api.list(video_id)
                chosen = None
                for tr in tlist:
                    chosen = tr
                    if getattr(tr, "language_code", "") in ("fa", "en"):
                        break
                if chosen is not None:
                    raw_items = chosen.fetch()
        else:
            # v0.6.x classmethod API
            try:
                raw_items = YouTubeTranscriptApi.get_transcript(video_id, languages=pref_langs)
            except Exception:
                tlist = YouTubeTranscriptApi.list_transcripts(video_id)
                for tr in tlist:
                    raw_items = tr.fetch()
                    break
    except Exception:
        raw_items = None

    if not raw_items:
        return []

    segments: list[dict] = []
    for seg in raw_items:
        if isinstance(seg, dict):
            txt = str(seg.get("text") or "").strip()
            start = float(seg.get("start") or 0.0)
        else:
            txt = str(getattr(seg, "text", "") or "").strip()
            start = float(getattr(seg, "start", 0.0) or 0.0)
        txt = re.sub(r"\s+", " ", html.unescape(txt)).strip()
        if txt and txt not in ("[Music]", "[Applause]", "[موسیقی]"):
            segments.append({"start": start, "text": txt})
    return segments


def _ytdlp_extract_sync(url: str) -> dict[str, Any]:
    """Extract metadata & subtitle URLs via yt-dlp without downloading media."""
    try:
        import yt_dlp
    except Exception:
        return {}
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "socket_timeout": 12,
        "extract_flat": False,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info if isinstance(info, dict) else {}
    except Exception:
        return {}


async def _fetch_sub_from_ydl_info(info: dict) -> list[dict]:
    """If yt-dlp returned subtitle or automatic_captions URLs (json3/vtt), parse them."""
    subs_pool = {}
    for key in ("subtitles", "automatic_captions"):
        val = info.get(key)
        if isinstance(val, dict):
            for lang, tracks in val.items():
                if lang not in subs_pool and isinstance(tracks, list):
                    subs_pool[lang] = tracks
    if not subs_pool:
        return []

    chosen_tracks = None
    for lang in ("fa", "en", "en-orig", "en-US", "ar"):
        if lang in subs_pool:
            chosen_tracks = subs_pool[lang]
            break
    if not chosen_tracks:
        chosen_tracks = next(iter(subs_pool.values()))

    json3_url = ""
    vtt_url = ""
    for tr in chosen_tracks:
        if not isinstance(tr, dict):
            continue
        ext = str(tr.get("ext") or "").lower()
        u = str(tr.get("url") or "")
        if ext == "json3" and u:
            json3_url = u
            break
        if ext in ("vtt", "srv1", "ttml") and u and not vtt_url:
            vtt_url = u

    target_url = json3_url or vtt_url
    if not target_url:
        return []

    try:
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True, headers=feeds.BROWSER_HEADERS) as client:
            resp = await client.get(target_url)
            if resp.status_code >= 400:
                return []
            if json3_url:
                data = resp.json()
                segs: list[dict] = []
                for ev in data.get("events") or []:
                    start = float(ev.get("tStartMs") or 0) / 1000.0
                    piece = "".join(str(s.get("utf8") or "") for s in (ev.get("segs") or [])).strip()
                    piece = re.sub(r"\s+", " ", piece)
                    if piece and piece != "\n":
                        segs.append({"start": start, "text": piece})
                return segs
            # Simple VTT/XML fallback
            lines: list[dict] = []
            cur_sec = 0.0
            for line in resp.text.splitlines():
                line_s = line.strip()
                m_t = re.match(r"(?:(\d+):)?(\d{2}):(\d{2})\.\d+\s*-->", line_s)
                if m_t:
                    hh = int(m_t.group(1) or 0)
                    mm = int(m_t.group(2) or 0)
                    ss = int(m_t.group(3) or 0)
                    cur_sec = hh * 3600 + mm * 60 + ss
                    continue
                if not line_s or line_s.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")) or line_s.isdigit():
                    continue
                clean_l = re.sub(r"<[^>]+>", "", line_s).strip()
                if clean_l and (not lines or lines[-1]["text"] != clean_l):
                    lines.append({"start": cur_sec, "text": clean_l})
            return lines
    except Exception:
        return []


async def _extract_youtube(url: str) -> dict[str, Any]:
    vid = _extract_yt_id(url)
    if not vid:
        raise ValueError("شناسه ویدیوی یوتیوب در لینک پیدا نشد")

    canonical = f"https://www.youtube.com/watch?v={vid}"
    title = ""
    author = ""
    duration = 0
    thumbnail = f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
    description = ""
    chapters: list[dict] = []

    # Run transcript fetch + yt-dlp metadata concurrently
    segments_task = asyncio.to_thread(_fetch_yt_transcript_sync, vid)
    ydl_task = asyncio.to_thread(_ytdlp_extract_sync, canonical)

    # Also quick oEmbed check in parallel
    async def _oembed() -> dict:
        try:
            async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
                r = await client.get(
                    "https://www.youtube.com/oembed",
                    params={"url": canonical, "format": "json"},
                )
                return r.json() if r.status_code == 200 else {}
        except Exception:
            return {}

    segments, ydl_info, oembed = await asyncio.gather(segments_task, ydl_task, _oembed())

    if ydl_info:
        title = str(ydl_info.get("title") or "").strip()
        author = str(ydl_info.get("uploader") or ydl_info.get("channel") or "").strip()
        duration = int(ydl_info.get("duration") or 0)
        description = str(ydl_info.get("description") or "").strip()
        if ydl_info.get("thumbnail"):
            thumbnail = str(ydl_info["thumbnail"])
        for ch in ydl_info.get("chapters") or []:
            if isinstance(ch, dict) and ch.get("title"):
                chapters.append(
                    {"start": float(ch.get("start_time") or 0), "title": str(ch["title"]).strip()}
                )
        if not segments:
            segments = await _fetch_sub_from_ydl_info(ydl_info)

    if not title and oembed:
        title = str(oembed.get("title") or "").strip()
        author = author or str(oembed.get("author_name") or "").strip()
        if oembed.get("thumbnail_url"):
            thumbnail = str(oembed["thumbnail_url"])

    # HTML fallback if both ydl_info and oembed missed details
    if not title or (not segments and not description):
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, headers=feeds.BROWSER_HEADERS) as client:
                r = await client.get(canonical)
                if r.status_code < 400:
                    m_pr = re.search(r"ytInitialPlayerResponse\s*=\s*(\{.+?\});", r.text)
                    if m_pr:
                        pr = json.loads(m_pr.group(1))
                        vd = pr.get("videoDetails") or {}
                        title = title or str(vd.get("title") or "")
                        author = author or str(vd.get("author") or "")
                        duration = duration or int(vd.get("lengthSeconds") or 0)
                        description = description or str(vd.get("shortDescription") or "")
        except Exception:
            pass

    if not duration and segments:
        duration = int(segments[-1]["start"]) + 10

    transcript_text = " ".join(s["text"] for s in segments).strip()
    full_text = transcript_text
    if description:
        full_text = (transcript_text + "\n\n---\nتوضیحات ویدیو:\n" + description[:3000]).strip() if transcript_text else description

    return {
        "platform": "youtube",
        "title": title or f"YouTube Video ({vid})",
        "author": author,
        "duration_sec": duration,
        "image": thumbnail,
        "text": full_text,
        "segments": segments,
        "chapters": chapters,
    }


async def _extract_instagram(url: str) -> dict[str, Any]:
    title = ""
    author = ""
    duration = 0
    image = ""
    caption = ""
    segments: list[dict] = []

    ydl_info = await asyncio.to_thread(_ytdlp_extract_sync, url)
    if ydl_info:
        caption = str(ydl_info.get("description") or ydl_info.get("title") or "").strip()
        author = str(ydl_info.get("uploader") or ydl_info.get("channel") or ydl_info.get("uploader_id") or "").strip()
        duration = int(ydl_info.get("duration") or 0)
        image = str(ydl_info.get("thumbnail") or "").strip()
        segments = await _fetch_sub_from_ydl_info(ydl_info)

    m = IG_CODE_RE.search(url or "")
    if m and (not caption or not image):
        code = m.group(1)
        embed_url = f"https://www.instagram.com/p/{code}/embed/captioned/"
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, headers=feeds.BROWSER_HEADERS) as client:
                r = await client.get(embed_url)
                if r.status_code < 400:
                    soup = BeautifulSoup(r.text, "html.parser")
                    cap_el = soup.select_one(".Caption")
                    if cap_el and not caption:
                        # Remove username link prefix if needed
                        caption = cap_el.get_text(" ", strip=True)
                    user_el = soup.select_one(".UsernameText") or soup.select_one(".HeaderText")
                    if user_el and not author:
                        author = user_el.get_text(" ", strip=True)
                    img_el = soup.select_one("img.EmbeddedMediaImage")
                    if img_el and img_el.get("src") and not image:
                        image = str(img_el["src"])
        except Exception:
            pass

    if not caption:
        art = await feeds.enrich_article(url)
        caption = art.get("body") or ""
        title = art.get("title") or ""
        image = image or art.get("image") or ""
        author = author or art.get("author") or ""

    sub_txt = " ".join(s["text"] for s in segments).strip()
    combined = "\n\n".join(x for x in (sub_txt, caption) if x).strip()
    if not title:
        first_line = (caption.splitlines()[0] if caption else "").strip()
        title = first_line[:110] or (f"پست اینستاگرام از {author}" if author else "محتوای اینستاگرام")

    return {
        "platform": "instagram",
        "title": title,
        "author": author,
        "duration_sec": duration,
        "image": image,
        "text": combined,
        "segments": segments,
        "chapters": [],
    }


async def _extract_twitter(url: str) -> dict[str, Any]:
    m = TW_STATUS_RE.search(url or "")
    if m:
        user, status_id = m.group(1), m.group(2)
        api_url = f"https://api.fxtwitter.com/{user}/status/{status_id}"
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                r = await client.get(api_url)
                if r.status_code == 200:
                    tweet = (r.json() or {}).get("tweet") or {}
                    text = str(tweet.get("text") or "").strip()
                    # Check X Article if present
                    article = tweet.get("article") or {}
                    if isinstance(article, dict) and article.get("content"):
                        blocks = article["content"].get("blocks") or []
                        art_txt = "\n\n".join(str(b.get("text") or "") for b in blocks if b.get("text"))
                        if art_txt:
                            text = f"{article.get('title', '')}\n\n{art_txt}".strip()
                    author_obj = tweet.get("author") or {}
                    author = f"{author_obj.get('name', '')} (@{author_obj.get('screen_name', user)})".strip()
                    media = (tweet.get("media") or {}).get("all") or []
                    img = ""
                    dur = 0
                    for md in media:
                        if isinstance(md, dict):
                            img = img or str(md.get("thumbnail_url") or md.get("url") or "")
                            dur = dur or int(float(md.get("duration") or 0))
                    first_line = text.splitlines()[0][:110] if text else f"پست X از @{user}"
                    return {
                        "platform": "twitter",
                        "title": first_line,
                        "author": author,
                        "duration_sec": dur,
                        "image": img,
                        "text": text,
                        "segments": [],
                        "chapters": [],
                    }
        except Exception:
            pass
    return await _extract_web(url, platform_override="twitter")


async def _extract_telegram(url: str) -> dict[str, Any]:
    m = TG_POST_RE.search(url or "")
    if m:
        channel, msg_id = m.group(1), m.group(2)
        embed_url = f"https://t.me/{channel}/{msg_id}?embed=1&mode=tme"
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, headers=feeds.BROWSER_HEADERS) as client:
                r = await client.get(embed_url)
                if r.status_code < 400:
                    soup = BeautifulSoup(r.text, "html.parser")
                    txt_el = soup.select_one(".tgme_widget_message_text")
                    text = feeds.clean_text(str(txt_el), limit=6000) if txt_el else ""
                    owner_el = soup.select_one(".tgme_widget_message_owner_name")
                    author = owner_el.get_text(" ", strip=True) if owner_el else f"@{channel}"
                    photo_el = soup.select_one(".tgme_widget_message_photo_wrap")
                    img = ""
                    if photo_el and photo_el.get("style"):
                        m_bg = re.search(r"background-image:url\(['\"]?([^'\")]+)['\"]?\)", str(photo_el["style"]))
                        if m_bg:
                            img = m_bg.group(1)
                    title = (text.splitlines()[0][:110] if text else f"پست تلگرام @{channel}")
                    return {
                        "platform": "telegram",
                        "title": title,
                        "author": author,
                        "duration_sec": 0,
                        "image": img,
                        "text": text,
                        "segments": [],
                        "chapters": [],
                    }
        except Exception:
            pass
    return await _extract_web(url, platform_override="telegram")


async def _extract_web(url: str, platform_override: str = "") -> dict[str, Any]:
    plat = platform_override or detect_platform(url)
    title = ""
    author = ""
    duration = 0
    image = ""
    text = ""
    segments: list[dict] = []

    if plat in ("aparat", "tiktok"):
        ydl_info = await asyncio.to_thread(_ytdlp_extract_sync, url)
        if ydl_info:
            title = str(ydl_info.get("title") or "").strip()
            author = str(ydl_info.get("uploader") or ydl_info.get("channel") or "").strip()
            duration = int(ydl_info.get("duration") or 0)
            image = str(ydl_info.get("thumbnail") or "").strip()
            text = str(ydl_info.get("description") or "").strip()
            segments = await _fetch_sub_from_ydl_info(ydl_info)
            if segments:
                text = (" ".join(s["text"] for s in segments) + "\n\n" + text).strip()

    art = await feeds.enrich_article(url)
    title = title or art.get("title") or url.split("//", 1)[-1][:80]
    author = author or art.get("author") or urlparse(url).netloc
    image = image or art.get("image") or ""
    if len(art.get("body") or "") > len(text):
        text = art.get("body") or text

    return {
        "platform": plat,
        "title": title,
        "author": author,
        "duration_sec": duration,
        "image": image,
        "text": text,
        "segments": segments,
        "chapters": [],
    }


async def extract_any_url(url: str, custom_text: str = "") -> dict[str, Any]:
    plat = detect_platform(url)
    if plat == "youtube":
        data = await _extract_youtube(url)
    elif plat == "instagram":
        data = await _extract_instagram(url)
    elif plat == "twitter":
        data = await _extract_twitter(url)
    elif plat == "telegram":
        data = await _extract_telegram(url)
    else:
        data = await _extract_web(url)

    if custom_text and custom_text.strip():
        existing = (data.get("text") or "").strip()
        data["text"] = f"{custom_text.strip()}\n\n{existing}".strip() if existing else custom_text.strip()
    return data


# ── Hierarchical Summariser & Analyst (LLM + Keyless TF-IDF Engine) ─────────


def _active_llm() -> tuple[str, str, str] | None:
    """Return the dedicated analysis API, falling back to existing translation keys."""
    analysis_key = (db.get_setting("analysis_api_key") or "").strip()
    if analysis_key:
        return (
            db.get_setting("analysis_api_base_url") or "https://api.openai.com/v1",
            db.get_setting("analysis_api_model") or "gpt-4o-mini",
            analysis_key,
        )
    provider = db.get_setting("translate_provider") or "deepseek"
    ds_key = (db.get_setting("deepseek_api_key") or "").strip()
    oa_key = (db.get_setting("openai_api_key") or "").strip()
    if provider == "openai_compatible" and oa_key:
        return (
            db.get_setting("openai_base_url") or "https://api.openai.com/v1",
            db.get_setting("openai_model") or "gpt-4o-mini",
            oa_key,
        )
    if ds_key:
        return (
            db.get_setting("deepseek_base_url") or "https://api.deepseek.com/v1",
            db.get_setting("deepseek_model") or "deepseek-chat",
            ds_key,
        )
    if oa_key:
        return (
            db.get_setting("openai_base_url") or "https://api.openai.com/v1",
            db.get_setting("openai_model") or "gpt-4o-mini",
            oa_key,
        )
    return None


async def _llm_chat(base_url: str, model: str, api_key: str, system: str, user: str, timeout: float = 55.0) -> str:
    payload = {
        "model": model,
        "temperature": 0.25,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"llm_http_{resp.status_code}")
    data = resp.json()
    return (data["choices"][0]["message"]["content"] or "").strip()


async def test_llm_connection() -> dict[str, Any]:
    """Check the configured chat-completions endpoint without exposing its key."""
    cfg = _active_llm()
    if not cfg:
        return {"ok": False, "error": "analysis_api_missing"}
    base_url, model, api_key = cfg
    try:
        response = await _llm_chat(
            base_url,
            model,
            api_key,
            "Reply with the single word OK.",
            "Connection test. Reply with OK only.",
            timeout=20.0,
        )
        return {"ok": bool(response), "model": model, "response": response[:80]}
    except Exception as exc:  # noqa: BLE001 — return a short, key-safe diagnostic
        return {"ok": False, "model": model, "error": str(exc)[:180] or exc.__class__.__name__}


def _build_timed_chunks(data: dict, max_chunk_chars: int = 14000, max_chunks: int = 6) -> list[tuple[str, str]]:
    """Group transcript or long text into chronological (label, text) chunks — handles 3h+ videos."""
    segments = data.get("segments") or []
    if segments:
        total_dur = max(float(data.get("duration_sec") or 0), float(segments[-1]["start"]) + 1)
        raw_total = sum(len(s["text"]) for s in segments)
        n_buckets = min(max_chunks, max(1, math.ceil(raw_total / max_chunk_chars)))
        if total_dur >= 1200 and n_buckets < 4:  # >= 20 min gets at least 4 timeline chapters
            n_buckets = min(max_chunks, max(4, int(total_dur // 1200) + 1))

        bucket_dur = total_dur / n_buckets
        buckets: list[list[str]] = [[] for _ in range(n_buckets)]
        for s in segments:
            idx = min(n_buckets - 1, int(float(s["start"]) // max(bucket_dur, 1)))
            buckets[idx].append(s["text"])

        out: list[tuple[str, str]] = []
        for i, words in enumerate(buckets):
            if not words:
                continue
            start_lbl = fmt_duration(i * bucket_dur) or "00:00"
            end_lbl = fmt_duration(min(total_dur, (i + 1) * bucket_dur))
            joined = " ".join(words)
            # Sample evenly if a single bucket of a 4-hour stream is still huge
            if len(joined) > max_chunk_chars:
                half = max_chunk_chars // 2
                joined = joined[:half] + " … " + joined[-half:]
            out.append((f"{start_lbl} – {end_lbl}", joined))
        if out:
            return out

    text = (data.get("text") or "").strip()
    if not text:
        return []
    chunks: list[tuple[str, str]] = []
    step = max(max_chunk_chars, math.ceil(len(text) / max_chunks))
    for i in range(0, len(text), step):
        piece = text[i : i + max_chunk_chars]
        chunks.append((f"بخش {len(chunks) + 1}", piece))
        if len(chunks) >= max_chunks:
            break
    return chunks


def _extractive_top_sentences(text: str, count: int = 5) -> list[str]:
    """Keyless TF-IDF centrality sentence ranker for zero-key operation."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return []
    # Split by sentence punctuation or ~32-word windows for unpunctuated auto-captions
    raw_sents = [s.strip() for s in re.split(r"(?<=[.!?؟۔\n])\s+", text) if len(s.strip()) >= 25]
    if len(raw_sents) < 3:
        words = text.split()
        raw_sents = [" ".join(words[i : i + 30]) for i in range(0, len(words), 30) if len(words[i : i + 30]) >= 6]
    if len(raw_sents) <= count:
        return raw_sents

    tokens_per_sent: list[list[str]] = []
    freq: Counter[str] = Counter()
    for s in raw_sents:
        toks = [
            w.lower()
            for w in re.findall(r"[\w\u0600-\u06FF]{3,}", s)
            if w.lower() not in STOPWORDS and not w.isdigit()
        ]
        tokens_per_sent.append(toks)
        freq.update(set(toks))

    scored: list[tuple[float, int, str]] = []
    n_total = len(raw_sents)
    for idx, (s, toks) in enumerate(zip(raw_sents, tokens_per_sent)):
        if not toks:
            continue
        # Normalize by sqrt(length) so medium informative sentences win over run-on noise
        base = sum(freq[t] for t in toks) / (math.sqrt(len(toks)) + 2.0)
        pos_bonus = 1.18 if idx < max(2, n_total // 8) else (1.08 if idx > n_total * 0.85 else 1.0)
        scored.append((base * pos_bonus, idx, s[:340]))

    scored.sort(key=lambda x: x[0], reverse=True)
    picked = sorted(scored[:count], key=lambda x: x[1])
    return [p[2] for p in picked]


async def _analyze_with_llm(aid: int, data: dict, llm_cfg: tuple[str, str, str]) -> dict[str, Any]:
    base_url, model, api_key = llm_cfg
    chunks = _build_timed_chunks(data, max_chunk_chars=13000, max_chunks=6)

    chunk_notes: list[str] = []
    if len(chunks) > 1:
        for idx, (label, ctext) in enumerate(chunks, start=1):
            _update_analysis(aid, progress_msg=f"در حال تحلیل هوشمند بخش {idx} از {len(chunks)} ({label})…")
            note = await _llm_chat(
                base_url,
                model,
                api_key,
                "You are an expert Persian content analyst. Summarise this segment concisely in fluent Persian (4-6 bullet points), keeping exact facts, numbers and core arguments.",
                f"عنوان: {data.get('title')}\nبازه زمانی/بخش: {label}\n\nمتن:\n{ctext}",
            )
            chunk_notes.append(f"### بازه {label}\n{note}")
        combined_source = "\n\n".join(chunk_notes)
    else:
        combined_source = chunks[0][1] if chunks else (data.get("title") or "")

    _update_analysis(aid, progress_msg="در حال تدوین خلاصه جامع، نکات کلیدی و پیش‌نویس کانال…")
    dur_str = fmt_duration(data.get("duration_sec")) or "نامشخص"
    sys_prompt = (
        "You are a senior Persian media editor and analyst. "
        "Return ONLY valid JSON (no markdown fences) with these exact keys in fluent, journalistic Persian:\n"
        "{\n"
        '  "title_fa": "عنوان جذاب و روان فارسی",\n'
        '  "summary": "خلاصه جامع ۲ تا ۳ پاراگرافی از کل محتوا",\n'
        '  "key_points": ["نکته کلیدی ۱", "نکته کلیدی ۲", "نکته کلیدی ۳", "نکته کلیدی ۴", "نکته کلیدی ۵"],\n'
        '  "deep_analysis": "تحلیل عمیق دیدگاه‌ها، لحن، اهمیت موضوع و جمع‌بندی نهایی",\n'
        '  "timeline": [{"time": "00:00", "text": "موضوع این بخش"}],\n'
        '  "channel_draft": "متن حرفه‌ای و خوش‌فرمت برای انتشار در کانال تلگرام (شامل تیتر، خلاصه جذاب و بولت‌پوینت‌های مهم با ایموجی مناسب، بدون لینک خام)"\n'
        "}"
    )
    user_prompt = (
        f"پلتفرم: {data.get('platform')}\n"
        f"عنوان اصلی: {data.get('title')}\n"
        f"تولیدکننده/نویسنده: {data.get('author')}\n"
        f"مدت زمان: {dur_str}\n\n"
        f"محتوا:\n{combined_source[:20000]}"
    )
    raw_json = await _llm_chat(base_url, model, api_key, sys_prompt, user_prompt, timeout=65.0)
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_json.strip(), flags=re.M)
    m_obj = re.search(r"\{[\s\S]*\}", cleaned)
    parsed = json.loads(m_obj.group(0) if m_obj else cleaned)
    return {
        "title_fa": str(parsed.get("title_fa") or "").strip(),
        "summary": str(parsed.get("summary") or "").strip(),
        "key_points": [str(x).strip() for x in (parsed.get("key_points") or []) if str(x).strip()][:8],
        "deep_analysis": str(parsed.get("deep_analysis") or "").strip(),
        "timeline": [
            {"time": str(t.get("time") or ""), "text": str(t.get("text") or "")}
            for t in (parsed.get("timeline") or [])
            if isinstance(t, dict) and t.get("text")
        ][:10],
        "channel_draft": str(parsed.get("channel_draft") or "").strip(),
    }


async def _analyze_keyless(aid: int, data: dict) -> dict[str, Any]:
    """Zero-API-key analyzer: chronological extractive synthesis + auto Persian translation."""
    _update_analysis(aid, progress_msg="در حال استخراج نکات کلیدی و بخش‌بندی زمانی محتوا…")
    raw_title = (data.get("title") or "").strip()
    full_text = (data.get("text") or "").strip()
    chunks = _build_timed_chunks(data, max_chunk_chars=12000, max_chunks=6)

    timeline_raw: list[dict] = []
    # Prefer creator's explicit YouTube chapters if available, enriched with segment highlights
    chapters = data.get("chapters") or []
    if chapters:
        for ch in chapters[:8]:
            timeline_raw.append({"time": fmt_duration(ch.get("start")) or "00:00", "text": ch["title"]})

    per_chunk_highlights: list[str] = []
    for label, ctext in chunks:
        best_in_chunk = _extractive_top_sentences(ctext, count=2)
        if best_in_chunk:
            per_chunk_highlights.extend(best_in_chunk)
            if not chapters and len(chunks) > 1:
                timeline_raw.append({"time": label.split("–")[0].strip(), "text": best_in_chunk[0][:180]})

    overall_top = _extractive_top_sentences(full_text, count=6) if full_text else []
    key_points_src = list(dict.fromkeys((overall_top[:4] + per_chunk_highlights[:4])))[:6]

    summary_src = "\n\n".join(overall_top[:3]) if overall_top else raw_title

    _update_analysis(aid, progress_msg="در حال ترجمه روان و آماده‌سازی تحلیل فارسی…")
    title_fa, _ = await translate.maybe_translate(raw_title, True)
    summary_fa, _ = await translate.maybe_translate(summary_src, True)

    key_points_fa: list[str] = []
    if key_points_src:
        joined_kp = "\n###\n".join(key_points_src)
        tr_kp, _ = await translate.maybe_translate(joined_kp, True)
        key_points_fa = [p.strip(" -•\n") for p in tr_kp.split("###") if p.strip()][:6]

    timeline_fa: list[dict] = []
    if timeline_raw:
        joined_tl = "\n###\n".join(t["text"] for t in timeline_raw)
        tr_tl, _ = await translate.maybe_translate(joined_tl, True)
        parts_tl = [p.strip() for p in tr_tl.split("###")]
        for orig, tr_txt in zip(timeline_raw, parts_tl):
            timeline_fa.append({"time": orig["time"], "text": tr_txt or orig["text"]})

    # Topic & structural analysis
    topic_rows = db.query("SELECT * FROM topics WHERE enabled = 1")
    best_topic, _, matched_names = topics_mod.classify(
        topic_rows, f"{title_fa} {raw_title}", f"{summary_fa} {full_text[:2000]}"
    )
    word_count = len(full_text.split())
    dur_sec = int(data.get("duration_sec") or 0)
    dur_fa = fmt_duration(dur_sec)

    plat_fa = {
        "youtube": "ویدیوی یوتیوب",
        "instagram": "محتوای اینستاگرام",
        "twitter": "پست شبکه X (توییتر)",
        "telegram": "پست تلگرام",
        "aparat": "ویدیوی آپارات",
        "tiktok": "ویدیوی تیک‌تاک",
        "web": "مقاله و صفحه وب",
    }.get(data.get("platform") or "web", "محتوای وب")

    analysis_lines = [
        f"• نوع محتوا: {plat_fa}" + (f" از «{data.get('author')}»" if data.get("author") else ""),
        f"• حجم محتوای بررسی‌شده: حدود {word_count:,} کلمه" + (f" در مدت زمان {dur_fa}" if dur_fa else ""),
    ]
    if matched_names:
        analysis_lines.append(f"• حوزه‌های موضوعی تشخیص‌داده‌شده: {'، '.join(matched_names[:3])}")
    if dur_sec >= 1800:
        analysis_lines.append("• این محتوا یک ویدیو/برنامه طولانی است که تمام بخش‌های زمانی آن از ابتدا تا انتها پایش و چکیده شد.")
    elif not full_text:
        analysis_lines.append("• نکته: این لینک زیرنویس یا کپشن متنی عمومی نداشت؛ در صورت نیاز می‌توانید توضیحات تکمیلی را دستی اضافه کنید.")
    deep_analysis = "\n".join(analysis_lines)

    # Ready-to-publish channel post draft
    bullets = "\n".join(f"▫️ {kp}" for kp in key_points_fa[:4])
    topic_tag = ""
    if best_topic:
        topic_tag = f"\n\n{topics_mod.topic_label(best_topic)} {topics_mod.hashtag(best_topic.get('name', ''))}".strip()

    meta_header = []
    if data.get("author"):
        meta_header.append(f"👤 {data['author']}")
    if dur_fa:
        meta_header.append(f"⏱ {dur_fa}")
    meta_line = (" | ".join(meta_header) + "\n\n") if meta_header else ""

    draft_parts = [f"🎬 {title_fa or raw_title}".strip()]
    if meta_line.strip():
        draft_parts.append(meta_line.strip())
    if summary_fa and summary_fa != title_fa:
        draft_parts.append(summary_fa[:550])
    if bullets:
        draft_parts.append(f"📌 مهم‌ترین نکات:\n{bullets}")
    if topic_tag:
        draft_parts.append(topic_tag)

    return {
        "title_fa": title_fa or raw_title,
        "summary": summary_fa or raw_title,
        "key_points": key_points_fa,
        "deep_analysis": deep_analysis,
        "timeline": timeline_fa,
        "channel_draft": "\n\n".join(p for p in draft_parts if p),
    }


async def run_analysis_task(aid: int, url: str, custom_text: str = "") -> dict:
    """Full extraction + analysis pipeline updating DB record `aid`."""
    try:
        _update_analysis(aid, status="processing", progress_msg="در حال دریافت محتوا، زیرنویس و متادیتای لینک…")
        extracted = await extract_any_url(url, custom_text=custom_text)
        raw_text = (extracted.get("text") or "").strip()
        word_count = len(raw_text.split())
        lang = translate.detect_language(f"{extracted.get('title', '')} {raw_text[:800]}")

        _update_analysis(
            aid,
            platform=extracted.get("platform", "web"),
            title=extracted.get("title", ""),
            author=extracted.get("author", ""),
            duration_sec=int(extracted.get("duration_sec") or 0),
            image=extracted.get("image", ""),
            source_lang=lang,
            word_count=word_count,
            transcript_len=len(raw_text),
        )

        llm_cfg = _active_llm()
        if llm_cfg and (raw_text or extracted.get("title")):
            _update_analysis(aid, analysis_mode="ai")
            try:
                result = await _analyze_with_llm(aid, extracted, llm_cfg)
            except Exception as exc:
                # Do not silently label a keyless extraction as an AI analysis
                # when the user's configured provider failed.
                raise RuntimeError(f"خطای API تحلیل هوشمند: {str(exc)[:240]}") from exc
        else:
            _update_analysis(aid, analysis_mode="extractive")
            result = await _analyze_keyless(aid, extracted)

        final_title = result.get("title_fa") or extracted.get("title") or url
        _update_analysis(
            aid,
            title=final_title[:400],
            summary=result.get("summary") or "",
            key_points=result.get("key_points") or [],
            deep_analysis=result.get("deep_analysis") or "",
            timeline=result.get("timeline") or [],
            channel_draft=result.get("channel_draft") or "",
            status="ready",
            progress_msg="تحلیل کامل شد — آماده بررسی و ارسال به کانال",
            error="",
        )
    except Exception as exc:  # noqa: BLE001
        _update_analysis(
            aid,
            status="failed",
            progress_msg="",
            error=str(exc)[:400],
        )
    return get_analysis_public(aid) or {"ok": False}


def get_analysis_public(aid: int) -> dict | None:
    row = db.query_one("SELECT * FROM analyses WHERE id = ?", (aid,))
    if not row:
        return None
    return _format_row(row)


def _format_row(row: dict) -> dict:
    out = dict(row)
    out["duration_fmt"] = fmt_duration(out.get("duration_sec"))
    out["key_points"] = db.load_list(out.get("key_points"))
    out["timeline"] = db.load_list(out.get("timeline"))
    out["published_to"] = db.load_list(out.get("published_to"))
    return out


def list_analyses(limit: int = 40) -> list[dict]:
    rows = db.query("SELECT * FROM analyses ORDER BY id DESC LIMIT ?", (min(limit, 150),))
    return [_format_row(r) for r in rows]


async def publish_analysis(
    aid: int,
    *,
    destination_ids: list[int] | None = None,
    channel_draft: str | None = None,
    include_link: bool | None = None,
    send_image: bool | None = None,
) -> dict:
    """Approve & publish an analyzed link to selected (or all enabled) channels."""
    row = db.query_one("SELECT * FROM analyses WHERE id = ?", (aid,))
    if not row:
        return {"ok": False, "error_code": "item_not_found"}

    if channel_draft is not None:
        row["channel_draft"] = channel_draft.strip()
    if include_link is not None:
        row["include_link"] = 1 if include_link else 0
    if send_image is not None:
        row["send_image"] = 1 if send_image else 0

    _update_analysis(
        aid,
        channel_draft=row["channel_draft"],
        include_link=int(row["include_link"]),
        send_image=int(row["send_image"]),
    )

    if destination_ids:
        marks = ",".join("?" * len(destination_ids))
        destinations = db.query(f"SELECT * FROM destinations WHERE id IN ({marks})", destination_ids)
    else:
        destinations = db.query("SELECT * FROM destinations WHERE enabled = 1")
    if not destinations:
        return {"ok": False, "error_code": "no_destinations"}

    draft_text = (row.get("channel_draft") or row.get("summary") or row.get("title") or "").strip()
    url = (row.get("url") or "").strip()
    want_link = bool(int(row.get("include_link") or 0))
    want_img = bool(int(row.get("send_image", 1))) and bool(row.get("image"))
    sig_on = (db.get_setting("signature_enabled") or "1") != "0"
    global_footer = (db.get_setting("global_footer") or "").strip() if sig_on else ""

    results: list[dict] = []
    for dest in destinations:
        platform = (dest.get("platform") or "telegram").lower()
        use_html = publish.supports_html(platform) and (dest.get("parse_mode") or "HTML").upper() == "HTML"
        footer = (dest.get("footer") or "").strip() if sig_on else ""

        def _compose(limit_chars: int) -> str:
            tails: list[str] = []
            if footer:
                tails.append(f"<i>{html.escape(footer, quote=False)}</i>" if use_html else f"— {footer}")
            if global_footer and global_footer != footer:
                tails.append(f"<i>{html.escape(global_footer, quote=False)}</i>" if use_html else global_footer)
            if want_link and url:
                tails.append(
                    f'🔗 <a href="{html.escape(url, quote=True)}">مشاهده محتوای اصلی</a>'
                    if use_html
                    else f"🔗 لینک اصلی: {url}"
                )
            tail_plain_len = sum(len(publish.strip_tags(t)) for t in tails) + len(tails) * 2 + 6
            budget = max(80, limit_chars - tail_plain_len)
            body_trimmed = publish._truncate_clean(draft_text, budget)
            body_out = html.escape(body_trimmed, quote=False) if use_html else body_trimmed
            return "\n\n".join([body_out] + tails)

        if want_img and publish.supports_photo(platform):
            cap = _compose(publish.platform_limit(platform, "caption"))
            ok, detail = await publish.send_photo(dest, row["image"], cap)
            # Keep photo-enabled delivery honest: a failed photo is not silently
            # republished as a text-only analyzer post.
        else:
            ok, detail = await publish.send_message(dest, _compose(publish.platform_limit(platform, "text")))

        results.append({"id": dest["id"], "name": dest.get("name"), "ok": ok, "detail": detail})
        await asyncio.sleep(config.SEND_DELAY)

    any_ok = any(r["ok"] for r in results)
    if any_ok:
        _update_analysis(aid, status="published", posted_at=db.now_iso(), published_to=results)
    return {"ok": any_ok, "results": results, "analysis": get_analysis_public(aid)}
