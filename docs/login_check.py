"""Sign-in page layout probe — every width, both directions, multiple engines.

Checks the v1.08 login layout:
  * the password field stays inside the card and does not collide with submit,
  * the submit button spans the card content width,
  * nothing overflows the viewport and no console errors appear.

    python docs/login_check.py --base http://127.0.0.1:8080 --engines chromium
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from playwright.async_api import async_playwright

WIDTHS = [320, 390, 430, 535, 768, 1024, 1440]
MEASURE = """() => {
  const btn = document.getElementById('submitBtn');
  const card = document.querySelector('.login-card');
  const input = document.getElementById('password');
  const cs = getComputedStyle(input);
  const r = (el) => { const b = el.getBoundingClientRect();
    return {l: Math.round(b.left), r: Math.round(b.right), t: Math.round(b.top), b: Math.round(b.bottom), w: Math.round(b.width), h: Math.round(b.height)}; };
  const cardStyle = getComputedStyle(card);
  const inner = card.clientWidth - parseFloat(cardStyle.paddingLeft) - parseFloat(cardStyle.paddingRight);
  return {
    dir: document.documentElement.dir,
    btn: r(btn), input: r(input), card: r(card),
    contentWidth: Math.round(inner),
    cardPaddingLeft: parseFloat(cardStyle.paddingLeft), cardPaddingRight: parseFloat(cardStyle.paddingRight),
    docWidth: document.documentElement.scrollWidth,
    viewport: window.innerWidth,
  };
}"""


def verdict(m: dict) -> list[str]:
    problems = []
    # 1. password field stays inside the card, above the submit button
    if m["input"]["l"] < m["card"]["l"] - 1 or m["input"]["r"] > m["card"]["r"] + 1:
        problems.append(f"password field escapes card ({m['input']['l']}..{m['input']['r']})")
    if m["input"]["b"] >= m["btn"]["t"]:
        problems.append("password field collides with submit button")
    # 2. submit button spans the card content
    if abs(m["btn"]["w"] - m["contentWidth"]) > 2:
        problems.append(f"submit is {m['btn']['w']}px, card content is {m['contentWidth']}px")
    if m["btn"]["h"] < 38:
        problems.append(f"submit is only {m['btn']['h']}px tall")
    # 3. no sideways scroll
    if m["docWidth"] > m["viewport"] + 1:
        problems.append(f"horizontal overflow {m['docWidth']} > {m['viewport']}")
    return problems


async def probe(pw, engine: str, base: str, shots: str | None) -> list[str]:
    failures: list[str] = []
    browser = await getattr(pw, engine).launch(
        args=["--no-sandbox"] if engine == "chromium" else []
    )
    for width in WIDTHS:
        for lang in ("fa", "en"):
            ctx = await browser.new_context(
                viewport={"width": width, "height": 780},
                device_scale_factor=2 if width <= 535 else 1,
            )
            page = await ctx.new_page()
            errors: list[str] = []
            page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            await page.add_init_script(
                f"try{{localStorage.setItem('rz.lang','{lang}');localStorage.setItem('rz.theme','slate');}}catch(e){{}}"
            )
            await page.goto(base + "/login", wait_until="networkidle")
            await page.wait_for_timeout(250)
            await page.fill("#password", "secret123")
            metrics = await page.evaluate(MEASURE)
            problems = verdict(metrics)
            if errors:
                problems.append("console: " + "; ".join(errors)[:200])
            tag = f"{engine} {width}px {lang}"
            if problems:
                failures.append(f"{tag}: {' | '.join(problems)}")
                print(f"  FAIL {tag}: {' | '.join(problems)}")
            else:
                print(
                    f"  ok   {tag}: btn {metrics['btn']['w']}x{metrics['btn']['h']} "
                    f"card {metrics['contentWidth']} input {metrics['input']['w']}px"
                )
            if shots and width in (390, 535) and lang == "fa":
                await page.screenshot(path=f"{shots}/login-{engine}-{width}.png", full_page=True)
            await ctx.close()
    await browser.close()
    return failures


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8080")
    ap.add_argument("--shots", default="")
    ap.add_argument("--engines", default="chromium")
    args = ap.parse_args()
    engines = [e.strip() for e in args.engines.split(",") if e.strip()]
    failures: list[str] = []
    async with async_playwright() as pw:
        for engine in engines:
            print(f"\n[{engine}]")
            failures += await probe(pw, engine, args.base, args.shots)
    print("\n" + ("ALL LOGIN CHECKS PASSED" if not failures else f"{len(failures)} FAILURES"))
    if failures:
        print(json.dumps(failures, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
