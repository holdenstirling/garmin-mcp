"""A club's public link page: ``/app/c/<slug>`` (a link that works in an Instagram bio).

Server-rendered, no JavaScript, no login. It lists the club's public runs (``clubs.public_page``):
when, where (a map link when the organizer dropped a pin), pace groups, beginner / walk /
women-only labels, spots left, the cost note and the waiver. Anyone can RSVP with a name and an
email (contact for the organizers only, never shown to other people) or open rabbt to RSVP with
one tap. A run shared with ``?t=<token>`` (its private link) shows even when it isn't public.

The RSVP form posts back to the same origin (``form-action 'self'``); the confirmation page has
an add-to-calendar file and a cancel link with a secret (only its hash is stored).
"""

from __future__ import annotations

import html
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote

from . import legal as _legal

LEVEL_WORD = {"all": "All levels", "easy": "Easy pace", "moderate": "Moderate pace", "fast": "Fast pace"}
HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff",
           "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src 'self'; "
                                      "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"}


def _e(v: Any) -> str:
    return html.escape(str(v if v is not None else ""), quote=True)


def when_text(iso: str | None, repeat: str | None = None) -> str:
    if not iso:
        return ""
    d = datetime.fromisoformat(iso)
    hour = d.strftime("%I:%M %p").lstrip("0")
    day = d.strftime("%a, %b ") + str(d.day)
    return f"{day} at {hour}" + (f" (every {d.strftime('%A')})" if repeat == "weekly" else "")


def tags(r: dict[str, Any]) -> list[str]:
    out = []
    if r.get("beginner"):
        out.append("Beginner friendly, no one left behind")
    if r.get("walk"):
        out.append("Walkers welcome")
    if r.get("women"):
        out.append("Women only")
    if r.get("level") and r["level"] != "all":
        out.append(LEVEL_WORD.get(r["level"], ""))
    return [t for t in out if t]


def _style() -> str:
    return """<style>:root{color-scheme:light dark;--bg:#f6f1e8;--card:#fffdf8;--text:#1f2a24;--muted:#56625a;--brand:#1a3a2a;--accent:#2f6b4a;--line:#ded6c6;--danger:#ba1e1e}
@media (prefers-color-scheme:dark){:root{--bg:#151816;--card:#1d211f;--text:#eef1ec;--muted:#a3ada6;--brand:#cfe7d6;--accent:#8fd0a8;--line:#2c322e;--danger:#e86f6f}}
*{box-sizing:border-box}body{margin:0;font:17px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;background:var(--bg);color:var(--text)}
main{max-width:620px;margin:0 auto;padding:20px max(16px,env(safe-area-inset-left)) 48px}
.brand{display:flex;align-items:center;gap:8px;color:var(--brand);font-weight:700;font-size:15px}
h1{font:400 32px/1.15 Georgia,"Times New Roman",serif;color:var(--brand);margin:16px 0 4px}
.sub{color:var(--muted);margin:0 0 4px}.card{background:var(--card);border:1px solid var(--line);border-radius:20px;padding:20px;margin-top:16px}
h2{font-size:20px;line-height:1.25;margin:0 0 4px}.when{color:var(--accent);font-weight:600;margin:0 0 2px}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}.chips span{background:color-mix(in srgb,var(--accent) 14%,transparent);border-radius:999px;padding:6px 12px;font-size:15px}
.groups{margin:10px 0;padding:0;list-style:none}.groups li{padding:8px 0;border-top:1px solid var(--line);display:flex;justify-content:space-between;gap:12px}
.note{margin:8px 0 0}.muted{color:var(--muted);font-size:15px}a{color:var(--accent)}
details{margin-top:12px;border-top:1px solid var(--line);padding-top:10px}summary{cursor:pointer;font-weight:600}
.waiver{white-space:pre-wrap;font-size:15px;color:var(--muted)}
form{display:grid;gap:12px;margin-top:16px}label{display:grid;gap:6px;font-weight:600;font-size:15px}
input[type=text],input[type=email]{font:inherit;font-size:17px;padding:12px 14px;border-radius:12px;border:1px solid var(--line);background:var(--bg);color:var(--text)}
.check{display:flex;gap:10px;align-items:flex-start;font-weight:400}.check input{width:24px;height:24px;margin:0}
button,.cta{display:block;width:100%;text-align:center;font:inherit;font-weight:600;border:0;border-radius:12px;padding:14px;background:var(--accent);color:#fff;text-decoration:none;cursor:pointer}
@media (prefers-color-scheme:dark){button,.cta{color:#0f1a14}}.ghost{background:transparent;color:var(--accent);border:1px solid var(--line)}
.hp{position:absolute;left:-9999px}.err{color:var(--danger);font-weight:600}.ok{color:var(--accent);font-weight:600}
footer{margin-top:24px;color:var(--muted);font-size:14px}</style>"""


def _head(title: str, desc: str, url: str, og_image: str) -> str:
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{_e(title)} · rabbt</title><meta name="description" content="{_e(desc)}">
<meta property="og:type" content="website"><meta property="og:site_name" content="rabbt">
<meta property="og:title" content="{_e(title)}"><meta property="og:description" content="{_e(desc)}">
<meta property="og:url" content="{_e(url)}"><meta property="og:image" content="{_e(og_image)}">
<meta name="twitter:card" content="summary_large_image"><meta name="theme-color" content="#1a3a2a">{_style()}</head>"""


def _run_card(slug: str, r: dict[str, Any], *, token: str | None, error: str | None, form: dict[str, str]) -> str:
    bits = [f"<p class=when>{_e(when_text(r.get('next'), r.get('repeat')))}</p>", f"<h2>{_e(r.get('title'))}</h2>"]
    where = _e(r.get("where"))
    if r.get("lat") is not None and r.get("lng") is not None:
        osm = f"https://www.openstreetmap.org/?mlat={r['lat']}&mlon={r['lng']}#map=17/{r['lat']}/{r['lng']}"
        where = f'{where} · <a href="{_e(osm)}" rel="noopener">Map</a>'
    bits.append(f"<p class=sub>{where}</p>")
    chips = tags(r)
    if r.get("paid"):
        chips.append(str(r["paid"]))
    if chips:
        bits.append("<div class=chips>" + "".join(f"<span>{_e(c)}</span>" for c in chips) + "</div>")
    groups = r.get("groups") or []
    if groups:
        bits.append("<ul class=groups>" + "".join(
            f"<li><span>{_e(g.get('label'))}</span><span class=muted>{_e(g.get('pace'))}</span></li>" for g in groups) + "</ul>")
    elif r.get("pace"):
        bits.append(f"<p class=muted>Pace: {_e(r['pace'])}</p>")
    if r.get("notes"):
        bits.append(f"<p class=note>{_e(r['notes'])}</p>")
    cap = r.get("capacity")
    if cap:
        left = r.get("spots_left") or 0
        bits.append(f"<p class=muted>{left} of {cap} spots left" + (f", {r['waitlist']} on the waitlist" if r.get("waitlist") else "") + "</p>")
    elif r.get("count"):
        bits.append(f"<p class=muted>{r['count']} going</p>")
    if r.get("waiver"):
        bits.append(f"<details><summary>Waiver</summary><p class=waiver>{_e(r['waiver'])}</p></details>")
    action = f"/app/c/{quote(slug)}/r/{quote(str(r['id']))}/rsvp" + (f"?t={quote(token)}" if token else "")
    full = cap and not r.get("spots_left")
    label = "Join the waitlist" if full else "I'm going"
    waiver = ("<label class=check><input type=checkbox name=waiver value=yes required> "
              "<span>I've read and accept the waiver.</span></label>") if r.get("waiver") else ""
    err = f'<p class=err role=alert>{_e(error)}</p>' if error else ""
    bits.append(f"""<form method=post action="{_e(action)}">{err}
<label>Your first name<input type=text name=name maxlength=40 autocomplete=given-name required value="{_e(form.get('name', ''))}"></label>
<label>Email (only the organizers see it)<input type=email name=email maxlength=120 autocomplete=email required value="{_e(form.get('email', ''))}"></label>
{waiver}<input class=hp type=text name=website tabindex=-1 autocomplete=off aria-hidden=true>
<button type=submit>{label}</button></form>
<p class=muted style="margin-top:10px">Have rabbt? <a href="/app/?club_run={_e(r['id'])}&amp;club={_e(slug)}">RSVP in the app</a> with one tap.</p>""")
    return f'<section class=card id="run-{_e(r["id"])}">' + "".join(bits) + "</section>"


def render_page(page: dict[str, Any], *, base: str, token: str | None = None, error: str | None = None,
                error_run: str | None = None, form: dict[str, str] | None = None) -> str:
    slug = str(page["slug"])
    url = f"{base}/app/c/{slug}"
    place = ", ".join(x for x in (page.get("city"), page.get("state")) if x)
    runs = page.get("runs") or []
    desc = (page.get("description") or f"{page['name']} on rabbt") + (f" · {place}" if place else "")
    cards = "".join(_run_card(slug, r, token=token, error=error if r["id"] == error_run else None,
                              form=form if r["id"] == error_run and form else {}) for r in runs)
    if not runs:
        cards = "<section class=card><p>No runs posted right now. Check back soon, or open rabbt to follow the club.</p></section>"
    members = page.get("members") or 0
    return f"""{_head(page['name'], desc, url, base + '/app/og-image.png')}
<body><main><div class=brand><span aria-hidden="true">🐇</span>rabbt</div>
<h1>{_e(page.get('emoji') or '')} {_e(page['name'])}</h1>
<p class=sub>{_e(place)}{' · ' if place else ''}{members} member{'s' if members != 1 else ''}</p>
{f"<p class=note>{_e(page['description'])}</p>" if page.get('description') else ''}
{cards}
<a class="cta ghost" style="margin-top:20px" href="/app/">Open rabbt</a>
<footer>Run at your own pace and your own risk. {_legal.FOOTER}</footer></main></body></html>"""


def render_done(page: dict[str, Any], run: dict[str, Any], result: dict[str, Any], *, base: str) -> str:
    slug = str(page["slug"])
    status = result.get("status")
    head = "You're on the waitlist" if status == "waitlist" else "You're going"
    msg = ("We'll keep your spot in line. If someone drops out, you move up. The organizers can reach you by email."
           if status == "waitlist" else "See you there. The organizers can reach you by email if anything changes.")
    ics = f"/app/c/{quote(slug)}/r/{quote(str(run['id']))}.ics"
    cancel = result.get("cancel")
    cancel_html = ""
    if cancel:
        cancel_url = f"/app/c/{quote(slug)}/r/{quote(str(run['id']))}/cancel?s={quote(cancel)}"
        cancel_html = (f'<p class=muted>Can\'t make it? <a href="{_e(cancel_url)}">Cancel your spot</a>. '
                       "Save this page: the link only works from here.</p>")
    return f"""{_head(head, run.get('title') or page['name'], base + '/app/c/' + slug, base + '/app/og-image.png')}
<body><main><div class=brand><span aria-hidden="true">🐇</span>rabbt</div>
<h1>{_e(head)}</h1><section class=card><p class=when>{_e(when_text(run.get('next')))}</p><h2>{_e(run.get('title'))}</h2>
<p class=sub>{_e(run.get('where'))}</p><p class=ok>{_e(msg)}</p>
<a class=cta href="{_e(ics)}">Add to calendar</a>{cancel_html}</section>
<a class="cta ghost" style="margin-top:16px" href="/app/c/{_e(slug)}">Back to {_e(page['name'])}</a>
<footer>{_legal.FOOTER}</footer></main></body></html>"""


def render_message(title: str, text: str, *, slug: str | None = None) -> str:
    back = f'<a class="cta ghost" href="/app/c/{_e(slug)}">Back to the club</a>' if slug else ""
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>{_e(title)} · rabbt</title>{_style()}</head><body><main><div class=brand><span aria-hidden="true">🐇</span>rabbt</div>
<h1>{_e(title)}</h1><section class=card><p>{_e(text)}</p></section>{back}<footer>{_legal.FOOTER}</footer></main></body></html>"""


def ics(run: dict[str, Any], club_name: str, url: str) -> str:
    start = datetime.fromisoformat(str(run["next"]))
    end = start + timedelta(hours=1, minutes=30)

    def esc(s: Any) -> str:
        return str(s or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
    rule = f"RRULE:FREQ=WEEKLY\r\n" if run.get("repeat") == "weekly" else ""
    return ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//rabbt//club run//EN\r\nBEGIN:VEVENT\r\n"
            f"UID:{run['id']}-{start:%Y%m%d}@rabbit\r\nDTSTAMP:{datetime.utcnow():%Y%m%dT%H%M%SZ}\r\n"
            f"DTSTART:{start:%Y%m%dT%H%M%S}\r\nDTEND:{end:%Y%m%dT%H%M%S}\r\n{rule}"
            f"SUMMARY:{esc(run.get('title'))} ({esc(club_name)})\r\nLOCATION:{esc(run.get('where'))}\r\n"
            f"DESCRIPTION:{esc(url)}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")


__all__ = ["HEADERS", "ics", "render_done", "render_message", "render_page", "tags", "when_text"]
