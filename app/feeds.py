"""News source reader & full-article extractor.

Pipeline:
1. RSS / Atom parser (extracts content:encoded, summary, categories, real media).
2. Smart HTML news-page fallback (extracts cards without copying homepage logos).
3. Full-article enrichment (`enrich_article`): visits the article URL (and unwraps
   aggregator frames/links such as Shahrekhabar/KhabarFarsi when needed) to pull
   the real multi-paragraph news text and the real article photograph — rejecting
   site logos, favicons, badges and placeholder banners.
"""

from __future__ import annotations

import calendar
import hashlib
import html as html_lib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urljoin, urlparse

import feedparser
import httpx
from bs4 import BeautifulSoup

from . import config

TAG_RE = re.compile(r"<[^>]+>")
BLOCK_END_RE = re.compile(r"</(?:p|div|li|blockquote|h[1-6]|section|article)>|<br\s*/?>", re.I)
HSPACE_RE = re.compile(r"[ \t\u00a0\r]+")
MULTI_NL_RE = re.compile(r"\n{3,}")
SPACE_RE = re.compile(r"\s+")
WP_THUMB_RE = re.compile(r"-(\d{2,3})x(\d{2,3})(?=\.(?:jpe?g|png|webp)(?:\?|$))", re.I)

LOGO_OR_JUNK_RE = re.compile(
    r"(?:^|[/_\-.])("
    r"logo|site[-_]?logo|brand|favicon|apple-touch-icon|sprite|avatar|"
    r"icon|ico|placeholder|default[-_]?img|default[-_]?image|default[-_]?thumb|"
    r"no[-_]?image|noimage|nothumb|blank|pixel|1x1|spacer|spinner|loading|"
    r"banner[-_]?ad|adsense|advert|header[-_]?logo|footer[-_]?logo|"
    r"watermark|badge|smilies|emoji|share[-_]?btn|telegram[-_]?logo"
    r")(?:[/_\-.]|$)|\.svg(?:\?|$)|^data:image/",
    re.I,
)

BOILERPLATE_LINE_RE = re.compile(
    r"^(?:"
    r"ادامه مطلب|بیشتر بخوانید|اخبار مرتبط|همچنین بخوانید|کلیک کنید|"
    r"انتهای پیام/?|به گزارش خبرنگار|کد خبر\s*:.*|منبع\s*:.*|"
    r"عضویت در کانال.*|ما را در .* دنبال کنید.*|"
    r"read more|continue reading|related articles|advertisement|subscribe.*"
    r")$",
    re.I,
)

AGGREGATOR_HOSTS = (
    "shahrekhabar.com",
    "khabarfarsi.com",
    "ghatreh.com",
    "khabarpu.com",
    "vista.ir",
    "sahebkhabar.ir",
    "tazenews.com",
)

BROWSER_HEADERS = {
    "User-Agent": config.USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "fa-IR,fa;q=0.95,en-US;q=0.8,en;q=0.7",
}


class FeedError(RuntimeError):
    pass


def clean_text(raw: str | None, limit: int = 2600, preserve_paragraphs: bool = True) -> str:
    """Clean HTML/feed markup into crisp, readable journalistic text."""
    if not raw:
        return ""
    if preserve_paragraphs:
        marked = BLOCK_END_RE.sub("\n\n", raw)
        unescaped = html_lib.unescape(TAG_RE.sub(" ", marked))
        lines: list[str] = []
        for raw_line in unescaped.splitlines():
            line = HSPACE_RE.sub(" ", raw_line).strip()
            if not line:
                if lines and lines[-1] != "":
                    lines.append("")
                continue
            if BOILERPLATE_LINE_RE.match(line):
                continue
            lines.append(line)
        text = "\n".join(lines).strip()
        text = MULTI_NL_RE.sub("\n\n", text)
    else:
        text = html_lib.unescape(TAG_RE.sub(" ", raw))
        text = SPACE_RE.sub(" ", text).strip()

    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    for sep in ("\n\n", ". ", "۔ ", "؟ ", "! ", " "):
        idx = cut.rfind(sep)
        if idx > limit * 0.65:
            cut = cut[: idx + (1 if sep.strip() else 0)]
            break
    return cut.rstrip() + "…"


def _clean_title(title: str) -> str:
    title = html_lib.unescape(TAG_RE.sub(" ", title or ""))
    return SPACE_RE.sub(" ", title).strip()


def _to_iso(entry: Any) -> str:
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        value = getattr(entry, attr, None) or (entry.get(attr) if isinstance(entry, dict) else None)
        if value:
            try:
                return (
                    datetime.fromtimestamp(calendar.timegm(value), tz=timezone.utc)
                    .replace(microsecond=0)
                    .isoformat()
                )
            except (TypeError, ValueError, OverflowError):
                continue
    return ""


def _normalize_url(url: str | None, base_url: str = "") -> str:
    url = html_lib.unescape((url or "").strip())
    if not url or url.startswith(("data:", "javascript:", "mailto:")):
        return ""
    if url.startswith("//"):
        url = "https:" + url
    elif base_url and not url.startswith(("http://", "https://")):
        url = urljoin(base_url, url)
    return url if url.startswith(("http://", "https://")) else ""


def is_logo_or_junk(
    url: str | None,
    *,
    alt: str = "",
    cls: str = "",
    site_logo: str = "",
    width: int = 0,
    height: int = 0,
) -> bool:
    """Return True if an image URL or tag looks like a site logo, icon or placeholder."""
    if not url:
        return True
    norm = url.strip()
    if site_logo and norm.rstrip("/") == site_logo.strip().rstrip("/"):
        return True
    parsed = urlparse(norm)
    path_q = f"{parsed.path}?{parsed.query}" if parsed.query else parsed.path
    if LOGO_OR_JUNK_RE.search(path_q):
        return True
    meta_str = f"{alt} {cls}".lower()
    if any(tok in meta_str for tok in ("site-logo", "custom-logo", "navbar-brand", "header-logo", "favicon", "avatar")):
        return True
    if width and width < 140:
        return True
    if height and height < 100:
        return True
    return False


def _upgrade_image(url: str) -> str:
    """Ask CDNs / WordPress for a full-size image instead of tiny 150px thumbs."""
    url = re.sub(r"(ichef\.bbci\.co\.uk/.*?/(?:ws|standard|news))/(\d{2,4})/", r"\1/800/", url)
    # Upgrade small WordPress thumbnails like photo-150x150.jpg or photo-300x169.jpg
    m = WP_THUMB_RE.search(url)
    if m:
        w, h = int(m.group(1)), int(m.group(2))
        if w <= 360 or h <= 240:
            url = WP_THUMB_RE.sub("", url)
    return url


def _pick_best_from_srcset(srcset: str, base_url: str = "") -> str:
    best_url = ""
    best_w = -1
    for part in (srcset or "").split(","):
        tokens = part.strip().split()
        if not tokens:
            continue
        candidate = _normalize_url(tokens[0], base_url)
        if not candidate:
            continue
        weight = 0
        if len(tokens) > 1 and tokens[1].endswith("w") and tokens[1][:-1].isdigit():
            weight = int(tokens[1][:-1])
        if weight >= best_w:
            best_w = weight
            best_url = candidate
    return best_url


def _img_tag_url(img: Any, base_url: str = "") -> str:
    srcset = img.get("srcset") or img.get("data-srcset") or ""
    if srcset:
        best = _pick_best_from_srcset(str(srcset), base_url)
        if best:
            return best
    for attr in ("data-src", "data-lazy-src", "data-original", "data-full-url", "src"):
        val = _normalize_url(img.get(attr), base_url)
        if val:
            return val
    return ""


def _entry_image(entry: Any) -> str:
    candidates: list[str] = []
    for key in ("media_content", "media_thumbnail"):
        for media in entry.get(key) or []:
            url = (media or {}).get("url")
            if url:
                candidates.append(url)
    for enc in entry.get("enclosures") or []:
        if str(enc.get("type", "")).startswith("image") and enc.get("href"):
            candidates.append(enc["href"])
    for content in entry.get("content") or []:
        val = (content or {}).get("value") or ""
        for m in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', val, re.I):
            candidates.append(m.group(1))
    for block in ("summary", "description"):
        text = entry.get(block) or ""
        for m in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', text, re.I):
            candidates.append(m.group(1))
    for link in entry.get("links") or []:
        href = (link or {}).get("href") or ""
        if str(link.get("type", "")).startswith("image") or re.search(
            r"\.(jpe?g|png|webp)(\?|$)", href, re.I
        ):
            candidates.append(href)
    for raw in candidates:
        candidate = _normalize_url(raw)
        if candidate and not is_logo_or_junk(candidate):
            return _upgrade_image(candidate)
    return ""


def _entry_body(entry: Any) -> str:
    """Prefer full <content:encoded> when richer than <description>/<summary>."""
    blocks: list[str] = []
    for content in entry.get("content") or []:
        val = clean_text((content or {}).get("value") or "", limit=2800)
        if val:
            blocks.append(val)
    summary = clean_text(entry.get("summary") or entry.get("description") or "", limit=2800)
    if summary:
        blocks.append(summary)
    if not blocks:
        return ""
    blocks.sort(key=len, reverse=True)
    return blocks[0]


def _entry_tags(entry: Any) -> str:
    terms: list[str] = []
    for tag in entry.get("tags") or []:
        term = (tag.get("term") or tag.get("label") or "").strip()
        if term and term not in terms:
            terms.append(term)
    return ", ".join(terms[:12])


def parse_feed(content: bytes) -> list[dict]:
    parsed = feedparser.parse(content)
    # Detect feed-level logo so we never mistake it for an article image
    feed_logo = ""
    feed_meta = getattr(parsed, "feed", {}) or {}
    if isinstance(feed_meta, dict):
        img_info = feed_meta.get("image") or {}
        if isinstance(img_info, dict):
            feed_logo = _normalize_url(img_info.get("href") or img_info.get("url") or "")
        elif isinstance(feed_meta.get("logo"), str):
            feed_logo = _normalize_url(feed_meta.get("logo"))

    items: list[dict] = []
    for entry in parsed.entries or []:
        title = _clean_title(entry.get("title", ""))
        link = (entry.get("link") or "").strip()
        if not title or not link:
            continue
        summary = _entry_body(entry)
        img = _entry_image(entry)
        if img and is_logo_or_junk(img, site_logo=feed_logo):
            img = ""
        items.append(
            {
                "title": title[:400],
                "link": link,
                "summary": summary,
                "image": img,
                "tags": _entry_tags(entry),
                "published": _to_iso(entry),
                "_site_logo": feed_logo,
            }
        )
    return items


def parse_html(content: bytes, base_url: str) -> list[dict]:
    """Smart HTML news-list extractor — NEVER assigns homepage og:image to articles."""
    soup = BeautifulSoup(content.decode("utf-8", errors="ignore"), "html.parser")

    # Capture homepage og:image strictly as a site_logo blacklist!
    site_logo = ""
    for prop in ("og:image", "twitter:image"):
        tag = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
        if tag and tag.get("content"):
            site_logo = _normalize_url(str(tag["content"]), base_url)
            break

    base_host = urlparse(base_url).netloc.lower()
    seen: set[str] = set()
    items: list[dict] = []

    for a in soup.find_all("a", href=True):
        href = str(a.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        url = _normalize_url(href, base_url)
        if not url or url in seen:
            continue
        parsed_u = urlparse(url)
        if parsed_u.netloc.lower() != base_host:
            continue
        # Skip category/tag/login/about index links when possible
        if re.search(r"/(?:login|register|about|contact|privacy|terms|tag|author|search)(?:/|$|\?)", parsed_u.path, re.I):
            continue

        # Extract headline text from heading inside <a> or anchor text itself
        heading = a.find(["h1", "h2", "h3", "h4", "strong"])
        raw_title = heading.get_text(" ", strip=True) if heading else a.get_text(" ", strip=True)
        title = SPACE_RE.sub(" ", raw_title).strip()
        if len(title) < 22 or len(title) > 320:
            continue

        seen.add(url)

        # Look for a real thumbnail inside the anchor or its immediate card container
        card = a.find_parent(["article", "li", "div"]) or a
        thumb = ""
        img_el = a.find("img") or (card.find("img") if card and len(card.find_all("a")) <= 4 else None)
        if img_el:
            cand = _img_tag_url(img_el, base_url)
            w = int(img_el.get("width") or 0) if str(img_el.get("width") or "").isdigit() else 0
            h_px = int(img_el.get("height") or 0) if str(img_el.get("height") or "").isdigit() else 0
            cls_str = " ".join(img_el.get("class") or [])
            alt_str = str(img_el.get("alt") or "")
            if cand and not is_logo_or_junk(cand, alt=alt_str, cls=cls_str, site_logo=site_logo, width=w, height=h_px):
                thumb = _upgrade_image(cand)

        # Look for a card excerpt/summary paragraph
        snippet = ""
        if card and len(card.find_all("a")) <= 4:
            p_el = card.find("p")
            if p_el:
                p_txt = SPACE_RE.sub(" ", p_el.get_text(" ", strip=True)).strip()
                if len(p_txt) >= 35 and p_txt != title:
                    snippet = p_txt[:900]

        items.append(
            {
                "title": title[:400],
                "link": url,
                "summary": snippet,
                "image": thumb,
                "tags": "",
                "published": "",
                "_site_logo": site_logo,
            }
        )
        if len(items) >= 40:
            break
    return items


# ── Full Article Body & Real Image Enrichment ──────────────────────────────


def _extract_json_ld(soup: BeautifulSoup, base_url: str, site_logo: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for script in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        raw = (script.string or script.get_text() or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        queue = data if isinstance(data, list) else [data]
        while queue:
            node = queue.pop(0)
            if not isinstance(node, dict):
                continue
            if isinstance(node.get("@graph"), list):
                queue.extend(node["@graph"])
            ntype = str(node.get("@type") or "")
            if any(k in ntype for k in ("Article", "NewsArticle", "BlogPosting", "ReportageNewsArticle", "VideoObject")):
                body = node.get("articleBody") or ""
                if isinstance(body, str) and len(body.strip()) > len(out.get("body", "")):
                    out["body"] = clean_text(body, limit=3000)
                if not out.get("description") and isinstance(node.get("description"), str):
                    out["description"] = clean_text(node["description"], limit=1000)
                if not out.get("title") and isinstance(node.get("headline"), str):
                    out["title"] = _clean_title(node["headline"])
                img_val = node.get("image") or node.get("thumbnailUrl")
                img_candidates: list[str] = []
                if isinstance(img_val, str):
                    img_candidates.append(img_val)
                elif isinstance(img_val, dict):
                    img_candidates.append(str(img_val.get("url") or img_val.get("contentUrl") or ""))
                elif isinstance(img_val, list):
                    for iv in img_val:
                        if isinstance(iv, str):
                            img_candidates.append(iv)
                        elif isinstance(iv, dict):
                            img_candidates.append(str(iv.get("url") or iv.get("contentUrl") or ""))
                for ic in img_candidates:
                    norm = _normalize_url(ic, base_url)
                    if norm and not is_logo_or_junk(norm, site_logo=site_logo):
                        out.setdefault("image", _upgrade_image(norm))
                        break
                if not out.get("published"):
                    for dk in ("datePublished", "dateCreated", "uploadDate"):
                        if isinstance(node.get(dk), str):
                            out["published"] = node[dk]
                            break
                author = node.get("author")
                if isinstance(author, dict) and author.get("name"):
                    out.setdefault("author", str(author["name"]))
                elif isinstance(author, list) and author and isinstance(author[0], dict):
                    out.setdefault("author", str(author[0].get("name") or ""))
    return out


ARTICLE_SELECTORS = (
    "[itemprop='articleBody']",
    "article .entry-content",
    "article .post-content",
    ".article-body",
    ".article-content",
    ".news-body",
    ".news-text",
    ".news_body",
    ".story-body",
    ".item-body",
    ".item-text",
    ".post-content",
    ".entry-content",
    ".single-content",
    ".content-body",
    ".main-news-body",
    ".doctext",
    "article",
    "main",
)

JUNK_CONTAINERS_RE = re.compile(
    r"related|recommend|comment|sidebar|footer|header|navbar|menu|breadcrumb|"
    r"share|social|tags|newsletter|author-box|advert|promo|widget|popup",
    re.I,
)


def _extract_dom_article(soup: BeautifulSoup, base_url: str, site_logo: str = "") -> tuple[str, str]:
    """Extract (multi_paragraph_body, real_article_image) from HTML DOM."""
    work = BeautifulSoup(str(soup), "html.parser")
    for bad in work.find_all(["script", "style", "noscript", "svg", "nav", "footer", "header", "aside", "form", "iframe"]):
        bad.decompose()

    best_container = None
    for sel in ARTICLE_SELECTORS:
        found = work.select_one(sel)
        if found and len(found.get_text(" ", strip=True)) >= 120:
            best_container = found
            break
    root = best_container or work.body or work

    # Remove noisy sub-blocks inside the chosen container
    for sub in list(root.find_all(["div", "section", "ul", "aside"])):
        if sub is root:
            continue
        attrs_txt = " ".join(sub.get("class") or []) + " " + str(sub.get("id") or "")
        if JUNK_CONTAINERS_RE.search(attrs_txt):
            sub.decompose()

    # 1) Look for real hero image inside the article body / figure first
    article_img = ""
    search_roots = [best_container, soup.find("article"), soup.find("main")]
    for sr in search_roots:
        if not sr:
            continue
        for img in sr.find_all("img"):
            cand = _img_tag_url(img, base_url)
            if not cand:
                continue
            w = int(img.get("width") or 0) if str(img.get("width") or "").isdigit() else 0
            h_px = int(img.get("height") or 0) if str(img.get("height") or "").isdigit() else 0
            cls_str = " ".join(img.get("class") or []) + " " + str(img.get("id") or "")
            alt_str = str(img.get("alt") or "")
            if not is_logo_or_junk(cand, alt=alt_str, cls=cls_str, site_logo=site_logo, width=w, height=h_px):
                article_img = _upgrade_image(cand)
                break
        if article_img:
            break

    # 2) Collect clean paragraphs (lead/subtitle + body <p> blocks)
    paragraphs: list[str] = []
    seen_p: set[str] = set()

    # Check dedicated lead/summary box often used on Iranian news agencies (ISNA, Mehr, Tasnim, IRNA, Fars, Varzesh3, Digiato)
    for lead_sel in (".lead", ".news-lead", ".introtext", ".summary", ".subtitle", ".post-excerpt", "[itemprop='description']"):
        lead_el = soup.select_one(lead_sel)
        if lead_el:
            lt = HSPACE_RE.sub(" ", lead_el.get_text(" ", strip=True)).strip()
            if len(lt) >= 35 and not BOILERPLATE_LINE_RE.match(lt):
                paragraphs.append(lt)
                seen_p.add(lt[:80])

    for p in root.find_all(["p", "blockquote"]):
        txt = HSPACE_RE.sub(" ", p.get_text(" ", strip=True)).strip()
        if len(txt) < 28:
            continue
        if BOILERPLATE_LINE_RE.match(txt):
            continue
        # Skip paragraphs that are mostly links
        link_txt_len = sum(len(a.get_text(strip=True)) for a in p.find_all("a"))
        if link_txt_len > 0.78 * len(txt) and len(txt) < 140:
            continue
        sig = txt[:80]
        if sig in seen_p:
            continue
        seen_p.add(sig)
        paragraphs.append(txt)
        if sum(len(x) for x in paragraphs) >= 2800:
            break

    # Fallback if site uses <div> text blocks instead of <p>
    if not paragraphs and best_container:
        raw_html = str(best_container)
        cleaned = clean_text(raw_html, limit=2600, preserve_paragraphs=True)
        if len(cleaned) >= 60:
            return cleaned, article_img

    body = "\n\n".join(paragraphs)
    return clean_text(body, limit=2800, preserve_paragraphs=True), article_img


def _find_aggregator_target(soup: BeautifulSoup, page_url: str) -> str:
    """If page_url is an aggregator wrapper (like shahrekhabar.com), locate the real source URL."""
    host = urlparse(page_url).netloc.lower()
    is_agg = any(h in host for h in AGGREGATOR_HOSTS)

    # Check iframe pointing to external article
    for iframe in soup.find_all("iframe", src=True):
        src = _normalize_url(str(iframe.get("src") or ""), page_url)
        if src and urlparse(src).netloc.lower() != host:
            if not re.search(r"youtube|aparat|google|doubleclick|ads|player", src, re.I):
                return src

    if not is_agg:
        return ""

    # Check explicit source link on aggregator page
    for a in soup.find_all("a", href=True):
        href = _normalize_url(str(a.get("href") or ""), page_url)
        if not href:
            continue
        ahost = urlparse(href).netloc.lower()
        if not ahost or ahost == host or any(x in ahost for x in ("telegram.me", "t.me", "instagram.com", "twitter.com", "x.com", "whatsapp.com")):
            continue
        cls_id = (" ".join(a.get("class") or []) + " " + str(a.get("id") or "")).lower()
        txt = a.get_text(" ", strip=True)
        if (
            any(k in cls_id for k in ("source", "origin", "external", "more", "full", "news-link"))
            or any(k in txt for k in ("مشاهده متن کامل", "منبع خبر", "لینک خبر", "ادامه خبر در", "مشاهده خبر"))
            or str(a.get("target") or "") == "_blank"
        ):
            if len(urlparse(href).path.strip("/")) >= 4:
                return href
    return ""


def parse_article_html(html_text: str, page_url: str, site_logo: str = "") -> dict[str, Any]:
    """Parse a single web/article HTML document into title, body, real image, meta."""
    soup = BeautifulSoup(html_text, "html.parser")
    ld = _extract_json_ld(soup, page_url, site_logo=site_logo)

    # Meta tags
    meta_desc = ""
    meta_img = ""
    meta_title = ""
    meta_site = ""
    for meta in soup.find_all("meta"):
        key = str(meta.get("property") or meta.get("name") or "").lower().strip()
        val = str(meta.get("content") or "").strip()
        if not key or not val:
            continue
        if key in ("og:description", "twitter:description", "description") and len(val) > len(meta_desc):
            meta_desc = clean_text(val, limit=1200)
        elif key in ("og:image", "og:image:secure_url", "og:image:url", "twitter:image", "twitter:image:src") and not meta_img:
            cand = _normalize_url(val, page_url)
            if cand and not is_logo_or_junk(cand, site_logo=site_logo):
                meta_img = _upgrade_image(cand)
        elif key in ("og:title", "twitter:title") and not meta_title:
            meta_title = _clean_title(val)
        elif key == "og:site_name":
            meta_site = val.strip()

    dom_body, dom_img = _extract_dom_article(soup, page_url, site_logo=site_logo)

    # Pick richest body text
    body_candidates = [ld.get("body") or "", dom_body, ld.get("description") or "", meta_desc]
    body_candidates = [b.strip() for b in body_candidates if b and b.strip()]
    body = ""
    if body_candidates:
        # Prefer multi-sentence article body over tiny meta description
        body_candidates.sort(key=len, reverse=True)
        body = body_candidates[0]

    # Pick most authentic news photo:
    # For aggregator pages, their og:image is almost always their own site logo!
    host = urlparse(page_url).netloc.lower()
    is_agg = any(h in host for h in AGGREGATOR_HOSTS)
    if is_agg:
        image = ld.get("image") or dom_img or ""
    else:
        image = ld.get("image") or dom_img or meta_img or ""

    h1 = soup.find("h1")
    title = (
        ld.get("title")
        or ( _clean_title(h1.get_text(" ", strip=True)) if h1 else "" )
        or meta_title
        or (_clean_title(soup.title.get_text(" ", strip=True)) if soup.title else "")
    )

    tags: list[str] = []
    for kw_meta in soup.find_all("meta", attrs={"property": "article:tag"}):
        if kw_meta.get("content"):
            tags.append(str(kw_meta["content"]).strip())
    kw_tag = soup.find("meta", attrs={"name": "keywords"})
    if kw_tag and kw_tag.get("content"):
        tags.extend([x.strip() for x in str(kw_tag["content"]).replace("،", ",").split(",") if x.strip()])

    return {
        "title": title[:400],
        "body": body,
        "image": image,
        "author": ld.get("author") or meta_site or "",
        "published": ld.get("published") or "",
        "tags": ", ".join(dict.fromkeys(tags))[:300],
        "_target_url": _find_aggregator_target(soup, page_url),
    }


async def enrich_article(link: str, site_logo: str = "") -> dict[str, Any]:
    """Fetch an article URL (unwrapping aggregators if needed) for full body & real photo."""
    empty = {"title": "", "body": "", "image": "", "author": "", "published": "", "tags": ""}
    if not link or not link.startswith(("http://", "https://")):
        return empty
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10.0), follow_redirects=True, headers=BROWSER_HEADERS
        ) as client:
            resp = await client.get(link)
            if resp.status_code >= 400:
                return empty
            ctype = (resp.headers.get("content-type") or "").lower()
            if "html" not in ctype and "xml" not in ctype and ctype:
                return empty
            first = parse_article_html(resp.text[:700_000], str(resp.url), site_logo=site_logo)

            # If this was an aggregator wrapper with weak body or missing real image, follow target URL!
            target = first.get("_target_url") or ""
            if target and (len(first.get("body") or "") < 260 or not first.get("image")):
                try:
                    resp2 = await client.get(target, timeout=8.5)
                    if resp2.status_code < 400 and "html" in (resp2.headers.get("content-type") or "html").lower():
                        second = parse_article_html(resp2.text[:700_000], str(resp2.url), site_logo=site_logo)
                        if len(second.get("body") or "") > len(first.get("body") or ""):
                            first["body"] = second["body"]
                        if second.get("image") and not first.get("image"):
                            first["image"] = second["image"]
                        if second.get("tags") and not first.get("tags"):
                            first["tags"] = second["tags"]
                except Exception:
                    pass
            first.pop("_target_url", None)
            return first
    except Exception:  # noqa: BLE001 — enrichment must never crash a run
        return empty


async def og_image(link: str, site_logo: str = "") -> str:
    """Compatibility helper: return the verified real article image for `link`."""
    info = await enrich_article(link, site_logo=site_logo)
    return info.get("image") or ""


async def fetch_source(feed: dict) -> list[dict]:
    """Download a source and return normalized items (newest first when dated)."""
    url = (feed.get("url") or "").strip()
    if not url:
        raise FeedError("لینک منبع خالی است")
    headers = {
        "User-Agent": config.USER_AGENT,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, text/html;q=0.8, */*;q=0.5",
        "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
    }
    try:
        async with httpx.AsyncClient(
            timeout=config.HTTP_TIMEOUT, follow_redirects=True, headers=headers
        ) as client:
            response = await client.get(url)
    except httpx.HTTPError as exc:
        raise FeedError(f"خطا در دریافت منبع: {exc.__class__.__name__}") from exc

    if response.status_code >= 400:
        raise FeedError(f"منبع کد {response.status_code} برگرداند")

    content = response.content
    if not content:
        raise FeedError("پاسخ منبع خالی بود")

    items = parse_feed(content)
    if not items:
        items = parse_html(content, str(response.url))
    if not items:
        raise FeedError("هیچ خبری در این منبع پیدا نشد (RSS یا HTML قابل خواندن نبود)")

    items.sort(key=published_sort_key, reverse=True)
    return items


def item_hash(feed_url: str, item: dict) -> str:
    seed = f"{feed_url}|{item.get('link') or ''}|{item.get('title') or ''}"
    return hashlib.sha1(seed.encode("utf-8", errors="ignore")).hexdigest()[:32]


def within_window(item: dict, hours: int, now: datetime | None = None) -> bool:
    if hours <= 0:
        return True
    now = now or datetime.now(timezone.utc)
    published = item.get("published") or ""
    if not published:
        return True
    try:
        stamp = datetime.fromisoformat(published)
    except ValueError:
        return True
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp >= now - timedelta(hours=hours)


def published_sort_key(item: dict) -> datetime:
    try:
        stamp = datetime.fromisoformat(item.get("published") or "")
        return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.now(timezone.utc)
