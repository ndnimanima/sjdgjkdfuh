"""The news → channel pipeline.

sources → time window → de-duplication → smart topic & negative-keyword filter →
full-article body & real-photo enrichment → translation →
one message (with real news photo + full news text) per item → archive + logs.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from . import db, feeds, publish, topics as topics_mod, translate

RUN_LOCK = asyncio.Lock()
MAX_FEEDS_PER_RUN = 60
MAX_FILTERED_STORED = 25


def _load_topics() -> list[dict]:
    return db.query("SELECT * FROM topics WHERE enabled = 1 ORDER BY id")


def _load_feeds(job: dict) -> list[dict]:
    ids = [int(x) for x in db.load_list(job.get("feed_ids"))]
    if ids:
        marks = ",".join("?" * len(ids))
        return db.query(
            f"SELECT * FROM feeds WHERE id IN ({marks}) AND enabled = 1 ORDER BY sort_order, id",
            ids,
        )
    return db.query("SELECT * FROM feeds WHERE enabled = 1 ORDER BY sort_order, id")


def _load_destinations(job: dict) -> list[dict]:
    ids = [int(x) for x in db.load_list(job.get("destination_ids"))]
    if ids:
        marks = ",".join("?" * len(ids))
        return db.query(f"SELECT * FROM destinations WHERE id IN ({marks}) AND enabled = 1", ids)
    return db.query("SELECT * FROM destinations WHERE enabled = 1")


def _destination_accepts(destination: dict, item: dict) -> bool:
    raw = (destination.get("topic_filter") or "").strip()
    if not raw:
        return True
    allowed = {p.strip() for p in raw.replace("،", ",").split(",") if p.strip()}
    topic = item.get("topic") or ""
    return not allowed or any(name in topic for name in allowed)


def _seen(hashes: list[str]) -> set[str]:
    if not hashes:
        return set()
    found: set[str] = set()
    for i in range(0, len(hashes), 400):
        chunk = hashes[i : i + 400]
        marks = ",".join("?" * len(chunk))
        for row in db.query(f"SELECT hash FROM items WHERE hash IN ({marks})", chunk):
            found.add(row["hash"])
    return found


def _insert_item(item: dict) -> int:
    return db.execute(
        """INSERT OR IGNORE INTO items
           (hash, job_id, feed_id, feed_title, show_source, title, link, summary, image,
            published, lang, tags, topic, topic_key, title_fa, summary_fa, status,
            filter_reason, error, destinations, created_at, posted_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            item["hash"],
            item.get("job_id"),
            item.get("feed_id"),
            item.get("feed_title", ""),
            int(item.get("show_source") or 0),
            item.get("title", ""),
            item.get("link", ""),
            item.get("summary", ""),
            item.get("image", ""),
            item.get("published", ""),
            item.get("lang", ""),
            item.get("tags", ""),
            item.get("topic", ""),
            item.get("topic_key", ""),
            item.get("title_fa", ""),
            item.get("summary_fa", ""),
            item.get("status", "new"),
            item.get("filter_reason", ""),
            item.get("error", ""),
            db.dump(item.get("destinations", [])),
            db.now_iso(),
            item.get("posted_at", ""),
        ),
    )


def _update_item(item_id: int, **fields) -> None:
    if not fields:
        return
    if "destinations" in fields:
        fields["destinations"] = db.dump(fields["destinations"])
    assignments = ", ".join(f"{key} = ?" for key in fields)
    db.execute(f"UPDATE items SET {assignments} WHERE id = ?", (*fields.values(), item_id))


async def _enrich_one(item: dict, *, want_body: bool = True, want_image: bool = True) -> None:
    """Enrich an item in-place with full article text and verified real news image."""
    link = (item.get("link") or "").strip()
    if not link:
        return
    site_logo = item.get("_site_logo") or ""
    cur_body = (item.get("summary") or "").strip()
    cur_img = (item.get("image") or "").strip()
    if cur_img and feeds.is_logo_or_junk(cur_img, site_logo=site_logo):
        cur_img = ""
        item["image"] = ""

    need_body = want_body and (len(cur_body) < 280 or bool(item.get("_full_article", 1)))
    need_img = want_image and not cur_img
    if not need_body and not need_img:
        return

    info = await feeds.enrich_article(link, site_logo=site_logo)
    fetched_body = (info.get("body") or "").strip()
    if want_body and fetched_body and len(fetched_body) > len(cur_body):
        item["summary"] = fetched_body
    if want_image and not cur_img and info.get("image"):
        item["image"] = info["image"]
    if info.get("tags") and not item.get("tags"):
        item["tags"] = info["tags"]


async def run_job(
    job: dict,
    *,
    dry_run: bool = False,
    force: bool = False,
    max_items_override: int | None = None,
) -> dict:
    """Execute one publication job and return a translatable report."""
    job_id = job.get("id")
    if not force and not int(job.get("enabled", 1)):
        return {"ok": False, "error_code": "job_disabled", "events": [{"code": "job_disabled"}]}

    async with RUN_LOCK:
        report: dict = {
            "ok": True,
            "job_id": job_id,
            "job_name": job.get("name", ""),
            "dry_run": dry_run,
            "started_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "feeds": 0,
            "fetched": 0,
            "in_window": 0,
            "matched": 0,
            "new": 0,
            "translated": 0,
            "sent": 0,
            "failed": 0,
            "skipped": 0,
            "images": 0,
            "previews": [],
            "events": [],
            "lines": [],
        }

        def note(code: str, level: str = "info", **params) -> None:
            report["events"].append({"code": code, "level": level, "params": params})
            text = {
                "run_start": f"شروع اجرا — {params.get('feeds')} منبع، {params.get('destinations')} کانال، بازه {params.get('window')} ساعت",
                "run_dry": "حالت آزمایشی (بدون ارسال)",
                "feed_error": f"منبع «{params.get('feed')}» خوانده نشد: {params.get('error')}",
                "cap_note": f"{params.get('eligible')} خبر واجد شرایط بود؛ {params.get('taken')} خبر جدیدتر انتخاب شد",
                "no_fresh": "خبر تازه‌ای متناسب با شرایط این قاعده پیدا نشد",
                "no_feeds": "منبع خبری فعالی انتخاب نشده است",
                "no_destinations": "کانال مقصد فعالی انتخاب نشده است",
                "send_failed": f"ارسال «{params.get('title')}» ناموفق بود: {params.get('detail')}",
                "run_done": (
                    f"پایان اجرا — تازه {params.get('new')}، ارسال {params.get('sent')}، "
                    f"ناموفق {params.get('failed')}، ردشده {params.get('skipped')}"
                ),
            }.get(code, code)
            report["lines"].append(text)
            if not dry_run:
                db.log(job_id, text, level=level, code=code)

        feed_list = _load_feeds(job)[:MAX_FEEDS_PER_RUN]
        destinations = _load_destinations(job)
        if not feed_list:
            report["ok"] = False
            report["error_code"] = "no_feeds"
            note("no_feeds", level="error")
            return report
        if not destinations:
            report["ok"] = False
            report["error_code"] = "no_destinations"
            note("no_destinations", level="error")
            return report

        topic_rows = _load_topics()
        topic_name_by_id = {int(t["id"]): t.get("name", "") for t in topic_rows}
        selected_topics = {int(x) for x in db.load_list(job.get("topic_ids"))}
        filter_mode = (job.get("filter_mode") or "smart").strip().lower()
        exclude_keywords = (job.get("exclude_keywords") or "").strip()

        window = int(job.get("window_hours") or 24)
        max_items = max_items_override or int(job.get("max_items") or 8)
        translate_enabled = bool(int(job.get("translate", 1)))
        include_summary = bool(int(job.get("include_summary", 1)))
        full_text = bool(int(job.get("full_text", 1)))
        send_image = bool(int(job.get("send_image", 1)))
        show_topic = bool(int(job.get("show_topic", 1)))
        only_unseen = bool(int(job.get("only_unseen", 1)))

        note(
            "run_start",
            feeds=len(feed_list),
            destinations=len(destinations),
            window=window,
            dry=int(dry_run),
        )
        if dry_run:
            note("run_dry")

        # ── 1) gather fresh candidates ───────────────────────────────────────
        candidates: list[dict] = []
        for feed in feed_list:
            report["feeds"] += 1
            try:
                raw_items = await feeds.fetch_source(feed)
            except feeds.FeedError as exc:
                report["errors"] = report.get("errors", []) + [f"{feed.get('title')}: {exc}"]
                note("feed_error", level="warn", feed=feed.get("title", ""), error=str(exc))
                if not dry_run:
                    db.execute(
                        "UPDATE feeds SET last_checked = ?, last_status = ?, last_count = 0 WHERE id = ?",
                        (db.now_iso(), f"error: {exc}"[:200], feed["id"]),
                    )
                continue

            report["fetched"] += len(raw_items)
            in_window = [it for it in raw_items if feeds.within_window(it, window)]
            report["in_window"] += len(in_window)
            if not dry_run:
                db.execute(
                    "UPDATE feeds SET last_checked = ?, last_status = ?, last_count = ? WHERE id = ?",
                    (db.now_iso(), "ok", len(in_window), feed["id"]),
                )

            hashes = [feeds.item_hash(feed["url"], it) for it in in_window]
            seen = _seen(hashes) if only_unseen else set()
            for item, digest in zip(in_window, hashes):
                if digest in seen:
                    report["skipped"] += 1
                    continue
                item = dict(item)
                item["hash"] = digest
                item["feed_id"] = feed["id"]
                item["feed_title"] = feed.get("title", "")
                item["show_source"] = int(feed.get("show_source") or 0)
                item["custom_source_label"] = feed.get("custom_source_label") or ""
                item["_default_topic_id"] = int(feed.get("default_topic_id") or 0)
                item["_full_article"] = int(feed.get("full_article", 1))
                item["show_topic"] = 1 if show_topic else 0
                candidates.append(item)

        # ── 2) smart topic & blocklist filter before per-run cap ─────────────
        eligible: list[dict] = []
        filtered_out: list[dict] = []
        needs_deep_check: list[dict] = []

        for item in candidates:
            bad_kw = topics_mod.check_excluded(
                exclude_keywords, item.get("title", ""), item.get("summary", "")
            )
            if bad_kw:
                item["_filter_reason"] = f"کلیدواژه مسدودشده: «{bad_kw}»"
                report["skipped"] += 1
                filtered_out.append(item)
                continue

            best_topic, score, matched_ids = topics_mod.score_topics(
                topic_rows,
                item.get("title", ""),
                item.get("summary", ""),
                tags=item.get("tags", ""),
                default_topic_id=int(item.get("_default_topic_id") or 0),
            )
            item["_topic"] = best_topic
            item["_score"] = score

            if filter_mode == "all" or not selected_topics:
                eligible.append(item)
                continue

            min_score = 3 if filter_mode == "strict" else 1
            if (matched_ids & selected_topics) and score >= min_score:
                eligible.append(item)
            elif filter_mode == "smart" and len((item.get("summary") or "").strip()) < 140 and len(needs_deep_check) < 12:
                needs_deep_check.append(item)
            else:
                sel_names = "، ".join(topic_name_by_id.get(tid, str(tid)) for tid in list(selected_topics)[:3])
                if best_topic:
                    item["_filter_reason"] = f"موضوع خبر ({best_topic.get('name')}) جزو موضوعات انتخابی ({sel_names}) نبود"
                else:
                    item["_filter_reason"] = f"عدم تطبیق کلیدواژه با موضوعات انتخابی ({sel_names})"
                report["skipped"] += 1
                filtered_out.append(item)

        # Deep check short/HTML items by reading their article body before filtering them out
        if needs_deep_check:
            sem_pre = asyncio.Semaphore(4)

            async def _probe(cand: dict) -> None:
                async with sem_pre:
                    await _enrich_one(cand, want_body=True, want_image=send_image)

            await asyncio.gather(*(_probe(c) for c in needs_deep_check))
            for item in needs_deep_check:
                bad_kw = topics_mod.check_excluded(
                    exclude_keywords, item.get("title", ""), item.get("summary", "")
                )
                if bad_kw:
                    item["_filter_reason"] = f"کلیدواژه مسدودشده: «{bad_kw}»"
                    report["skipped"] += 1
                    filtered_out.append(item)
                    continue
                best_topic, score, matched_ids = topics_mod.score_topics(
                    topic_rows,
                    item.get("title", ""),
                    item.get("summary", ""),
                    tags=item.get("tags", ""),
                    default_topic_id=int(item.get("_default_topic_id") or 0),
                )
                item["_topic"] = best_topic
                if matched_ids & selected_topics:
                    eligible.append(item)
                else:
                    sel_names = "، ".join(topic_name_by_id.get(tid, str(tid)) for tid in list(selected_topics)[:3])
                    if best_topic:
                        item["_filter_reason"] = f"موضوع خبر ({best_topic.get('name')}) جزو موضوعات انتخابی ({sel_names}) نبود"
                    else:
                        item["_filter_reason"] = f"عدم تطبیق کلیدواژه با موضوعات انتخابی ({sel_names})"
                    report["skipped"] += 1
                    filtered_out.append(item)

        report["matched"] = len(eligible)
        eligible.sort(key=feeds.published_sort_key, reverse=True)
        if max_items > 0 and len(eligible) > max_items:
            note("cap_note", eligible=len(eligible), taken=max_items)
            eligible = eligible[:max_items]

        if not dry_run and filtered_out:
            for item in filtered_out[:MAX_FILTERED_STORED]:
                topic = item.get("_topic")
                _insert_item(
                    {
                        **item,
                        "job_id": job_id,
                        "status": "filtered",
                        "filter_reason": item.get("_filter_reason", "عدم تطبیق با فیلتر موضوعی قاعده"),
                        "lang": translate.detect_language(item.get("title", "")),
                        "topic": topics_mod.topic_label(topic),
                        "topic_key": str((topic or {}).get("id", "")),
                    }
                )

        if not eligible:
            note("no_fresh")
            report["finished_at"] = db.now_iso()
            if not dry_run:
                _finish_job(job, report)
            return report

        # ── 3) enrich full news text & real article photos concurrently ──────
        sem = asyncio.Semaphore(5)

        async def _prepare(it: dict) -> None:
            async with sem:
                await _enrich_one(
                    it,
                    want_body=bool(include_summary or full_text),
                    want_image=send_image,
                )

        await asyncio.gather(*(_prepare(it) for it in eligible))

        # ── 4) translate + publish ───────────────────────────────────────────
        for item in eligible:
            best_topic = item.pop("_topic", None)
            item.pop("_score", None)
            item.pop("_default_topic_id", None)
            item.pop("_full_article", None)
            item.pop("_site_logo", None)
            item.pop("_filter_reason", None)

            # Re-score topic if enrichment brought in full text and topic was previously unknown
            if best_topic is None and item.get("summary"):
                best_topic, _, _ = topics_mod.score_topics(
                    topic_rows, item.get("title", ""), item.get("summary", ""), tags=item.get("tags", "")
                )

            label = topics_mod.topic_label(best_topic)
            item["topic"] = (
                f"{label} {topics_mod.hashtag(best_topic.get('name', ''))}".strip()
                if (best_topic and show_topic)
                else ""
            )
            item["topic_key"] = str((best_topic or {}).get("id", ""))
            item["lang"] = translate.detect_language(
                f"{item.get('title', '')} {item.get('summary', '')}"
            )

            if not include_summary and not full_text:
                item["summary"] = ""

            title_fa = item.get("title", "")
            summary_fa = item.get("summary", "")
            if translate_enabled:
                title_fa, did = await translate.maybe_translate(item.get("title", ""), True)
                if did:
                    report["translated"] += 1
                if summary_fa:
                    summary_fa, did_s = await translate.maybe_translate(summary_fa, True)
                    if did_s and not did:
                        report["translated"] += 1

            item["title_fa"] = title_fa if title_fa != item.get("title") else ""
            item["summary_fa"] = summary_fa if summary_fa != item.get("summary") else ""

            if dry_run:
                report["previews"].append(
                    {
                        "title": item.get("title"),
                        "title_fa": item.get("title_fa") or "",
                        "summary": item.get("summary_fa") or item.get("summary") or "",
                        "topic": item.get("topic", ""),
                        "topic_id": item.get("topic_key", ""),
                        "link": item.get("link", ""),
                        "image": item.get("image", ""),
                        "lang": item.get("lang", ""),
                        "message": publish.render_item(item, destinations[0]),
                        "caption": publish.render_caption(item, destinations[0]),
                    }
                )
                continue

            item["job_id"] = job_id
            item["status"] = "new"
            item_id = _insert_item(item)
            if not item_id:
                report["skipped"] += 1
                continue
            report["new"] += 1

            delivered: list[dict] = []
            failures: list[str] = []
            for destination in destinations:
                if not _destination_accepts(destination, item):
                    continue
                platform = (destination.get("platform") or "").lower()
                use_photo = send_image and bool(item.get("image")) and publish.supports_photo(platform)
                if use_photo:
                    ok, detail = await publish.send_photo(
                        destination, item["image"], publish.render_caption(item, destination)
                    )
                    if ok:
                        report["images"] += 1
                    else:
                        # If the photo was rejected (e.g., site logo/banner) or failed, send clean full text
                        ok, detail = await publish.send_message(
                            destination, publish.render_item(item, destination)
                        )
                else:
                    ok, detail = await publish.send_message(
                        destination, publish.render_item(item, destination)
                    )
                delivered.append(
                    {"id": destination["id"], "name": destination.get("name"), "ok": ok, "detail": detail}
                )
                if ok:
                    report["sent"] += 1
                else:
                    report["failed"] += 1
                    failures.append(f"{destination.get('name')}: {detail}")
                await asyncio.sleep(config_send_delay())

            if any(d["ok"] for d in delivered):
                _update_item(item_id, status="sent", posted_at=db.now_iso(), destinations=delivered)
            else:
                _update_item(
                    item_id,
                    status="failed",
                    error=" | ".join(failures)[:500] or "no_destination_accepted",
                    destinations=delivered,
                )
                if failures:
                    note(
                        "send_failed",
                        level="error",
                        title=(item.get("title") or "")[:60],
                        detail=failures[0],
                    )

        note(
            "run_done",
            new=report["new"],
            sent=report["sent"],
            failed=report["failed"],
            skipped=report["skipped"],
        )
        report["finished_at"] = db.now_iso()
        if not dry_run:
            _finish_job(job, report)
        return report


def config_send_delay() -> float:
    from . import config

    return config.SEND_DELAY


def _finish_job(job: dict, report: dict) -> None:
    db.execute(
        "UPDATE jobs SET last_run = ?, last_result = ? WHERE id = ?",
        (
            db.now_iso(),
            db.dump(
                {
                    "new": report["new"],
                    "sent": report["sent"],
                    "failed": report["failed"],
                    "at": report["finished_at"],
                }
            ),
            job["id"],
        ),
    )


async def resend_item(item_id: int, destination_ids: list[int] | None = None) -> dict:
    item = db.query_one("SELECT * FROM items WHERE id = ?", (item_id,))
    if not item:
        return {"ok": False, "error_code": "item_not_found"}

    # If item was previously filtered before enrichment, enrich its body & real photo now!
    if len((item.get("summary") or "").strip()) < 140 and item.get("link"):
        await _enrich_one(item, want_body=True, want_image=True)
        if item.get("summary"):
            s_fa, did = await translate.maybe_translate(item["summary"], True)
            if did:
                item["summary_fa"] = s_fa
        _update_item(
            item_id,
            summary=item.get("summary", ""),
            summary_fa=item.get("summary_fa", ""),
            image=item.get("image", ""),
        )

    if destination_ids:
        marks = ",".join("?" * len(destination_ids))
        destinations = db.query(f"SELECT * FROM destinations WHERE id IN ({marks})", destination_ids)
    else:
        destinations = db.query("SELECT * FROM destinations WHERE enabled = 1")
    if not destinations:
        return {"ok": False, "error_code": "no_destinations"}

    # Respect feed's current show_source setting if feed still exists
    if item.get("feed_id"):
        feed = db.query_one("SELECT show_source, custom_source_label FROM feeds WHERE id = ?", (item["feed_id"],))
        if feed:
            item["show_source"] = int(feed.get("show_source") or 0)
            item["custom_source_label"] = feed.get("custom_source_label") or ""

    results = []
    for destination in destinations:
        platform = (destination.get("platform") or "").lower()
        if item.get("image") and publish.supports_photo(platform):
            ok, detail = await publish.send_photo(
                destination, item["image"], publish.render_caption(item, destination)
            )
            if not ok:
                ok, detail = await publish.send_message(
                    destination, publish.render_item(item, destination)
                )
        else:
            ok, detail = await publish.send_message(
                destination, publish.render_item(item, destination)
            )
        results.append(
            {"id": destination["id"], "name": destination.get("name"), "ok": ok, "detail": detail}
        )
        await asyncio.sleep(config_send_delay())
    if any(r["ok"] for r in results):
        _update_item(item_id, status="sent", filter_reason="", posted_at=db.now_iso(), destinations=results)
    return {"ok": any(r["ok"] for r in results), "results": results}


async def preview_item(item_id: int, destination_id: int | None = None) -> dict:
    item = db.query_one("SELECT * FROM items WHERE id = ?", (item_id,))
    if not item:
        return {"ok": False, "error_code": "item_not_found"}
    if len((item.get("summary") or "").strip()) < 140 and item.get("link"):
        await _enrich_one(item, want_body=True, want_image=True)
        _update_item(item_id, summary=item.get("summary", ""), image=item.get("image", ""))
    if item.get("feed_id"):
        feed = db.query_one("SELECT show_source, custom_source_label FROM feeds WHERE id = ?", (item["feed_id"],))
        if feed:
            item["show_source"] = int(feed.get("show_source") or 0)
            item["custom_source_label"] = feed.get("custom_source_label") or ""
    if destination_id:
        destination = db.query_one("SELECT * FROM destinations WHERE id = ?", (destination_id,))
    else:
        destination = db.query_one("SELECT * FROM destinations WHERE enabled = 1 ORDER BY id LIMIT 1")
    destination = destination or {
        "platform": "telegram",
        "parse_mode": "HTML",
        "footer": "",
        "name": "preview",
    }
    return {
        "ok": True,
        "message": publish.render_item(item, destination),
        "caption": publish.render_caption(item, destination),
        "has_image": bool(item.get("image")),
        "image": item.get("image") or "",
        "filter_reason": item.get("filter_reason") or "",
    }
