"""Responsive SPA smoke check for Rozaneh v1.08.

Logs in, visits every first-level panel route at several viewport widths, checks
for horizontal overflow or JavaScript errors, then verifies language/theme toggles
and the mobile sidebar. Optional screenshots are saved only when --shots is given.

Use a disposable instance; the default bootstrap password is ``rozaneh``.

    python docs/verify_panel.py --base http://127.0.0.1:8080
"""
from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from playwright.async_api import async_playwright

PAGES = (
    "dashboard", "analyzer", "feeds", "topics", "channels", "jobs",
    "archive", "logs", "settings", "admin", "creators",
)
WIDTHS = (1440, 1120, 900, 768, 430, 390, 320)


async def run(base: str, password: str, shots: str | None) -> int:
    base = base.rstrip("/")
    errors: list[str] = []
    failures: list[str] = []
    checks = 0
    output = Path(shots).expanduser() if shots else None
    if output:
        output.mkdir(parents=True, exist_ok=True)

    def check(label: str, ok: bool, detail: str = "") -> None:
        nonlocal checks
        checks += 1
        if ok:
            print(f"  ok   {label}")
        else:
            failures.append(f"{label}: {detail}")
            print(f"  FAIL {label}: {detail}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox"])
        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        page.on("console", lambda msg: errors.append(f"[console] {msg.text}") if msg.type == "error" else None)
        page.on("pageerror", lambda exc: errors.append(f"[pageerror] {exc}"))

        await page.goto(base + "/login", wait_until="domcontentloaded")
        await page.wait_for_selector("#password")
        await page.fill("#password", password)
        await page.click("#submitBtn")
        await page.wait_for_url(base + "/", timeout=20000)
        await page.wait_for_selector(".stats", timeout=20000)
        check("login and dashboard boot", True)

        async def check_internal_scroll(width: int, height: int, *, desktop: bool) -> None:
            await page.set_viewport_size({"width": width, "height": height})
            await page.evaluate(
                """() => { const view = document.querySelector('#view'); if (view) view.style.minHeight = '1800px'; }"""
            )
            before = await page.evaluate(
                """() => ({
                    topbar: document.querySelector('.topbar').getBoundingClientRect().top,
                    sidebar: document.querySelector('.sidebar').getBoundingClientRect().top,
                    window: window.scrollY
                })"""
            )
            await page.locator("#main").evaluate("el => { el.scrollTop = 700; }")
            await page.wait_for_timeout(80)
            after = await page.evaluate(
                """() => ({
                    main: document.querySelector('#main').scrollTop,
                    topbar: document.querySelector('.topbar').getBoundingClientRect().top,
                    sidebar: document.querySelector('.sidebar').getBoundingClientRect().top,
                    window: window.scrollY,
                    pageHeight: document.documentElement.scrollHeight,
                    viewport: window.innerHeight
                })"""
            )
            check(
                f"content pane scrolls independently at {width}px",
                after["main"] >= 500 and after["window"] == 0 and after["pageHeight"] <= after["viewport"] + 1,
                str(after),
            )
            check(
                f"top bar stays fixed at {width}px",
                abs(after["topbar"] - before["topbar"]) < 1,
                f"topbar moved from {before['topbar']} to {after['topbar']}",
            )
            if desktop:
                check(
                    "desktop navigation stays fixed",
                    abs(after["sidebar"] - before["sidebar"]) < 1,
                    f"sidebar moved from {before['sidebar']} to {after['sidebar']}",
                )
            await page.evaluate(
                """() => { const view = document.querySelector('#view'); if (view) view.style.minHeight = ''; document.querySelector('#main').scrollTop = 0; }"""
            )

        await check_internal_scroll(1440, 900, desktop=True)
        await check_internal_scroll(390, 844, desktop=False)

        before_lang = await page.evaluate("document.documentElement.lang")
        await page.click("#langBtn")
        await page.wait_for_function("lang => document.documentElement.lang !== lang", arg=before_lang)
        check("language toggle updates document direction", True)
        await page.click("#langBtn")
        await page.wait_for_function("lang => document.documentElement.lang === lang", arg=before_lang)
        check("language toggle restores original preference", True)

        palette_closed = await page.locator("#themePopover").evaluate("el => el.hidden")
        check("theme colors start tucked behind the palette button", palette_closed)
        await page.click("#themeToggle")
        await page.wait_for_function("!document.querySelector('#themePopover').hidden")
        await page.click('#themeSwitch [data-t="amber"]')
        await page.wait_for_function("document.documentElement.dataset.theme === 'amber'")
        check("theme toggle selects amber and closes the palette", await page.locator("#themePopover").evaluate("el => el.hidden"))

        for width in WIDTHS:
            await page.set_viewport_size({"width": width, "height": 900})
            await page.wait_for_timeout(100)
            for slug in PAGES:
                await page.evaluate("slug => window.Rozaneh.go(slug)", slug)
                await page.wait_for_timeout(100)
                heading = await page.locator("#view .page-intro").count()
                scroll = await page.evaluate("document.documentElement.scrollWidth")
                client = await page.evaluate("document.documentElement.clientWidth")
                check(f"{slug} renders at {width}px", heading > 0, "page heading not found")
                check(
                    f"{slug} fits at {width}px",
                    scroll <= client + 1,
                    f"document width {scroll}px exceeds viewport {client}px",
                )
                if output and slug == "dashboard" and width in (1440, 390):
                    await page.screenshot(path=str(output / f"dashboard-{width}.png"), full_page=True)

        await page.set_viewport_size({"width": 390, "height": 844})
        await page.evaluate("window.Rozaneh.go('dashboard')")
        await page.click("#menuBtn")
        opened = await page.locator("#sidebar").evaluate("el => el.classList.contains('open')")
        check("mobile menu opens sidebar", opened)

        for err in errors:
            failures.append(err)
        check("browser console/page errors", not errors, "; ".join(errors[:4]))
        await browser.close()

    print(f"\nRESULT: {checks - len(failures)}/{checks} checks passed")
    if failures:
        print("\nFAILURES:")
        for failure in failures:
            print(" -", failure)
    return 1 if failures else 0


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8080")
    parser.add_argument("--password", default=os.environ.get("ROZANEH_TEST_PASSWORD", "rozaneh"))
    parser.add_argument("--shots", default="", help="Optional directory for dashboard screenshots")
    args = parser.parse_args()
    return await run(args.base, args.password, args.shots or None)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
