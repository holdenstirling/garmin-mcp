"""Share by text: public read-only links for one thing (``/app/l/<token>``).

An athlete shares a planned workout, a recorded workout, an event, a club or an invite to
Rabbit with anyone (Messages, WhatsApp, email...). The link opens a small server-rendered page
(no app, no login, no JavaScript) with Open Graph tags so Messages shows a preview.

Privacy, decided at share time and frozen into a *snapshot* of safe fields:
* planned workout: title, date/time, sport, duration/distance in the sharer's units, steps in
  plain words with pace / power / swim-pace / cadence ranges and effort; heart-rate ranges only
  when the sharer turns on "include heart rate";
* recorded workout: sport, distance, time, pace, elevation, lap splits (distance + time); never
  heart rate unless included, never location / maps / coordinates; workouts imported from other
  apps (Oura...) never include heart rate at all;
* event: name, date/time, repeat text, neighborhood (never a street address), sport;
* club: public clubs only (a private club's link needs the owner/admin to include the code);
* invite: the sharer's first name plus a join link (only people who can invite get one).

Tokens: random 24 bytes; only a SHA-256 is stored (per-user ``sharelinks`` doc for the list +
global ``sharelinks-index`` hash -> user/link id). Revoking deletes both, so the URL 404s at once.
At most ``MAX_LINKS`` per person (oldest dropped) and ``CREATES_PER_DAY`` new links a day.
"""

from __future__ import annotations

import hashlib
import html
import secrets
import time
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

TOKEN_BYTES = 24
MAX_LINKS = 200
CREATES_PER_DAY = 60
KINDS = ("workout", "activity", "event", "club", "invite")
KM_PER_MI = 1.609344
M_PER_YD = 0.9144
SPORT_WORD = {"run": "run", "bike": "ride", "swim": "swim", "brick": "brick", "strength": "strength session",
              "walk": "walk", "hike": "hike", "trail": "trail run", "rest": "rest day"}
SPORT_EMOJI = {"run": "🏃", "bike": "🚴", "swim": "🏊", "brick": "🔁", "strength": "💪", "walk": "🚶", "hike": "🥾"}


class ShareError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


# ------------------------------------------------------------------ storage --
class ShareLinks:
    def __init__(self, store: Any, *, clock: Callable[[], float] = time.time) -> None:
        self._s = store
        self._clock = clock

    def _mine(self, uid: str) -> Any:
        return self._s.user_doc(uid, "sharelinks")

    def _index(self) -> Any:
        return self._s.global_doc("sharelinks-index")

    def create(self, uid: str, kind: str, ref: str, snap: dict[str, Any]) -> tuple[str, str]:
        """A new link (token shown once) for one item. Returns (token, link id)."""
        if kind not in KINDS:
            raise ShareError("kind")
        token = secrets.token_urlsafe(TOKEN_BYTES)
        h = _hash(token)
        lid = secrets.token_hex(6)
        now = int(self._clock())
        day = datetime.fromtimestamp(now).strftime("%Y-%m-%d")
        dropped: list[str] = []

        def put(d: dict[str, Any]) -> None:
            rate = d.setdefault("rate", {})
            if rate.get("day") != day:
                rate.clear()
                rate.update(day=day, n=0)
            if rate["n"] >= CREATES_PER_DAY:
                raise ShareError("That's a lot of links today. Try again tomorrow.", 429)
            rate["n"] += 1
            links = d.setdefault("links", {})
            links[lid] = {"hash": h, "kind": kind, "ref": str(ref)[:80], "title": str(snap.get("title") or "")[:120],
                          "snap": snap, "created": now, "views": 0}
            while len(links) > MAX_LINKS:
                old = min(links, key=lambda k: links[k]["created"])
                dropped.append(links.pop(old)["hash"])
        self._mine(uid).update(put)

        def idx(d: dict[str, Any]) -> None:
            for x in dropped:
                d.pop(x, None)
            d[h] = [uid, lid]
        self._index().update(idx)
        return token, lid

    def list(self, uid: str) -> list[dict[str, Any]]:
        links = self._mine(uid).load().get("links") or {}
        return sorted(({"id": k, "kind": v["kind"], "title": v.get("title") or "", "created": v["created"],
                        "views": int(v.get("views") or 0)} for k, v in links.items()),
                      key=lambda x: -x["created"])

    def revoke(self, uid: str, lid: str) -> bool:
        gone: dict[str, Any] = {}

        def drop(d: dict[str, Any]) -> None:
            rec = (d.get("links") or {}).pop(lid, None)
            if rec:
                gone.update(rec)
        self._mine(uid).update(drop)
        if gone.get("hash"):
            self._index().update(lambda d: d.pop(gone["hash"], None))
        return bool(gone)

    def revoke_ref(self, uid: str, kind: str, ref: str) -> int:
        """Turn off every link to one item (e.g. the item was deleted)."""
        hashes: list[str] = []

        def drop(d: dict[str, Any]) -> None:
            links = d.get("links") or {}
            for k in [k for k, v in links.items() if v["kind"] == kind and v["ref"] == str(ref)]:
                hashes.append(links.pop(k)["hash"])
        self._mine(uid).update(drop)
        if hashes:
            self._index().update(lambda d: [d.pop(x, None) for x in hashes])
        return len(hashes)

    def resolve(self, token: str) -> tuple[str, dict[str, Any]] | None:
        """(owner, link record) for a live token; counts the view."""
        if not isinstance(token, str) or not 20 <= len(token) <= 64:
            return None
        hit = self._index().load().get(_hash(token))
        if not hit:
            return None
        uid, lid = hit[0], hit[1]
        rec: dict[str, Any] = {}

        def view(d: dict[str, Any]) -> None:
            r = (d.get("links") or {}).get(lid)
            if r and secrets.compare_digest(r.get("hash", ""), _hash(token)):
                r["views"] = int(r.get("views") or 0) + 1
                rec.update(r)
        self._mine(uid).update(view)
        return (uid, rec) if rec else None

    # The sharer's reusable "Join Rabbit" invite for these pages (only for people who can invite).
    def invite_token(self, uid: str, make: Callable[[], tuple[str, int]]) -> str:
        """``make()`` -> (access invite token, expires ts). Reused until a week before it expires."""
        now = int(self._clock())
        cur = self._mine(uid).load().get("invite") or {}
        if cur.get("token") and int(cur.get("expires") or 0) > now + 7 * 86400:
            return str(cur["token"])
        token, expires = make()
        self._mine(uid).update(lambda d: d.__setitem__("invite", {"token": token, "expires": expires}))
        return token


# ------------------------------------------------------------- formatting --
def _first(name: str | None) -> str:
    return (str(name or "").strip().split(" ")[0] or "A friend")[:40]


def fmt_minutes(m: float | None) -> str:
    if not m:
        return ""
    m = round(m)
    return f"{m // 60}h {m % 60:02d}m" if m >= 60 else f"{m} min"


def fmt_seconds(s: float | None) -> str:
    if not s:
        return ""
    s = round(s)
    h, rem = divmod(s, 3600)
    mm, ss = divmod(rem, 60)
    return f"{h}:{mm:02d}:{ss:02d}" if h else f"{mm}:{ss:02d}"


def fmt_dist(km: float | None, sport: str, imperial: bool) -> str:
    if not km:
        return ""
    if sport == "swim":
        m = km * 1000
        return f"{round(m / M_PER_YD):,} yd" if imperial else f"{round(m):,} m"
    v = km / KM_PER_MI if imperial else km
    return f"{v:.1f} {'mi' if imperial else 'km'}"


def fmt_pace(sec_per_km: float | None, imperial: bool) -> str:
    if not sec_per_km:
        return ""
    s = round(sec_per_km * (KM_PER_MI if imperial else 1))
    return f"{s // 60}:{s % 60:02d}/{'mi' if imperial else 'km'}"


def fmt_swim(sec_per_100m: float | None, imperial: bool) -> str:
    if not sec_per_100m:
        return ""
    s = round(sec_per_100m * (M_PER_YD if imperial else 1))
    return f"{s // 60}:{s % 60:02d}/100{'yd' if imperial else 'm'}"


def _day_label(d: str | None, t: str | None = None) -> str:
    try:
        x = date.fromisoformat(str(d)[:10])
    except ValueError:
        return ""
    out = x.strftime("%a %b %-d")
    if t and len(t) == 5:
        hh, mm = int(t[:2]), int(t[3:])
        out += f" · {(hh % 12) or 12}:{mm:02d} {'AM' if hh < 12 else 'PM'}"
    return out


def _step_targets(st: dict[str, Any], imperial: bool, include_hr: bool) -> str:
    bits = []
    if st.get("pace"):
        bits.append(f"{fmt_pace(st['pace'][0], imperial).split('/')[0]}-{fmt_pace(st['pace'][1], imperial)}")
    if st.get("power"):
        bits.append(f"{st['power'][0]}-{st['power'][1]} W")
    if st.get("swim"):
        bits.append(f"{fmt_swim(st['swim'][0], imperial).split('/')[0]}-{fmt_swim(st['swim'][1], imperial)}")
    if include_hr and st.get("hr"):
        bits.append(f"{st['hr'][0]}-{st['hr'][1]} bpm")
    if st.get("cadence"):
        bits.append(f"{st['cadence'][0]}-{st['cadence'][1]} {'spm' if st['cadence'][0] >= 120 else 'rpm'}")
    if st.get("rpe"):
        bits.append(f"effort {st['rpe']}/10")
    return " · ".join(bits)


def _step_len(st: dict[str, Any], sport: str, imperial: bool) -> str:
    if st.get("meters") and sport == "swim":
        return fmt_dist(st["meters"] / 1000, "swim", imperial)
    return fmt_minutes(_num(st.get("minutes")))


def _flat_steps(steps: list[dict[str, Any]], sport: str, imperial: bool, include_hr: bool) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for st in steps or []:
        if st.get("type") == "repeat":
            inner = _flat_steps(st.get("steps") or [], sport, imperial, include_hr)
            out.append({"label": f"{int(st.get('reps') or 1)}×", "text": " + ".join(f"{x['text']} {x['label'].lower()}".strip() for x in inner),
                        "targets": inner[0]["targets"] if inner else ""})
            continue
        out.append({"label": str(st.get("label") or "Steady"), "text": _step_len(st, sport, imperial),
                    "targets": _step_targets(st, imperial, include_hr)})
    return out[:24]


# --------------------------------------------------------------- snapshots --
def planned_snap(s: dict[str, Any], day: str, item: dict[str, Any] | None, *, who: str, imperial: bool,
                 include_hr: bool = False) -> dict[str, Any]:
    """A planned plan session. ``item`` is the calendar view entry (targets, km, note)."""
    item = item or {}
    sport = str(s.get("sport") or "other")
    tg = item.get("targets") or {}
    km = sum(v for v in (item.get("km") or {}).values() if isinstance(v, int | float)) or None
    steps: list[dict[str, str]] = []
    if tg.get("legs"):
        for lg in tg["legs"]:
            steps.append({"label": str(lg.get("sport") or "").title(), "text": "", "targets": ""})
            steps += _flat_steps(lg.get("steps") or [], str(lg.get("sport")), imperial, include_hr)
    elif tg.get("steps"):
        steps = _flat_steps(tg["steps"], sport, imperial, include_hr)
    note = item.get("note") or {}
    summ = tg.get("summary") or {}
    facts = [x for x in (fmt_minutes(_num(summ.get("minutes")) or _num(s.get("minutes"))),
                         fmt_dist(km, sport, imperial),
                         fmt_pace(_num(summ.get("run_pace")), imperial) and f"avg {fmt_pace(_num(summ.get('run_pace')), imperial)}") if x]
    return {"kind": "workout", "who": _first(who), "title": str(s.get("title") or "Workout")[:80], "sport": sport,
            "when": _day_label(day, s.get("time")), "date": day, "facts": facts, "steps": steps,
            "why": str(note.get("why") or note.get("line") or "")[:400], "hr": bool(include_hr)}


def activity_snap(view: dict[str, Any], *, who: str, imperial: bool, include_hr: bool = False) -> dict[str, Any]:
    """A recorded workout from ``activitypage.build_view`` / ``build_imported``."""
    n = view.get("numbers") or {}
    sport = str(view.get("sport") or "other")
    garmin = view.get("source") == "garmin"
    hr_ok = include_hr and garmin  # imported (Oura...) workouts never share heart rate
    facts = [fmt_dist(_num(n.get("km")), sport, imperial), fmt_seconds(_num(n.get("moving_s"))),
             fmt_pace(_num(n.get("pace_s_per_km")), imperial) if sport in ("run", "walk", "hike") else "",
             fmt_swim(_num(n.get("pace_s_per_100m")), imperial) if sport == "swim" else "",
             (f"{(n['speed_kmh'] / KM_PER_MI if imperial else n['speed_kmh']):.1f} {'mph' if imperial else 'km/h'}"
              if sport == "bike" and _num(n.get("speed_kmh")) else ""),
             (f"{round(n['elevation_gain_m'] * 3.28084):,} ft climb" if imperial else f"{round(n['elevation_gain_m']):,} m climb")
             if _num(n.get("elevation_gain_m")) else ""]
    if hr_ok and _num(n.get("avg_hr")):
        facts.append(f"avg {round(n['avg_hr'])} bpm")
    laps = []
    for lp in (view.get("laps") or [])[:30]:
        row = {"n": int(lp.get("n") or len(laps) + 1), "dist": fmt_dist(_num(lp.get("km")), sport, imperial),
               "time": fmt_seconds(_num(lp.get("s"))),
               "pace": fmt_pace(_num(lp.get("pace_s_per_km")), imperial) if sport in ("run", "walk", "hike") else ""}
        if hr_ok and _num(lp.get("hr")):
            row["hr"] = f"{round(lp['hr'])} bpm"
        laps.append(row)
    return {"kind": "activity", "who": _first(who), "title": str(view.get("name") or "Workout")[:80], "sport": sport,
            "when": _day_label(view.get("start")), "date": str(view.get("start") or "")[:10],
            "facts": [f for f in facts if f], "laps": laps, "hr": bool(hr_ok),
            "source": "Garmin" if garmin else str(view.get("source") or "").title()}


def event_snap(ev: dict[str, Any], *, who: str) -> dict[str, Any]:
    where = str(ev.get("neighborhood") or "").strip() or str(ev.get("location") or "").split(",")[0].strip()
    facts = [x for x in (ev.get("repeat_text") or "", str(ev.get("distance") or ""),
                         str(ev.get("activity_label") or ev.get("activity") or "").replace("_", " ").capitalize()) if x]
    return {"kind": "event", "who": _first(who), "title": str(ev.get("name") or "Event")[:120],
            "when": _day_label(ev.get("date"), ev.get("time")), "date": str(ev.get("date") or ""),
            "where": where[:80], "facts": facts, "race": ev.get("type") == "race"}


def club_snap(c: dict[str, Any], *, who: str, code: str | None = None) -> dict[str, Any]:
    city = ", ".join(x for x in (c.get("city"), c.get("state")) if x)
    return {"kind": "club", "who": _first(who), "title": str(c.get("name") or "Club")[:80],
            "sport": str(c.get("sport") or ""), "where": city, "about": str(c.get("description") or "")[:300],
            "members": int(c.get("members") or 0), "code": code or None,
            "join": "Ask to join in Rabbit" if c.get("privacy") == "approval" else "Join in Rabbit"}


def invite_snap(*, who: str) -> dict[str, Any]:
    return {"kind": "invite", "who": _first(who), "title": f"{_first(who)} invited you to Rabbit"}


def default_text(snap: dict[str, Any]) -> str:
    """The friendly message that goes with the link (editable before sending)."""
    k, who, title = snap.get("kind"), snap.get("who") or "I", snap.get("title") or ""
    when = (snap.get("when") or "").split(" · ")[0]
    facts = ", ".join((snap.get("facts") or [])[:2])
    if k == "workout":
        return f"{who}'s {title.lower()} {when}: {facts}. Join me?".replace(" : ", ": ").replace(":.", ".")
    if k == "activity":
        return f"Just did a {title.lower() if len(title) < 30 else SPORT_WORD.get(snap.get('sport', ''), 'workout')}: {facts}."
    if k == "event":
        return (f"I'm racing {title} {when}. Follow along!" if snap.get("race")
                else f"Join me for {title} {when}?")
    if k == "club":
        return f"Come run with {title}! Here's the club on Rabbit."
    return "Join me on Rabbit, the training app I use. Here's my invite:"


# ------------------------------------------------------------------- page --
def _e(v: Any) -> str:
    return html.escape(str(v if v is not None else ""), quote=True)


def _description(snap: dict[str, Any]) -> str:
    bits = [snap.get("when") or "", *(snap.get("facts") or [])[:3], snap.get("where") or ""]
    return " · ".join(b for b in bits if b)[:200] or "Shared from Rabbit"


def render(snap: dict[str, Any], *, url: str, og_image: str, cta_url: str, cta_label: str) -> str:
    k = snap.get("kind")
    emoji = SPORT_EMOJI.get(str(snap.get("sport") or ""), "🐇")
    title = snap.get("title") or "Rabbit"
    head_line = {"workout": f"{snap.get('who')}'s planned workout", "activity": f"{snap.get('who')}'s workout",
                 "event": f"{snap.get('who')} shared an event", "club": f"{snap.get('who')} shared a club",
                 "invite": "You're invited"}.get(str(k), "Shared from Rabbit")
    body: list[str] = []
    if snap.get("when") or snap.get("where"):
        body.append(f"<p class=sub>{_e(' · '.join(x for x in (snap.get('when'), snap.get('where')) if x))}</p>")
    if snap.get("facts"):
        body.append("<div class=facts>" + "".join(f"<span>{_e(f)}</span>" for f in snap["facts"]) + "</div>")
    if snap.get("why"):
        body.append(f"<p class=note>{_e(snap['why'])}</p>")
    if snap.get("about"):
        body.append(f"<p class=note>{_e(snap['about'])}</p>")
    if snap.get("steps"):
        rows = "".join(f"<tr><th>{_e(s['label'])}</th><td>{_e(s['text'])}<div class=t>{_e(s['targets'])}</div></td></tr>"
                       for s in snap["steps"])
        body.append(f"<h2>The workout</h2><table>{rows}</table>")
    if snap.get("laps"):
        hr = any("hr" in lp for lp in snap["laps"])
        rows = "".join(f"<tr><th>{lp['n']}</th><td>{_e(lp['dist'])}</td><td>{_e(lp['time'])}</td><td>{_e(lp.get('pace', ''))}</td>"
                       + (f"<td>{_e(lp.get('hr', ''))}</td>" if hr else "") + "</tr>" for lp in snap["laps"])
        body.append(f"<h2>Laps</h2><table class=laps>{rows}</table>")
    if k == "club":
        if snap.get("members"):
            body.append(f"<p class=sub>{snap['members']} member{'s' if snap['members'] != 1 else ''}</p>")
        if snap.get("code"):
            body.append(f"<p>Club code: <b>{_e(snap['code'])}</b></p>")
    if k == "invite":
        body.append("<p class=note>Rabbit is a training app with a plan that adapts to your life, workouts synced "
                    "from your watch, and friends to train with.</p>")
    foot = ("Heart rate is included because the athlete chose to share it." if snap.get("hr")
            else "Shared from Rabbit. No heart rate or location is included.")
    if snap.get("source") and snap.get("source") != "Garmin":
        foot = f"Recorded with {_e(snap['source'])}. " + foot
    desc = _description(snap)
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><meta name=robots content="noindex,nofollow">
<title>{_e(title)} · Rabbit</title>
<meta property="og:type" content="website"><meta property="og:site_name" content="Rabbit">
<meta property="og:title" content="{_e(title)}"><meta property="og:description" content="{_e(desc)}">
<meta property="og:url" content="{_e(url)}"><meta property="og:image" content="{_e(og_image)}">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="{_e(title)}">
<meta name="twitter:description" content="{_e(desc)}"><meta name="twitter:image" content="{_e(og_image)}">
<meta name="theme-color" content="#1a3a2a">
<style>:root{{color-scheme:light dark;--bg:#f6f1e8;--card:#fffdf8;--text:#1f2a24;--muted:#5f6b63;--brand:#1a3a2a;--accent:#2f6b4a;--line:#e3dccd}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151816;--card:#1d211f;--text:#eef1ec;--muted:#a3ada6;--brand:#cfe7d6;--accent:#8fd0a8;--line:#2c322e}}}}
*{{box-sizing:border-box}}body{{margin:0;font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;background:var(--bg);color:var(--text)}}
main{{max-width:620px;margin:0 auto;padding:20px 16px 40px}}.brand{{display:flex;align-items:center;gap:8px;color:var(--brand);font-weight:700;letter-spacing:.14em;font-size:12px;text-transform:uppercase}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:18px;margin-top:14px}}
.kicker{{color:var(--muted);font-size:13px;margin:0}}h1{{font:600 26px/1.2 Georgia,"Times New Roman",serif;color:var(--brand);margin:4px 0 6px}}
.sub{{color:var(--muted);margin:0 0 10px}}.facts{{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}}
.facts span{{background:color-mix(in srgb,var(--accent) 14%,transparent);color:var(--text);border-radius:999px;padding:4px 10px;font-size:14px;font-variant-numeric:tabular-nums}}
.note{{margin:10px 0 0}}h2{{font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);margin:20px 0 6px}}
table{{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}}th{{text-align:left;font-weight:600;padding:8px 10px 8px 0;vertical-align:top;white-space:nowrap}}
td{{padding:8px 6px 8px 0}}tr{{border-bottom:1px solid var(--line)}}.t{{color:var(--muted);font-size:14px}}
.cta{{display:block;text-align:center;background:var(--accent);color:#fff;text-decoration:none;font-weight:600;border-radius:12px;padding:14px;margin-top:18px}}
@media (prefers-color-scheme:dark){{.cta{{color:#0f1a14}}}}footer{{margin-top:18px;color:var(--muted);font-size:13px}}</style></head>
<body><main><div class=brand><span aria-hidden="true">🐇</span>Rabbit</div>
<div class=card><p class=kicker>{_e(head_line)}</p><h1>{_e(emoji)} {_e(title)}</h1>{''.join(body)}
<a class=cta href="{_e(cta_url)}">{_e(cta_label)}</a></div>
<footer>{foot} The athlete can turn this link off at any time.</footer></main></body></html>"""


__all__ = ["CREATES_PER_DAY", "KINDS", "MAX_LINKS", "ShareError", "ShareLinks", "activity_snap", "club_snap",
           "default_text", "event_snap", "invite_snap", "planned_snap", "render"]
