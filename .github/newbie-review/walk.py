# TEMPORARY CI walkthrough + audit for feat-newbie (removed before merge). Screens -> shots/nb2_*.png
import asyncio, json, os
from playwright.async_api import async_playwright
OUT = "shots"; os.makedirs(OUT, exist_ok=True)
report = {"miss": [], "errors": [], "overflow": [], "text": {}}

async def shot(pg, name, full=False):
    await pg.wait_for_timeout(900)
    await pg.screenshot(path=f"{OUT}/nb2_{name}.png", full_page=full)
    try:
        ov = await pg.evaluate("()=>{const w=innerWidth;return [...document.querySelectorAll('body *')].filter(e=>{const r=e.getBoundingClientRect();if(!(r.width>0&&r.right>w+1)||getComputedStyle(e).position==='fixed')return false;for(let a=e.parentElement;a;a=a.parentElement){if(/(auto|scroll|hidden|clip)/.test(getComputedStyle(a).overflowX))return false}return true}).slice(0,5).map(e=>e.tagName+'.'+(e.className||'').toString().slice(0,60)+' '+Math.round(e.getBoundingClientRect().right))}")
        if ov: report["overflow"].append({name: ov})
        report["text"][name] = (await pg.evaluate("()=>document.body.innerText"))[:1500]
    except Exception as e:
        report["errors"].append(f"{name}: {e}")

async def click(pg, *texts, role="button"):
    for t in texts:
        for how in ("role", "text"):
            try:
                loc = pg.get_by_role(role, name=t).first if how == "role" else pg.get_by_text(t, exact=True).first
                await loc.click(timeout=5000); return True
            except Exception:
                pass
    report["miss"].append("/".join(texts)); return False

async def me(pg):
    try: await pg.get_by_role("button", name="Me", exact=True).first.click(timeout=4000)
    except Exception: report["miss"].append("Me")
    await pg.wait_for_timeout(800)

async def scroll(pg, frac=1.0):
    await pg.evaluate("""(f)=>{const els=[...document.querySelectorAll('*')].filter(e=>e.scrollHeight>e.clientHeight+20&&/(auto|scroll)/.test(getComputedStyle(e).overflowY));
      const m=els.sort((a,b)=>(b.clientHeight*b.scrollHeight)-(a.clientHeight*a.scrollHeight))[0]; if(m) m.scrollTop=(m.scrollHeight-m.clientHeight)*f; else scrollTo(0,document.body.scrollHeight*f)}""", frac)
    await pg.wait_for_timeout(500)

async def tab(pg, name):
    try:
        await pg.locator("nav.tab-bar").get_by_role("button", name=name).first.click(timeout=4000)
    except Exception:
        report["miss"].append("tab " + name)

async def consent(pg):
    boxes = pg.locator("input[type=checkbox]")
    for i in range(await boxes.count()):
        try: await boxes.nth(i).check(timeout=1500)
        except Exception: pass
    await click(pg, "Agree and continue", "Continue", "I agree")

async def dismiss_tour(pg):
    for _ in range(8):
        if not await pg.get_by_role("dialog").count(): return
        if not await click(pg, "Skip tour", "Skip", "Got it", "Done", "Next"): return
        await pg.wait_for_timeout(300)

async def fresh(b):
    ctx = await b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True,
                              geolocation={"latitude": 39.7392, "longitude": -104.9903}, permissions=["geolocation"])
    pg = await ctx.new_page(); pg.on("pageerror", lambda e: report["errors"].append(str(e)))
    await pg.goto("http://localhost:8040/app/", wait_until="networkidle")
    await shot(pg, "fresh_01_consent"); await consent(pg)
    await shot(pg, "fresh_02_hello"); await click(pg, "Let's go")
    await shot(pg, "fresh_03_pick"); await click(pg, "Find things to do near me")
    await shot(pg, "fresh_04_area")
    await pg.fill("#wf-place", "80204"); await shot(pg, "fresh_04b_typed")
    await click(pg, "That's me"); await pg.wait_for_timeout(2500)
    if await pg.locator("#wf-place").count():
        await shot(pg, "fresh_04c_zip_error"); await click(pg, "Use my location"); await pg.wait_for_timeout(3000)
    await shot(pg, "fresh_05_area_done"); await click(pg, "Next")
    await shot(pg, "fresh_06_heard"); await click(pg, "A club or run club"); await pg.wait_for_timeout(800)
    await shot(pg, "fresh_07_done"); await click(pg, "See what's near me"); await pg.wait_for_timeout(1500)
    await shot(pg, "fresh_08_nearme"); await dismiss_tour(pg); await shot(pg, "fresh_08b_nearme_full", full=True)
    await tab(pg, "Today"); await dismiss_tour(pg); await shot(pg, "fresh_09_today"); await shot(pg, "fresh_09b_today_full", full=True)
    await tab(pg, "Plan"); await dismiss_tour(pg); await shot(pg, "fresh_10_plan")
    await tab(pg, "Friends"); await dismiss_tour(pg); await shot(pg, "fresh_11_friends")
    await click(pg, "People", role="radio"); await shot(pg, "fresh_11b_people")
    await tab(pg, "Progress"); await dismiss_tour(pg); await shot(pg, "fresh_12_progress")
    await tab(pg, "Today")
    await me(pg); await shot(pg, "fresh_13_me"); await scroll(pg); await shot(pg, "fresh_13b_me_bottom")
    if await click(pg, "Usage and traction"):
        await pg.wait_for_timeout(2000); await shot(pg, "fresh_14_usage")
        for k in (0.25, 0.5, 0.75, 1): await scroll(pg, k); await shot(pg, f"fresh_14_usage_{int(k*100)}")
    await pg.goto("http://localhost:8040/app/", wait_until="networkidle"); await dismiss_tour(pg)
    await click(pg, "Ask rabbt anything…"); await shot(pg, "fresh_15_chat")
    await pg.goto("http://localhost:8040/app/", wait_until="networkidle"); await dismiss_tour(pg)
    await click(pg, "Get a plan For a race or just to get fitter", "Get a plan"); await pg.wait_for_timeout(1200); await shot(pg, "fresh_16_get_plan")
    state = await ctx.storage_state(); await ctx.close(); return state

async def fresh_plan(b):
    """Second new person: 320 px, dark, picks a plan, skips the optional questions."""
    ctx = await b.new_context(viewport={"width": 320, "height": 640}, device_scale_factor=2, is_mobile=True, has_touch=True, color_scheme="dark")
    pg = await ctx.new_page(); pg.on("pageerror", lambda e: report["errors"].append(str(e)))
    await pg.goto("http://localhost:8041/app/", wait_until="networkidle")
    await consent(pg)
    await shot(pg, "plan320d_01_hello"); await click(pg, "Let's go")
    await shot(pg, "plan320d_02_pick"); await click(pg, "Something else"); await shot(pg, "plan320d_02b_more", full=True)
    await click(pg, "Get a training plan")
    await shot(pg, "plan320d_03_area"); await pg.fill("#wf-place", "Denver"); await shot(pg, "plan320d_03b_needs_state")
    await click(pg, "Not now")
    await shot(pg, "plan320d_04_heard"); await click(pg, "Skip")
    await shot(pg, "plan320d_05_done"); await click(pg, "Get a plan"); await pg.wait_for_timeout(1500)
    await shot(pg, "plan320d_06_setup"); await ctx.close()

async def audit(b, state):
    for w, h in ((320, 640), (390, 844), (430, 932)):
        for scheme in ("light", "dark"):
            ctx = await b.new_context(viewport={"width": w, "height": h}, device_scale_factor=1, is_mobile=True, has_touch=True,
                                      color_scheme=scheme, storage_state=state)
            pg = await ctx.new_page()
            await pg.goto("http://localhost:8040/app/", wait_until="networkidle"); await dismiss_tour(pg)
            for t in ("Today", "Near me", "Plan", "Friends", "Progress"):
                await tab(pg, t); await dismiss_tour(pg)
                n = t.replace(' ', ''); await shot(pg, f"audit_{w}_{scheme}_{n}"); await scroll(pg); await shot(pg, f"audit_{w}_{scheme}_{n}_end")
            await tab(pg, "Today"); await me(pg); await shot(pg, f"audit_{w}_{scheme}_Me"); await scroll(pg, 0.5); await shot(pg, f"audit_{w}_{scheme}_Me_mid"); await scroll(pg); await shot(pg, f"audit_{w}_{scheme}_Me_end")
            await ctx.close()

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        state = await fresh(b)
        await fresh_plan(b)
        await audit(b, state)
        await b.close()
    json.dump(report, open(f"{OUT}/report.json", "w"), indent=1)
asyncio.run(main())
