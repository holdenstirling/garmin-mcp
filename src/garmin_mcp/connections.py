"""Connected apps: one status row per integration for the app's "Connected apps" hub.

Pure helpers (``status``, ``view``) plus the per-app facts the connect popup shows: what Rabbit
reads and what it never does. The facts restate ``legal.privacy`` and ``sources.py`` (workouts
come from Garmin only; Oura data never reaches the AI model); ``tests/test_connections.py``
pins them against the privacy page so the popup can't promise something the policy doesn't.

TrainingPeaks is deliberately absent: it lives in the MCP server process only
(``trainingpeaks.py``, a per-user cookie set by a CLI), so the Rabbit app can't connect it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

APPS: dict[str, dict[str, Any]] = {
    "garmin": {
        "name": "Garmin Connect",
        "kind": "password",      # email + password (+ code) inside the popup; never stored
        "import_weeks": 12,
        "import_label": "Importing your last 12 weeks of workouts…",
        "reads": [
            "Workouts, heart rate and training load",
            "Sleep and training readiness",
            "Your gear, for shoe and bike mileage",
        ],
        "never": [
            "Never posts or shares anything on Garmin",
            "Only adds workouts to your Garmin calendar when you send a plan you built",
            "Your password goes to Garmin once and is never stored",
        ],
    },
    "oura": {
        "name": "Oura",
        "kind": "oauth",
        "import_weeks": 4,
        "import_label": "Importing your last 4 weeks of readiness and sleep…",
        "reads": [
            "Readiness, sleep and HRV",
            "Resting heart rate and daily activity summaries",
        ],
        "never": [
            "Oura data never goes to Rabbit's AI: it is only shown in the app and used by fixed rules",
            "Oura workouts are never imported (workouts come from Garmin only, so nothing counts twice)",
            "Never posts or changes anything in Oura",
        ],
    },
    "calendar": {
        "name": "Google Calendar",
        "kind": "oauth",
        "import_weeks": 6,
        "import_label": "Reading your next 6 weeks for trips and busy days…",
        "reads": [
            "Event times on your main calendar (read-only)",
            "Trips and busy days, so your plan can work around them",
        ],
        "never": [
            "Never creates, edits or deletes events",
            "Never shares your calendar with anyone",
        ],
    },
}
ORDER = ("garmin", "oura", "calendar")


def _iso(ts: float | str | None) -> str | None:
    if ts is None or ts == "":
        return None
    if isinstance(ts, str):
        return ts
    return datetime.fromtimestamp(float(ts), UTC).isoformat(timespec="seconds")


def status(app: str, *, available: bool, connected: bool, last_sync: float | str | None = None,
           error: str | None = None, attention: bool = False) -> dict[str, Any]:
    """One app's row. ``state``: connected | attention | not_connected | unavailable.
    ``attention`` = connected but it needs the athlete (expired sign-in, refused access)."""
    meta = APPS[app]
    state = ("unavailable" if not available and not connected
             else ("attention" if attention else "connected") if connected
             else "not_connected")
    return {"id": app, "name": meta["name"], "kind": meta["kind"], "available": available,
            "connected": connected, "state": state, "last_sync": _iso(last_sync) if connected else None,
            "error": error if connected or attention else None,
            "import_weeks": meta["import_weeks"], "import_label": meta["import_label"],
            "reads": list(meta["reads"]), "never": list(meta["never"])}


def view(rows: dict[str, dict[str, Any]], sources: dict[str, Any] | None = None) -> dict[str, Any]:
    """The hub: apps in a fixed order, plus the recovery/sleep source choice (sources.py)."""
    return {"apps": [rows[a] for a in ORDER if a in rows], "sources": sources}


__all__ = ["APPS", "ORDER", "status", "view"]
