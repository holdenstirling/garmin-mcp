"""Read-only plan links: an athlete shares an unguessable URL (``/app/s/<token>``) with a
coach or training partner. The page is server-rendered HTML (no app, no login, no JS):
first name, main event, upcoming events, and the next two weeks of the plan. No chats,
no health data, no Garmin numbers. One link per athlete; making a new one or turning
sharing off kills the old link immediately.
"""

from __future__ import annotations

import html
import secrets
import threading
import time
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from .appstore import AppStore
from .planbuilder import iter_sessions

TOKEN_BYTES = 24


class Shares:
    def __init__(self, store: AppStore, *, clock: Callable[[], float] = time.time) -> None:
        self._s = store
        self._doc = store.global_doc("shares")
        self._clock = clock
        self._lock = threading.Lock()

    def current(self, user_id: str) -> str | None:
        return self._s.user_doc(user_id, "share").load().get("token")

    def create(self, user_id: str) -> str:
        token = secrets.token_urlsafe(TOKEN_BYTES)
        with self._lock:
            old = self.current(user_id)

            def apply(d: dict[str, Any]) -> None:
                if old:
                    d.pop(old, None)
                d[token] = {"user_id": user_id, "created": int(self._clock())}
            self._doc.update(apply)
            self._s.user_doc(user_id, "share").save({"token": token})
        return token

    def revoke(self, user_id: str) -> None:
        with self._lock:
            old = self.current(user_id)
            if old:
                self._doc.update(lambda d: d.pop(old, None))
            self._s.user_doc(user_id, "share").delete()

    def resolve(self, token: str) -> str | None:
        if not isinstance(token, str) or not (20 <= len(token) <= 64):
            return None
        for t, rec in self._doc.load().items():
            if secrets.compare_digest(t, token):
                return str(rec["user_id"])
        return None


def _e(v: Any) -> str:
    return html.escape(str(v or ""), quote=True)


def render(name: str, goal: dict[str, Any] | None, events: list[dict[str, Any]],
           plan: dict[str, Any] | None, today: date) -> str:
    first = (name or "An athlete").split(" ")[0]
    rows = []
    if plan:
        end = (today + timedelta(days=13)).isoformat()
        by_day: dict[str, list[dict[str, Any]]] = {}
        for _, d, s in iter_sessions(plan):
            if today.isoformat() <= d <= end:
                by_day.setdefault(d, []).append(s)
        for d in sorted(by_day):
            label = date.fromisoformat(d).strftime("%a %b %-d")
            items = ", ".join(f"{_e(s['title'])}{f' · {s['minutes']} min' if s.get('minutes') else ''}"
                              for s in by_day[d] if s["sport"] != "rest") or "Rest"
            rows.append(f"<tr><th>{_e(label)}</th><td>{items}</td></tr>")
    evs = "".join(f"<li><b>{_e(e['name'])}</b> · {_e(date.fromisoformat(e['date']).strftime('%b %-d, %Y'))}"
                  f"{' · main event' if e.get('main') else ''}</li>"
                  for e in events if e.get("date", "") >= today.isoformat())
    head = ""
    if goal and goal.get("date"):
        days = (date.fromisoformat(goal["date"]) - today).days
        head = f"<p class=sub>{_e(goal.get('title'))} · {max(days, 0)} days to go</p>"
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><meta name=robots content="noindex,nofollow">
<title>{_e(first)}'s training plan</title>
<style>:root{{color-scheme:light dark;--a:#2f7d5b}}body{{margin:0;font:15px/1.45 system-ui,-apple-system,sans-serif;background:Canvas;color:CanvasText}}
main{{max-width:640px;margin:0 auto;padding:24px 16px}}h1{{font-size:22px;margin:0 0 4px}}.sub{{color:GrayText;margin:0 0 20px}}
h2{{font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:GrayText;margin:24px 0 8px}}
table{{width:100%;border-collapse:collapse}}th{{text-align:left;font-weight:600;white-space:nowrap;padding:8px 12px 8px 0;vertical-align:top;width:1%}}
td{{padding:8px 0}}tr{{border-bottom:1px solid color-mix(in srgb,CanvasText 12%,transparent)}}ul{{padding-left:18px}}
footer{{margin-top:32px;color:GrayText;font-size:12px}}</style></head>
<body><main><h1>{_e(first)}'s training plan</h1>{head}
<h2>Next two weeks</h2>{'<table>' + ''.join(rows) + '</table>' if rows else '<p>No plan built yet.</p>'}
{'<h2>Upcoming events</h2><ul>' + evs + '</ul>' if evs else ''}
<footer>Shared read-only from Rabbit. The athlete can turn this link off at any time.</footer></main></body></html>"""


__all__ = ["Shares", "render"]
