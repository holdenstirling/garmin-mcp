"""Browser connectivity sweep (not part of the unit suite: needs a running app and Chromium).

Opens the app at phone size, visits every tab, the header controls (Search, Notifications,
Chats, Me), every Me row and each deep-link kind (/app/?open=<kind>&id=..), and reports:
console errors, failed requests (4xx/5xx), and controls that a tap can't reach (covered by
something else). Screenshots land in --out.

    python3 tests/browser_sweep.py --base http://localhost:8001 --out /tmp/sweep \
        [--chromium /opt/pw-browsers/chromium-1194/chrome-linux/chrome] [--scheme light|dark|both] \
        [--deep person=<uid> --deep club=<id> --deep activity=<id> --deep checklist=<event id> ...]

Run it against a dev server with demo data (DEV_NO_AUTH_USER, RABBIT_FAKE_GARMIN=1). Exit
status 1 when anything was found. The static half (tests/test_connectivity_static.py) runs with
the Python suite.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys

COVERED_JS = """() => { const r = []; for (const el of document.querySelectorAll('button,a[href],[role=tab],input,select,textarea')) {
  const b = el.getBoundingClientRect(); if (b.width < 2 || b.height < 2) continue
  if (b.bottom < 0 || b.top > innerHeight || b.right < 0 || b.left > innerWidth) continue
  if (getComputedStyle(el).visibility === 'hidden' || el.closest('[inert],[aria-hidden=true],.hidden')) continue
  const x = Math.min(Math.max(b.left + b.width / 2, 1), innerWidth - 1), y = Math.min(Math.max(b.top + b.height / 2, 1), innerHeight - 1)
  const hit = document.elementFromPoint(x, y); if (!hit) continue
  if (el.contains(hit) || hit.contains(el) || hit.closest('label')?.contains(el)) continue
  r.push((el.getAttribute('aria-label') || el.textContent || el.tagName).trim().slice(0, 40) + ' <- covered by ' + hit.tagName) }
  return r.slice(0, 12) }"""
TABS = ["Home", "Schedule", "Feed", "Clubs", "Progress"]
HEADER = ["Search", re.compile(r"^Notifications"), re.compile(r"^Chats"), re.compile(r"^Me\b")]
ME_ROWS = ["Training profile", "What Rabbit knows", "Gear garage", "Coaches", "Connected apps", "Settings", "Usage"]


async def sweep(base: str, out: str, chromium: str | None, scheme: str, deep: list[tuple[str, str]]) -> dict:
    from playwright.async_api import async_playwright
    found: dict = {"errors": [], "failed": [], "covered": []}
    async with async_playwright() as p:
        b = await p.chromium.launch(**({"executable_path": chromium} if chromium else {}))
        c = await b.new_context(viewport={"width": 375, "height": 812}, is_mobile=True, has_touch=True, color_scheme=scheme)
        pg = await c.new_page()
        where = {"v": "start"}
        pg.on("console", lambda m: found["errors"].append([where["v"], m.text[:200]]) if m.type == "error" else None)
        pg.on("pageerror", lambda e: found["errors"].append([where["v"], "PAGEERROR " + str(e)[:300]]))
        pg.on("response", lambda r: found["failed"].append([where["v"], r.status, r.request.method, r.url.replace(base, "")])
              if r.status >= 400 else None)

        async def home() -> None:
            await pg.goto(f"{base}/app/", wait_until="networkidle")
            await pg.wait_for_timeout(1500)

        async def step(name: str, fn) -> None:
            where["v"] = name
            try:
                await fn()
                await pg.wait_for_timeout(1200)
                await pg.screenshot(path=os.path.join(out, f"{scheme}_{re.sub(r'[^A-Za-z0-9]+', '_', name)}.png"))
                found["covered"] += [[name, x] for x in await pg.evaluate(COVERED_JS)]
            except Exception as e:  # noqa: BLE001 - report and keep sweeping
                found["errors"].append([name, "STEP FAILED " + str(e)[:200]])
            await pg.keyboard.press("Escape")

        await home()
        for t in TABS:
            await step(f"tab {t}", lambda t=t: pg.locator("nav.tab-bar").get_by_role("button", name=t).click(timeout=5000))
        for h in HEADER:
            await step(f"header {h if isinstance(h, str) else h.pattern}", lambda h=h: pg.get_by_role("button", name=h).first.click(timeout=5000))
        for row in ME_ROWS:
            await home()

            async def open_row(row: str = row) -> None:
                await pg.get_by_role("button", name=re.compile(r"^Me\b")).first.click(timeout=5000)
                await pg.wait_for_timeout(800)
                el = pg.get_by_text(row, exact=True).first
                await el.scroll_into_view_if_needed(timeout=5000)
                await el.click(timeout=5000)
            await step(f"me {row}", open_row)
        for kind, ident in deep:
            await step(f"deep {kind}", lambda kind=kind, ident=ident: pg.goto(f"{base}/app/?open={kind}&id={ident}", wait_until="networkidle"))
        await b.close()
    return found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8001")
    ap.add_argument("--out", default="/tmp/rabbit-sweep")
    ap.add_argument("--chromium", default=os.environ.get("CHROMIUM") or None)
    ap.add_argument("--scheme", default="both", choices=["light", "dark", "both"])
    ap.add_argument("--deep", action="append", default=[], help="kind=id, e.g. person=pal")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    deep = [tuple(d.split("=", 1)) for d in a.deep if "=" in d]
    bad = False
    for sc in (["light", "dark"] if a.scheme == "both" else [a.scheme]):
        r = asyncio.run(sweep(a.base.rstrip("/"), a.out, a.chromium, sc, deep))  # type: ignore[arg-type]
        print(sc, json.dumps(r, indent=1))
        bad = bad or any(r.values())
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
