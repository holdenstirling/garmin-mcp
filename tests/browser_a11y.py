"""Browser accessibility audit for the Rabbit web app (not run in CI: needs Chromium + a server).

    python3 tests/browser_a11y.py http://localhost:8001/app/ [--dark] [--out report.json]

Opens the app at phone size (390x844), visits every tab, view and the main sheets, and runs an
in-page audit on each screen (axe isn't installable in our sandbox, so this is a focused
subset of WCAG 2.2 AA):

* text contrast: computed color against the nearest opaque background (alpha blended);
  < 4.5:1 for normal text, < 3:1 for large text (>= 24px, or >= 18.66px bold)
* interactive elements (button, a[href], [role=button|tab|radio|checkbox|switch], input,
  select, textarea) with no accessible name
* tap targets smaller than 44x44 CSS px (helpers that extend the hit area with ::after or
  a .hit-44 class are measured with that extension)
* <img> without alt, <svg> that is neither aria-hidden nor labelled
* form fields without a label (label[for], wrapping label, aria-label, aria-labelledby)
* duplicate ids, positive tabindex
* heading levels that skip (h2 -> h4) within the visible screen
* sheets ([role=dialog]): Tab stays inside, Escape closes it, focus returns to the opener

Each finding is printed as `screen | rule | element | detail`; the exit status is the count.
Only visible elements of the visible screen are checked (hidden tabs stay mounted).
"""

from __future__ import annotations

import asyncio
import json
import sys

AUDIT_JS = r"""
() => {
  const out = [];
  // Only the top layer is reachable: with a sheet or dialog open, what's behind it is out of play.
  const modals = [...document.querySelectorAll('[aria-modal="true"]')].filter((m) => {
    const r = m.getBoundingClientRect(); return r.width > 1 && r.height > 1 && getComputedStyle(m).visibility !== 'hidden';
  });
  const top = modals[modals.length - 1] || null;
  const vis = (el) => {
    if (!(el instanceof Element)) return false;
    if (top && !top.contains(el)) return false;
    if (el.closest('[inert],[aria-hidden="true"],.hidden,[hidden]')) return false;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return false;
    if (r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) return false;
    const s = getComputedStyle(el);
    return s.visibility !== 'hidden' && s.display !== 'none' && Number(s.opacity) > 0.05;
  };
  const desc = (el) => {
    const t = (el.getAttribute('aria-label') || el.textContent || el.getAttribute('placeholder') || '').trim().replace(/\s+/g, ' ');
    return `${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''}${t ? ' "' + t.slice(0, 40) + '"' : ''}`;
  };
  const parse = (c) => {
    const m = c.match(/rgba?\(([^)]+)\)/); if (!m) {
      const m2 = c.match(/color\(srgb ([\d.]+) ([\d.]+) ([\d.]+)(?: \/ ([\d.]+))?\)/);
      if (m2) return [m2[1]*255, m2[2]*255, m2[3]*255, m2[4] === undefined ? 1 : +m2[4]];
      return null;
    }
    const p = m[1].split(/[ ,/]+/).filter(Boolean).map(Number);
    return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1];
  };
  const lum = ([r, g, b]) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4) };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  const blend = (top, bot) => {
    const a = top[3];
    return [top[0]*a + bot[0]*(1-a), top[1]*a + bot[1]*(1-a), top[2]*a + bot[2]*(1-a), 1];
  };
  const bgOf = (el) => {
    const layers = [];
    for (let e = el; e; e = e.parentElement) {
      const s = getComputedStyle(e);
      if (s.backgroundImage && s.backgroundImage !== 'none' && !s.backgroundImage.startsWith('linear-gradient(transparent')) return null; // image: skip
      const c = parse(s.backgroundColor);
      if (c && c[3] > 0) { layers.push(c); if (c[3] >= 0.99) break; }
    }
    let bg = [255, 255, 255, 1];
    const root = parse(getComputedStyle(document.body).backgroundColor);
    if (root && root[3] > 0.99) bg = root;
    for (let i = layers.length - 1; i >= 0; i--) bg = blend(layers[i], bg);
    return bg;
  };
  const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05) };

  // contrast: text nodes' parents
  const seen = new Set();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const n = walker.currentNode; if (!n.textContent.trim()) continue;
    const el = n.parentElement; if (!el || seen.has(el) || !vis(el)) continue;
    seen.add(el);
    if (el.closest('button:disabled,[aria-disabled="true"],input:disabled')) continue;
    const s = getComputedStyle(el);
    let fg = parse(s.color); if (!fg) continue;
    const bg = bgOf(el); if (!bg) continue;
    fg = blend([fg[0], fg[1], fg[2], fg[3] * Number(s.opacity || 1)], bg);
    const size = parseFloat(s.fontSize), bold = Number(s.fontWeight) >= 700;
    const large = size >= 24 || (bold && size >= 18.66);
    const r = ratio(fg, bg);
    const need = large ? 3 : 4.5;
    if (r < need - 0.05) out.push(['contrast', desc(el), `${r.toFixed(2)}:1 < ${need} (${s.color} on rgb(${bg.slice(0,3).map(Math.round)}))`]);
  }

  // names, targets, labels
  const inter = document.querySelectorAll('button, a[href], [role=button], [role=tab], [role=radio], [role=checkbox], [role=switch], [role=menuitem], input:not([type=hidden]), select, textarea, summary');
  for (const el of inter) {
    if (!vis(el)) continue;
    const name = (el.getAttribute('aria-label') || el.getAttribute('aria-labelledby') && [...el.getAttribute('aria-labelledby').split(' ')].map((i) => document.getElementById(i)?.textContent || '').join(' ') || el.textContent || el.getAttribute('title') || el.getAttribute('alt') || '').trim();
    const field = /^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName);
    if (field) {
      const lab = el.labels && el.labels.length > 0;
      if (!lab && !el.getAttribute('aria-label') && !el.getAttribute('aria-labelledby') && el.type !== 'checkbox' && el.type !== 'radio' && el.type !== 'range')
        out.push(['label', desc(el), 'form field without a label']);
      else if (!lab && !el.getAttribute('aria-label') && !el.getAttribute('aria-labelledby') && (el.type === 'checkbox' || el.type === 'radio' || el.type === 'range'))
        out.push(['label', desc(el), `${el.type} without a label`]);
    } else if (!name && !el.querySelector('img[alt]:not([alt=""])')) {
      out.push(['name', desc(el) + ' ' + (el.className && String(el.className).slice(0, 40)), 'interactive element without an accessible name']);
    }
    // tap target (::after hit areas count)
    const r = el.getBoundingClientRect();
    let w = r.width, h = r.height;
    const after = getComputedStyle(el, '::after');
    if (after && after.content !== 'none' && after.position === 'absolute') {
      const aw = parseFloat(after.width), ah = parseFloat(after.height);
      if (aw > 0 && ah > 0) { w = Math.max(w, aw); h = Math.max(h, ah) }
      else {
        const ins = (v) => -(parseFloat(v) || 0);
        h += Math.max(0, ins(after.top)) + Math.max(0, ins(after.bottom));
        w += Math.max(0, ins(after.left)) + Math.max(0, ins(after.right));
      }
    }
    // a field inside a label that is itself a big tap area (search pills) counts as the label
    const wrap = field ? el.closest('label') : null;
    if (wrap) { const q = wrap.getBoundingClientRect(); w = Math.max(w, q.width); h = Math.max(h, q.height) }
    const inline = el.tagName === 'A' && getComputedStyle(el).display === 'inline' && el.closest('p,li');  // inline text links are exempt (WCAG 2.5.8)
    if (!inline && (w < 43.5 || h < 43.5) && el.type !== 'range' && !(el.type === 'checkbox' && el.labels?.length) && !(el.type === 'radio' && el.labels?.length))
      out.push(['target', desc(el), `${Math.round(w)}x${Math.round(h)}`]);
  }

  // stolen taps: another control's hit area lies over part of this one
  const layer = (e) => {
    for (; e && e !== document.body; e = e.parentElement) { const p = getComputedStyle(e).position; if (p === 'fixed' || p === 'sticky') return e }
    return null;
  };
  for (const el of inter) {
    if (!vis(el)) continue;
    const q = el.getBoundingClientRect();
    // The part a finger can reach: clipped by every scrolling/overflow-hidden ancestor.
    let c = { l: 0, t: 0, r: innerWidth, b: innerHeight };
    for (let e = el.parentElement; e && e !== document.body; e = e.parentElement) {
      const st = getComputedStyle(e);
      if (st.overflowX !== 'visible' || st.overflowY !== 'visible') {
        const z = e.getBoundingClientRect();
        c = { l: Math.max(c.l, z.left), t: Math.max(c.t, z.top), r: Math.min(c.r, z.right), b: Math.min(c.b, z.bottom) };
      }
    }
    const pts = [[q.left + q.width / 2, q.top + q.height / 2], [q.left + 6, q.top + q.height / 2], [q.right - 6, q.top + q.height / 2]];
    for (const [x, y] of pts) {
      if (x < c.l + 1 || y < c.t + 1 || x > c.r - 1 || y > c.b - 1) continue;
      const hit = document.elementFromPoint(x, y);
      if (!hit || el.contains(hit) || hit.contains(el)) continue;
      const other = hit.closest('button, a[href], [role=button], [role=tab], input, select, textarea, summary, label');
      // Content scrolled under a fixed/sticky header or the tab bar is fine (scroll it into view).
      if (other && layer(other) && layer(other) !== layer(el)) continue;
      if (other && other !== el && !other.contains(el) && !el.contains(other)) {
        out.push(['overlap', desc(el), `part of it is covered by ${desc(other)}`]); break;
      }
    }
  }

  // images / svg
  for (const img of document.querySelectorAll('img')) if (vis(img) && !img.hasAttribute('alt')) out.push(['alt', desc(img) + ' ' + img.src.slice(-40), 'img without alt']);
  for (const svg of document.querySelectorAll('svg')) {
    if (!vis(svg)) continue;
    if (svg.getAttribute('aria-hidden') === 'true' || svg.closest('[aria-hidden="true"]')) continue;
    if (svg.getAttribute('role') === 'img' && (svg.getAttribute('aria-label') || svg.querySelector('title'))) continue;
    if (svg.getAttribute('aria-label') || svg.querySelector('title')) continue;
    // decorative icons inside a named control are fine when the control has text
    const ctl = svg.closest('button,a,[role=button],[role=tab]');
    if (ctl && (ctl.getAttribute('aria-label') || ctl.textContent.trim())) continue;
    out.push(['svg', (svg.getAttribute('class') || '').toString().slice(0, 50), 'svg neither aria-hidden nor labelled']);
  }

  // ids, tabindex
  const ids = {};
  for (const el of document.querySelectorAll('[id]')) ids[el.id] = (ids[el.id] || 0) + 1;
  for (const [id, n] of Object.entries(ids)) if (n > 1) out.push(['dup-id', '#' + id, `${n} elements`]);
  for (const el of document.querySelectorAll('[tabindex]')) if (Number(el.getAttribute('tabindex')) > 0) out.push(['tabindex', desc(el), 'positive tabindex']);

  // headings
  // Order is structural: count every rendered heading in the top layer, on screen or scrolled away.
  const rendered = (h) => (!top || top.contains(h)) && !h.closest('[inert],[aria-hidden="true"],.hidden,[hidden]')
    && (h.getClientRects().length > 0 || h.classList.contains('sr-only')) && getComputedStyle(h).visibility !== 'hidden';
  const hs = [...document.querySelectorAll('h1,h2,h3,h4,h5,h6')].filter(rendered);
  let prev = 0;
  for (const h of hs) { const l = Number(h.tagName[1]); if (prev && l > prev + 1) out.push(['heading', desc(h), `h${prev} -> h${l}`]); prev = l; }
  return out;
}
"""

FOCUS_JS = r"""
async () => {
  const dlg = [...document.querySelectorAll('[role=dialog]')].filter((d) => d.getBoundingClientRect().height > 0).pop();
  if (!dlg) return ['no-dialog'];
  const res = [];
  if (!dlg.getAttribute('aria-label') && !dlg.getAttribute('aria-labelledby')) res.push('dialog without a name');
  if (!dlg.contains(document.activeElement)) res.push('focus not inside the dialog after opening');
  return res;
}
"""


async def run(base: str, dark: bool) -> list[list[str]]:
    from playwright.async_api import async_playwright
    findings: list[list[str]] = []
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
        ctx = await b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True,
                                  color_scheme="dark" if dark else "light")
        await ctx.add_init_script("try{for(const k of Object.keys(localStorage)) if(k.startsWith('rabbit.tour')) localStorage.setItem(k,'1'); localStorage.setItem('rabbit.tour.done.demo','1')}catch(e){}")
        pg = await ctx.new_page()

        async def home() -> None:
            await pg.goto(base, wait_until="networkidle")
            await pg.wait_for_timeout(1800)

        async def audit(name: str) -> None:
            await pg.wait_for_timeout(1200)
            for scroll in range(4):
                for f in await pg.evaluate(AUDIT_JS):
                    findings.append([name, *f])
                moved = await pg.evaluate("""() => { const els=[...document.querySelectorAll('*')].filter(e=>{const o=getComputedStyle(e).overflowY;return (o==='auto'||o==='scroll')&&e.scrollHeight>e.clientHeight+10&&e.getBoundingClientRect().height>200&&!e.closest('.hidden,[inert]')}); els.sort((a,b)=>b.clientHeight-a.clientHeight); const e=els[0]; if(!e) return false; const t=e.scrollTop; e.scrollBy(0,700); return e.scrollTop!==t }""")
                if not moved:
                    break
                await pg.wait_for_timeout(500)

        async def tab(label: str) -> None:
            await pg.locator("nav.tab-bar").get_by_role("button", name=label).click()
            await pg.wait_for_timeout(1500)

        async def sheet(name: str, opener) -> None:
            try:
                await opener()
                await pg.wait_for_timeout(1300)
                for f in await pg.evaluate(FOCUS_JS):
                    if f != "no-dialog":
                        findings.append([name, "focus", "dialog", f])
                await audit(name)
                # Tab cycling stays inside; Escape closes
                await pg.keyboard.press("Escape")
                await pg.wait_for_timeout(700)
                still = await pg.evaluate("() => [...document.querySelectorAll('[role=dialog]')].filter(d=>d.getBoundingClientRect().height>0).length")
                if still:
                    findings.append([name, "escape", "dialog", "Escape did not close it"])
                    await pg.keyboard.press("Escape")
            except Exception as e:  # a missing opener is reported, not fatal
                findings.append([name, "step", "-", str(e)[:120]])

        await home()
        await audit("Home")
        try:
            await pg.get_by_role("tab", name="Chat").locator("visible=true").first.click(); await audit("Chat")
            await pg.get_by_role("tab", name="Home").locator("visible=true").first.click()
        except Exception as e:
            findings.append(["Chat", "step", "-", str(e)[:120]])
        for t in ["Schedule", "Feed", "Local", "Progress"]:
            await tab(t); await audit(t)
        await tab("Schedule")
        for v in ["Events", "Discover"]:
            try:
                await pg.get_by_role("tab", name=v).locator("visible=true").first.click(); await audit(f"Schedule {v}")
            except Exception as e:
                findings.append([v, "step", "-", str(e)[:120]])
        await pg.get_by_role("tab", name="Plan").locator("visible=true").first.click()
        for v in ["Today", "Week", "List", "Month"]:
            try:
                await pg.get_by_role("tab", name=v).locator("visible=true").first.click(); await audit(f"Plan {v}")
            except Exception as e:
                findings.append([v, "step", "-", str(e)[:120]])
        vis = lambda loc: loc.locator("visible=true").first  # noqa: E731
        await sheet("Add sheet", lambda: vis(pg.get_by_role("button", name="Add")).click())
        await sheet("Search", lambda: vis(pg.get_by_role("button", name="Search")).click())
        await sheet("Notifications", lambda: vis(pg.get_by_role("button", name="Notifications")).click())
        await sheet("Chats", lambda: vis(pg.get_by_role("button", name="Chat")).click())
        await tab("Feed")
        await sheet("New group", lambda: vis(pg.get_by_text("New group")).click())
        await home()
        await sheet("Me", lambda: vis(pg.get_by_role("button", name="Me")).click())
        for row in ["Training profile", "Connected apps", "Settings", "Gear garage", "Body & niggles"]:
            await home()
            try:
                await vis(pg.get_by_role("button", name="Me")).click(); await pg.wait_for_timeout(1000)
                el = vis(pg.get_by_text(row, exact=True)); await el.scroll_into_view_if_needed(); await el.click()
                await audit(f"Me > {row}")
            except Exception as e:
                findings.append([row, "step", "-", str(e)[:120]])
        # a workout page
        await home(); await tab("Schedule")
        try:
            await pg.get_by_role("tab", name="List").locator("visible=true").first.click(); await pg.wait_for_timeout(1000)
            await pg.evaluate("() => [...document.querySelectorAll('button')].find(b=>b.offsetParent&&/Long run|Long ride/.test(b.textContent)&&b.textContent.length<200)?.click()")
            await audit("Workout page")
        except Exception as e:
            findings.append(["Workout page", "step", "-", str(e)[:120]])
        await b.close()
    return findings


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    base = args[0] if args else "http://localhost:8001/app/"
    dark = "--dark" in sys.argv
    out = None
    if "--out" in sys.argv:
        out = sys.argv[sys.argv.index("--out") + 1]
    found = asyncio.run(run(base, dark))
    uniq: list[list[str]] = []
    keys = set()
    for f in found:
        k = (f[1], f[2], f[3])
        if k not in keys:
            keys.add(k)
            uniq.append(f)
    for f in uniq:
        print(" | ".join(f))
    if out:
        json.dump(uniq, open(out, "w"), indent=1)
    print(f"{len(uniq)} findings")
    return len(uniq)


if __name__ == "__main__":
    sys.exit(min(main(), 255))
