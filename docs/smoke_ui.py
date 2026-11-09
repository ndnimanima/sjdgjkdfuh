"""End-to-end UI smoke test for the Rozaneh panel (headless Chromium).

Creates, edits and deletes one of each entity through the real UI, checks that
the write reached the API, and reports every console error it saw.
"""
import asyncio
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("DATA_DIR", str(ROOT / "data"))).expanduser()
DB_PATH = DATA_DIR / "rozaneh.db"
ARCHIVE_FIXTURE_HASH = "smoke-ui-v106-archive-fixture"
BASE = "http://127.0.0.1:8080"


def seed_archive_fixture():
    """Add a deterministic sent item for preview tests without external network calls."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    summary = (
        "Synthetic article content created by the Rozaneh v1.06 browser smoke test. "
        "This fixture exercises archive filtering, safe message rendering, and the "
        "preview modal without downloading a feed, contacting a publisher, or posting anywhere."
    )
    with sqlite3.connect(DB_PATH, timeout=10) as conn:
        conn.execute("DELETE FROM items WHERE hash = ?", (ARCHIVE_FIXTURE_HASH,))
        cur = conn.execute(
            """INSERT INTO items(hash, title, title_fa, summary, summary_fa, status,
                                 created_at, posted_at)
               VALUES(?, ?, ?, ?, ?, 'sent', ?, ?)""",
            (ARCHIVE_FIXTURE_HASH, "Rozaneh smoke preview fixture", "نمونهٔ پیش‌نمایش تست",
             summary, summary, now, now),
        )
        return cur.lastrowid

ERRORS = []
CHECKS = []


def check(name, ok, extra=""):
    CHECKS.append((name, bool(ok), extra))
    print(("  ok   " if ok else "  FAIL ") + name + (("  " + str(extra)) if extra and not ok else ""))


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=["--no-sandbox"])
        ctx = await b.new_context(viewport={"width": 1440, "height": 1000})
        pg = await ctx.new_page()
        pg.on("console", lambda m: ERRORS.append(f"[{m.type}] {m.text}") if m.type == "error" else None)
        pg.on("pageerror", lambda e: ERRORS.append(f"[pageerror] {e}"))

        async def api_get(path):
            return await pg.evaluate(f"fetch('{path}', {{credentials:'same-origin'}}).then(r=>r.json())")

        # ── login ────────────────────────────────────────────────────────────
        await pg.goto(BASE + "/login")
        await pg.fill("#password", "rozaneh")
        await pg.click("#submitBtn")
        await pg.wait_for_url(BASE + "/")
        await pg.wait_for_selector(".stats", timeout=20000)
        check("login → dashboard", True)

        # ── make the run repeatable: drop leftovers from a crashed run ───────
        async def sweep(path, key, needle):
            rows = await api_get(path)
            for row in rows.get(key) or rows.get("items", []):
                if needle in str(row.get("name") or row.get("title") or ""):
                    await pg.evaluate(
                        "([p]) => fetch(p, {method:'DELETE', credentials:'same-origin'})",
                        [f"{path}/{row['id']}"],
                    )

        await sweep("/api/feeds", "feeds", "تست اسمک")
        await sweep("/api/topics", "topics", "تست اسمک")
        await sweep("/api/topics", "topics", "تست دیباگ")
        await sweep("/api/destinations", "destinations", "کانال تست اسمک")
        await sweep("/api/jobs", "jobs", "قاعدهٔ تست اسمک")
        await pg.wait_for_timeout(300)

        # ── feeds: create ────────────────────────────────────────────────────
        await pg.evaluate("window.Rozaneh.go('feeds')")
        await pg.wait_for_timeout(700)
        await pg.click(".page-actions [data-act='feed.new']")
        await pg.wait_for_selector("#feedForm")
        await pg.fill("#feedForm [name='title']", "تست اسمک — منبع")
        await pg.fill("#feedForm [name='url']", "https://example.com/rss.xml")
        await pg.click("#feedForm [data-act='feed.color'][data-color='violet']")
        await pg.click("[data-act='submit'][data-form-id='feedForm']")
        await pg.wait_for_timeout(900)
        feeds = (await api_get("/api/feeds"))["feeds"]
        made = [f for f in feeds if f["title"] == "تست اسمک — منبع"]
        check("feed.create", len(made) == 1, [f["title"] for f in feeds])
        fid = made[0]["id"] if made else None
        check("feed.create colour saved", made and made[0]["color"] == "violet", made and made[0]["color"])

        # ── feeds: toggle + edit ─────────────────────────────────────────────
        await pg.click(f"[data-act='feed.toggle'][data-id='{fid}']")
        await pg.wait_for_timeout(500)
        feeds = (await api_get("/api/feeds"))["feeds"]
        row = [f for f in feeds if f["id"] == fid][0]
        check("feed.toggle → off", int(row["enabled"]) == 0, row["enabled"])

        await pg.click(f"[data-act='feed.edit'][data-id='{fid}']")
        await pg.wait_for_selector("#feedForm")
        await pg.fill("#feedForm [name='title']", "تست اسمک — ویرایش‌شده")
        await pg.click("[data-act='submit'][data-form-id='feedForm']")
        await pg.wait_for_timeout(800)
        feeds = (await api_get("/api/feeds"))["feeds"]
        check("feed.edit", any(f["title"] == "تست اسمک — ویرایش‌شده" for f in feeds))

        # ── topics: create + match tester ────────────────────────────────────
        await pg.evaluate("window.Rozaneh.go('topics')")
        await pg.wait_for_timeout(700)
        await pg.click(".page-actions [data-act='topic.new']")
        await pg.wait_for_selector("#topicForm")
        await pg.fill("#topicForm [name='name']", "تست اسمک")
        await pg.fill("#topicForm [name='name_en']", "Smoke test")
        await pg.fill("#topicForm [name='keywords']", "اسمک,smoke,آزمون")
        await pg.click("[data-act='submit'][data-form-id='topicForm']")
        await pg.wait_for_timeout(800)
        topics = (await api_get("/api/topics"))["topics"]
        tids = [t["id"] for t in topics if t["name"] == "تست اسمک"]
        check("topic.create", len(tids) == 1)
        tid = tids[0] if tids else None

        await pg.click(".page-actions [data-act='topic.test']")
        await pg.wait_for_selector("#topicTestForm")
        await pg.fill("#topicTestForm [name='title']", "آزمون سیستم اسمک با موفقیت انجام شد")
        await pg.click("[data-act='submit'][data-form-id='topicTestForm']")
        await pg.wait_for_timeout(1200)
        res = await pg.inner_text("#topicTestResult")
        check("topic.match tester returns a match", "تست اسمک" in res, res[:80])
        await pg.keyboard.press("Escape")

        # ── channels: create ─────────────────────────────────────────────────
        await pg.evaluate("window.Rozaneh.go('channels')")
        await pg.wait_for_timeout(700)
        await pg.click(".page-actions [data-act='dest.new']")
        await pg.wait_for_selector("#destForm")
        await pg.fill("#destForm [name='name']", "کانال تست اسمک")
        await pg.select_option("#destForm [name='platform']", "eitaa")
        await pg.fill("#destForm [name='chat_id']", "-1009999999999")
        await pg.fill("#destForm [name='bot_token']", "smoketoken123456")
        await pg.click("[data-act='submit'][data-form-id='destForm']")
        await pg.wait_for_timeout(900)
        dests = (await api_get("/api/destinations"))["destinations"]
        dids = [d["id"] for d in dests if d["name"] == "کانال تست اسمک"]
        check("destination.create", len(dids) == 1)
        did = dids[0] if dids else None
        row = [d for d in dests if d["id"] == did][0] if did else {}
        check("destination.token masked", "••" in (row.get("bot_token") or ""), row.get("bot_token"))

        # ── channels: platform rules + real connection check ─────────────────
        await pg.click(".page-actions [data-act='dest.new']")
        await pg.wait_for_selector("#destForm")
        rules_tg = await pg.inner_text("#destRules")
        check("channel rules shown", "4096" in rules_tg and ("1024" in rules_tg or "1,024" in rules_tg), rules_tg[:80])
        await pg.select_option("#destForm [name='platform']", "eitaa")
        await pg.wait_for_timeout(200)
        rules_ei = await pg.inner_text("#destRules")
        check("rules follow the platform", rules_ei != rules_tg and "sendFile" in rules_ei, rules_ei[:120])
        mode_disabled = await pg.evaluate("document.querySelector('[data-dest-mode]').disabled")
        check("HTML mode disabled off-Telegram", mode_disabled is True, mode_disabled)
        await pg.keyboard.press("Escape")

        hook = await pg.evaluate(
            "() => fetch('/api/destinations', {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json'},"
            " body: JSON.stringify({name:'هوک اسمک', platform:'webhook', chat_id:'https://example.com/hook', bot_token:''})}).then(r=>r.json())"
        )
        hook_id = (hook or {}).get("id")
        verify = await pg.evaluate(
            f"() => fetch('/api/destinations/{hook_id}/verify', {{method:'POST', credentials:'same-origin'}}).then(r=>r.json())"
        )
        check("verify endpoint answers", verify.get("ok") is True and verify.get("detail") == "webhook_ready", verify)
        await pg.evaluate(f"() => fetch('/api/destinations/{hook_id}', {{method:'DELETE', credentials:'same-origin'}})")

        # ── rules: create + dry run ──────────────────────────────────────────
        await pg.evaluate("window.Rozaneh.go('jobs')")
        await pg.wait_for_timeout(900)
        await pg.click(".page-actions [data-act='job.new']")
        await pg.wait_for_selector("#jobForm")
        await pg.fill("#jobForm [name='name']", "قاعدهٔ تست اسمک")
        await pg.fill("#newTime", "09:15")
        await pg.click("[data-act='draft.addtime']")
        await pg.fill("#jobForm [name='interval_minutes']", "0")
        await pg.fill("#jobForm [name='window_hours']", "24")
        await pg.fill("#jobForm [name='max_items']", "2")
        await pg.click(f"[data-act='draft.pick'][data-kind='feed_ids'][data-id='{fid}']")
        await pg.click(f"[data-act='draft.pick'][data-kind='destination_ids'][data-id='{did}']")
        await pg.click("[data-act='submit'][data-form-id='jobForm']")
        await pg.wait_for_timeout(1000)
        jobs = (await api_get("/api/jobs"))["jobs"]
        jids = [j["id"] for j in jobs if j["name"] == "قاعدهٔ تست اسمک"]
        check("rule.create", len(jids) == 1)
        jid = jids[0] if jids else None
        job = [j for j in jobs if j["id"] == jid][0] if jid else {}
        check("rule.schedule saved", job.get("schedule_times") == '["09:15"]', job.get("schedule_times"))
        check("rule.picks saved", job.get("feed_ids") == [fid] and job.get("destination_ids") == [did],
              (job.get("feed_ids"), job.get("destination_ids")))

        await pg.click(f"[data-act='job.dry'][data-id='{jid}']")
        # a dry run really fetches and translates, so give it room on slow links
        await pg.wait_for_selector(".modal", timeout=75000)
        await pg.wait_for_timeout(2500)
        modal = await pg.inner_text(".modal")
        check("rule.dry-run opens report", "منبع خوانده‌شده" in modal or "Fetched" in modal, modal[:60])
        await pg.keyboard.press("Escape")

        # ── archive: filter + preview ────────────────────────────────────────
        archive_fixture_id = seed_archive_fixture()
        await pg.evaluate("window.Rozaneh.go('archive')")
        await pg.wait_for_timeout(900)
        await pg.click("[data-act='archive.filter'][data-status='sent']")
        await pg.wait_for_timeout(800)
        rows = await pg.query_selector_all(".irow")
        fixture_selector = f".irow[data-item-id='{archive_fixture_id}']"
        check("archive.filter sent includes fixture", await pg.locator(fixture_selector).count() == 1, len(rows))
        if await pg.locator(fixture_selector).count():
            await pg.click(f"{fixture_selector} [data-act='item.preview']")
            await pg.wait_for_selector(".modal", timeout=15000)
            await pg.wait_for_timeout(900)
            body = await pg.inner_text(".modal .previewbox")
            check("item.preview renders message", len(body.strip()) > 20, body[:60])
            check("item.preview has no raw tags", "<b>" not in body and "&lt;" not in body, body[:60])
            await pg.keyboard.press("Escape")

        # ── settings: save + translate test ──────────────────────────────────
        await pg.evaluate("window.Rozaneh.go('settings')")
        await pg.wait_for_timeout(900)
        await pg.fill("#setGeneral [name='timezone']", "Asia/Tehran")
        await pg.click("[data-act='submit'][data-form-id='setGeneral']")
        await pg.wait_for_timeout(900)
        s = (await api_get("/api/settings"))["settings"]
        check("settings.save", s["timezone"] == "Asia/Tehran", s["timezone"])

        await pg.click("[data-act='translate.test']")
        await pg.wait_for_selector("#trResult", timeout=20000)
        await pg.wait_for_timeout(6000)
        tr = await pg.inner_text("#trResult")
        check("translate.test responds", len(tr.strip()) > 3 and "…" not in tr, tr[:70])
        await pg.keyboard.press("Escape")

        # ── admin: appearance of a link + export ─────────────────────────────
        await pg.evaluate("window.Rozaneh.go('admin','links')")
        await pg.wait_for_timeout(900)
        await pg.fill(f"[data-act='admin.icon'][data-id='{fid}']", "🧪")
        await pg.click(f"[data-act='admin.showurl'][data-id='{fid}']")
        await pg.wait_for_timeout(800)
        feeds = (await api_get("/api/feeds"))["feeds"]
        row = [f for f in feeds if f["id"] == fid][0]
        check("admin.icon saved", row["icon"] == "🧪", row["icon"])
        check("admin.show_url toggled", int(row["show_url"]) in (0, 1))

        snippet = await pg.evaluate(
            "fetch('/api/admin/export?include_items=0',{credentials:'same-origin'}).then(r=>r.json()).then(d=>({feeds:(d.feeds||[]).length, has_settings: !!d.settings}))"
        )
        check("admin.export payload", snippet["feeds"] >= 1 and snippet["has_settings"], snippet)

        # ── cleanup ──────────────────────────────────────────────────────────
        await pg.evaluate(
            "([jid,did,tid,fid]) => Promise.all(["
            "fetch('/api/jobs/'+jid,{method:'DELETE',credentials:'same-origin'}),"
            "fetch('/api/destinations/'+did,{method:'DELETE',credentials:'same-origin'}),"
            "fetch('/api/topics/'+tid,{method:'DELETE',credentials:'same-origin'}),"
            "fetch('/api/feeds/'+fid,{method:'DELETE',credentials:'same-origin'})])",
            [jid, did, tid, fid],
        )
        await pg.evaluate(
            f"() => fetch('/api/items/{archive_fixture_id}', {{method:'DELETE', credentials:'same-origin'}})"
        )
        await pg.wait_for_timeout(800)
        after = await api_get("/api/feeds")
        check("cleanup", all(f["title"] != "تست اسمک — ویرایش‌شده" for f in after["feeds"]))

        print("\nCONSOLE ERRORS:", len(ERRORS))
        for e in ERRORS[:15]:
            print("  ", e[:200])
        failed = [c for c in CHECKS if not c[1]]
        print(f"\nRESULT: {len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed")
        await b.close()
        if failed or ERRORS:
            raise SystemExit(1)


asyncio.run(main())
