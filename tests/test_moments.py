"""Rabbit moments: deterministic updates in the Rabbit log (moments.py)."""

from __future__ import annotations

import asyncio
import inspect
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx2
from starlette.applications import Starlette

from garmin_mcp import agent as agent_mod
from garmin_mcp import moments as mm
from garmin_mcp.coaches import coach_user_id
from garmin_mcp.coaching import CoachStore
from garmin_mcp.config import Settings
from garmin_mcp.moments import Moments
from garmin_mcp.poller import FireOutcome, FireResult, Poller, StateStore
from garmin_mcp.sync import LiveSync
from garmin_mcp.webapp import build_app_routes
from garmin_mcp.webauth import WebAuth
from garmin_mcp.webchat import ChatRunner
from tests.test_agent import env  # noqa: F401  (fixture)

BASE = "http://localhost:8001"
TZ = ZoneInfo("America/Denver")
COACH = "coach@example.com"


class Clock:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def now(self, uid: str) -> datetime:
        return self.at

    def ts(self) -> float:
        return self.at.timestamp()


def make(env, at: datetime, **kw: Any) -> tuple[Moments, Clock, CoachStore, list[tuple]]:
    clock = Clock(at)
    coach = CoachStore(env.store, clock=clock.ts)
    pushes: list[tuple] = []
    m = Moments(env.store, coach, now=clock.now, clock=clock.ts,
                push=lambda u, t, b, url: pushes.append((u, t, b, url)), **kw)
    return m, clock, coach, pushes


def feed(coach: CoachStore, uid: str = "friend") -> list[dict[str, Any]]:
    return [t for t in coach.turns(uid, coach.coach_thread(uid)["id"]) if t["kind"] == "moment"]


def gact(aid: int, *, day: date, name: str = "Morning Run", minutes: float = 52 + 10 / 60,
         meters: float = 9978.0, sport: str = "running") -> dict[str, Any]:
    return {"activityId": aid, "activityName": name, "activityType": {"typeKey": sport},
            "duration": minutes * 60, "distance": meters, "startTimeLocal": f"{day.isoformat()} 07:12:00"}


NOON = datetime(2026, 10, 14, 12, 0, tzinfo=TZ)


# ------------------------------------------------------------- builders ---
def test_workout_moment_text_actions_and_limits() -> None:
    a = gact(42, day=NOON.date())
    m = mm.workout_moment(a, imperial=True, streak=9, ai_note=True)
    assert m["text"] == "🐇 Logged: Morning Run · 6.2 mi in 52:10 · +36 XP. 9-day streak!"
    assert m["key"] == "act:42"
    assert [x["id"] for x in m["actions"]] == ["checkin", "reaction"]
    assert all(x["activity_id"] == 42 for x in m["actions"])
    metric = mm.workout_moment(a, imperial=False, streak=None, ai_note=False)
    assert "10.0 km in 52:10" in metric["text"] and metric["text"].endswith("Nice hop.")
    # With the AI note coming, the moment stays factual (no cheer to repeat).
    assert "Nice hop" not in mm.workout_moment(a, imperial=False, ai_note=True)["text"]
    swim = mm.workout_moment(gact(1, day=NOON.date(), sport="lap_swimming", meters=1500), imperial=True)
    assert "1,640 yd" in swim["text"]
    lift = mm.workout_moment(gact(2, day=NOON.date(), sport="strength_training", meters=0, minutes=45),
                             imperial=True)
    assert "· 45 min ·" in lift["text"]
    long = mm.workout_moment(gact(3, day=NOON.date(), name="x" * 200), imperial=True, streak=120)
    every = [m, metric, swim, lift, long, mm.streak_risk(12, NOON.date()), mm.level_moment(7),
             mm.badge_moment("b", "First 100 km"), mm.challenge_moment("k", "Run 3x", 75),
             mm.coach_plan_moment("Bill", "1"), mm.grade_moment({"id": "e", "name": "Boston"}, "B", "B+", NOON.date()),
             *(mm.streak_milestone(n) for n in mm.STREAK_MILESTONES),
             *(mm.race_moment({"id": "e", "name": "Boston Marathon"}, d) for d in (56, 28, 14, 7, 1))]
    for x in every:
        assert x is not None and len(x["text"]) <= mm.MAX_CHARS and mm.emoji_count(x["text"]) <= 1, x
        assert "—" not in x["text"], x
        if x["type"] not in ("coach_plan", "grade") and not x["key"].endswith(":eve"):
            assert any(ch.isdigit() for ch in x["text"]), x  # a real number in every update
    assert mm.workout_moment({"activityId": "nope"}, imperial=True) is None


def test_race_countdown_thresholds() -> None:
    step = {d: mm.race_step(d) for d in range(0, 60)}
    assert [d for d, s in step.items() if s == "8w"] == [53, 54, 55, 56]
    assert [d for d, s in step.items() if s == "4w"] == [25, 26, 27, 28]
    assert [d for d, s in step.items() if s == "2w"] == [12, 13, 14]
    assert [d for d, s in step.items() if s == "week"] == [5, 6, 7]
    assert [d for d, s in step.items() if s == "eve"] == [1]
    assert step[0] is None and step[40] is None and step[20] is None
    ev = {"id": "ev1", "name": "Boston Marathon"}
    assert [a["id"] for a in mm.race_moment(ev, 56)["actions"]] == ["readiness"]
    assert [a["id"] for a in mm.race_moment(ev, 6)["actions"]] == ["readiness", "racepack"]
    assert mm.race_moment(ev, 1)["text"].startswith("🏁 Boston Marathon is tomorrow")
    assert mm.race_moment(ev, 30) is None


def test_no_oura_in_moments() -> None:
    src = inspect.getsource(mm)
    assert "from .oura" not in src and "import oura" not in src and "from .sources" not in src
    assert "oura" not in str(inspect.signature(Moments.__init__)).lower()


# ------------------------------------------------------------- service ----
def test_workout_synced_posts_once_with_streak_and_milestone(env) -> None:
    stats = {"streak": {"current": 7, "today_done": True, "at_risk": False}}
    m, _, coach, pushes = make(env, NOON, stats=lambda u: stats)
    old = gact(10, day=NOON.date() - timedelta(days=5))
    assert m.workouts("friend", [old, gact(11, day=NOON.date())]) == 1
    rows = feed(coach)
    assert len(rows) == 2  # the workout + the 7-day milestone
    assert rows[0]["parts"][0]["moment"] == "workout" and "Logged: Morning Run" in rows[0]["assistant"]
    assert "streak!" not in rows[0]["assistant"]  # the milestone says it instead
    assert rows[1]["parts"][0]["moment"] == "streak" and "7-day streak" in rows[1]["assistant"]
    # The poller and live sync both see it: deduped by activity id; milestone not repeated.
    assert m.workouts("friend", [gact(11, day=NOON.date())]) == 0
    assert len(feed(coach)) == 2 and pushes == []  # workouts and milestones never push
    assert m.workouts("coach_abc", [gact(12, day=NOON.date())]) == 0


def test_quiet_hours_queue_and_workout_exempt(env) -> None:
    night = datetime(2026, 10, 14, 22, 30, tzinfo=TZ)
    m, clock, coach, pushes = make(env, night)
    assert m.post("friend", mm.race_moment({"id": "e1", "name": "Boston"}, 28)) == "queued"
    assert m.workouts("friend", [gact(20, day=night.date())]) == 1  # instant, even at night
    assert [t["parts"][0]["moment"] for t in feed(coach)] == ["workout"]
    assert m.flush("friend") == 0
    clock.at = datetime(2026, 10, 15, 6, 59, tzinfo=TZ)
    assert m.flush("friend") == 0
    clock.at = datetime(2026, 10, 15, 7, 0, tzinfo=TZ)
    assert m.flush("friend") == 1
    assert [t["parts"][0]["moment"] for t in feed(coach)] == ["workout", "race"]
    assert len(pushes) == 1 and pushes[0][1] == "Race countdown" and pushes[0][3] == "/app/?open=coach"
    assert m.post("friend", mm.race_moment({"id": "e1", "name": "Boston"}, 28)) == "duplicate"


def test_daily_cap_and_dedupe(env) -> None:
    m, clock, coach, _ = make(env, NOON)
    out = [m.post("friend", mm.badge_moment(f"b{i}", f"Badge {i}")) for i in range(6)]
    assert out == ["posted"] * mm.DAILY_CAP + ["capped", "capped"]
    assert m.post("friend", mm.badge_moment("b0", "Badge 0")) == "duplicate"
    assert m.workouts("friend", [gact(30, day=NOON.date())]) == 1  # workouts are exempt
    clock.at += timedelta(days=1)
    assert m.post("friend", mm.badge_moment("new", "Badge new")) == "posted"


def test_streak_at_risk_conditions_and_push(env) -> None:
    st = {"current": 12, "at_risk": True, "today_done": False}
    early = datetime(2026, 10, 14, 18, 29, tzinfo=TZ)
    m, clock, coach, pushes = make(env, early, stats=lambda u: {"streak": st})
    m.tick("friend")
    assert feed(coach) == []
    clock.at = datetime(2026, 10, 14, 18, 31, tzinfo=TZ)
    m.tick("friend")
    m.tick("friend")  # once a day
    rows = feed(coach)
    assert len(rows) == 1 and "12-day streak is on the line" in rows[0]["assistant"]
    act = rows[0]["parts"][0]["actions"][0]
    assert act["id"] == "ask" and "20-minute" in act["prompt"]
    assert len(pushes) == 1 and pushes[0][1] == "Streak on the line" and not pushes[0][2].startswith("⏳")
    day = clock.at.date() + timedelta(days=1)
    for bad in ({"current": 2, "at_risk": True, "today_done": False},
                {"current": 12, "at_risk": False, "today_done": False},  # grace left / plan rest day
                {"current": 12, "at_risk": True, "today_done": True}):
        st.clear(); st.update(bad)
        assert m.check_streak_risk("friend", day) == "skipped"
    # Push off in settings: still posted, not pushed.
    env.store.user_doc("friend", "profile").update(lambda p: p.update(moments_push=False))
    st.clear(); st.update({"current": 5, "at_risk": True, "today_done": False})
    assert m.check_streak_risk("friend", day) == "posted" and len(pushes) == 1


def test_race_countdown_via_tick(env) -> None:
    race = (NOON.date() + timedelta(days=28)).isoformat()
    events = [{"id": "e9", "name": "Boston", "date": race, "main": True},
              {"id": "e8", "name": "Tune-up 10k", "date": (NOON.date() + timedelta(days=14)).isoformat()}]
    m, clock, coach, pushes = make(env, datetime(2026, 10, 14, 7, 30, tzinfo=TZ), events=lambda u: events)
    m.tick("friend")
    assert feed(coach) == []  # from 08:00
    clock.at = datetime(2026, 10, 14, 8, 5, tzinfo=TZ)
    m.tick("friend")
    rows = feed(coach)
    assert len(rows) == 1 and rows[0]["assistant"].startswith("🏁 4 weeks to Boston")
    assert rows[0]["parts"][0]["actions"][0] == {"id": "readiness", "label": "Race readiness", "event_id": "e9"}
    assert len(pushes) == 1
    clock.at += timedelta(days=1)
    m.tick("friend")
    assert len(feed(coach)) == 1  # same milestone, next day: deduped


def test_grade_change_weekly_at_most(env) -> None:
    grade = {"g": "B"}
    ev = {"id": "e1", "name": "Boston", "date": "2027-04-19", "main": True}
    m, clock, coach, _ = make(env, NOON, events=lambda u: [ev], grade=lambda u, e: grade["g"])
    d = NOON.date()
    assert m.check_grade("friend", d) == "baseline"
    assert m.check_grade("friend", d) == "same"
    grade["g"] = "B+"
    assert m.check_grade("friend", d) == "posted"
    assert "readiness: B → B+" in feed(coach)[-1]["assistant"] and feed(coach)[-1]["assistant"].startswith("📈")
    grade["g"] = "A-"
    assert m.check_grade("friend", d + timedelta(days=3)) == "wait"
    assert m.check_grade("friend", d + timedelta(days=7)) == "posted"
    assert "B+ → A-" in feed(coach)[-1]["assistant"]


def test_progress_deltas_after_baseline(env) -> None:
    m, clock, coach, _ = make(env, NOON)
    base = {"level": 5, "xp": 1000, "level_up": False, "new_badges": [{"id": "old", "title": "Old"}]}
    chal = [{"key": "runs3:2026-10-05", "name": "Run 3x", "xp": 75}]
    assert m.on_progress("friend", base, chal) == 0 and feed(coach) == []  # back-fill: nothing
    nxt = {"level": 6, "xp": 1600, "level_up": True,
           "new_badges": [{"id": "old", "title": "Old"}, {"id": "k100", "title": "100 km"}]}
    chal2 = chal + [{"key": "hours5:2026-10-12", "name": "5 hours", "xp": 75}]
    assert m.on_progress("friend", nxt, chal2) == 3
    kinds = [t["parts"][0]["moment"] for t in feed(coach)]
    assert kinds == ["level", "badge", "challenge"]
    assert "Level 6" in feed(coach)[0]["assistant"]
    assert m.on_progress("friend", nxt, chal2) == 0  # same deltas again: deduped
    assert m.on_progress("coach_x", nxt, chal2) == 0


def test_completed_challenges_from_doc() -> None:
    doc = {"joined": [{"id": "c1", "name": "Run 3x", "period": "week", "completed_at": "x", "xp_key": "r:1"},
                      {"id": "c2", "name": "Open", "period": "week"}],
           "history": [{"id": "c3", "name": "Month", "period": "month", "completed_at": "y"}]}
    assert mm.completed_challenges(doc) == [{"key": "r:1", "name": "Run 3x", "xp": 75},
                                            {"key": "c3", "name": "Month", "xp": 150}]


# --------------------------------------------------------------- hooks ----
def test_live_sync_hands_new_activities_to_moments(env) -> None:
    acts = [gact(100, day=NOON.date())]
    seen: list[tuple[str, list]] = []
    s = LiveSync(env.store, lambda u: acts, connected=lambda u: True, on_new=lambda u: None,
                 clock=lambda: 0.0, on_activities=lambda u, a: seen.append((u, a)))
    s.check("friend")  # baseline
    s._last.clear()
    acts.insert(0, gact(101, day=NOON.date(), name="Lunch Ride"))
    assert s.check("friend")["changed"] is True
    assert seen == [("friend", [acts[0]])]


def test_poller_on_new_runs_before_routine(tmp_path: Path) -> None:
    acts = [gact(1, day=NOON.date())]
    order: list[str] = []

    class Routine:
        def fire(self, text: str) -> FireResult:
            order.append("fire")
            return FireResult(FireOutcome.OK, 200)

    p = Poller(lambda start, limit: acts if start == 0 else [], StateStore(tmp_path / "s.json"), Routine(),
               on_new=lambda new: order.append(f"new:{[a['activityId'] for a in new]}"))
    p.poll()  # baseline
    acts.insert(0, gact(2, day=NOON.date()))
    p.poll()
    assert order == ["new:[2]", "fire"]


# ------------------------------------------------------- feed + privacy ---
def test_feed_includes_moments_and_coach_visibility(env, tmp_path) -> None:
    agent, backend = env.agent([(["Sure."], [], "end_turn")])
    agent.moments.workouts("friend", [gact(77, day=agent._now("friend").date())], ai_note=False)
    # Moments are UI-only: never part of the model's context.
    assert agent._context_messages("friend", agent.coach.coach_thread("friend")["id"]) == []
    settings = Settings(public_base_url=BASE, data_dir=tmp_path, app_enabled=True, mcp_enabled=False,
                        allowed_google_users={"friend@example.com": "friend"})
    runner = ChatRunner(agent)
    a_app = Starlette(routes=build_app_routes(settings, WebAuth(settings, env.store, "", dev_user="friend"),
                                              env.tokens, None, None, runner))
    cid = coach_user_id(COACH)
    c_app = Starlette(routes=build_app_routes(settings, WebAuth(settings, env.store, "", dev_user=cid),
                                              env.tokens, None, None, runner))
    h = {"origin": BASE}
    tid = agent.coach.coach_thread("friend")["id"]

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=a_app), base_url=BASE) as a, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=c_app), base_url=BASE) as c:
            r = await a.get(f"/app/api/threads/{tid}/messages")
            assert r.status_code == 200, r.text
            t = next(x for x in r.json()["turns"] if x["kind"] == "moment"
                     and x["parts"][0]["moment"] == "workout")
            assert t["parts"][0]["type"] == "moment"
            assert t["parts"][0]["actions"][1] == {"id": "reaction", "label": "See breakdown", "activity_id": 77}
            # Coach accounts never reach the athlete's own routes.
            assert (await c.get(f"/app/api/threads/{tid}/messages")).status_code == 403
            await a.post("/app/api/coaches", headers=h, json={"email": COACH})
            assert (await c.get("/app/api/me")).status_code == 200
            assert (await c.get(f"/app/api/coach/athletes/friend/rabbit/{tid}")).status_code == 400
            await a.patch(f"/app/api/coaches/{COACH}", headers=h, json={"can_see_rabbit_chats": True})
            r = await c.get(f"/app/api/coach/athletes/friend/rabbit/{tid}")
            assert r.status_code == 200
            mt = next(x for x in r.json()["turns"] if x["id"] == t["id"])
            assert mt["parts"] == [{"type": "text", "text": t["parts"][0]["text"]}] and mt["label"] == "update"
            s = (await a.put("/app/api/settings", headers=h, json={"moments_push": False}))
            assert s.status_code == 200
            assert env.store.user_doc("friend", "profile").load()["moments_push"] is False
            assert s.json()["moments_push"] is False
            assert (await a.get("/app/api/me")).json()["settings"]["moments_push"] is False
    asyncio.run(go_())


# ---------------------------------------------------------- reply length ---
def test_system_prompt_keeps_length_rules() -> None:
    p = agent_mod.SYSTEM_PROMPT
    for rule in ("Phone-first and short", "about 80 words", "under about 200 words",
                 "Lead with the answer", "One emoji at most", "want the full breakdown?"):
        assert rule in p, rule
    assert agent_mod.LONG_REPLY_WORDS == 250


def test_long_reply_is_logged_not_truncated(env, monkeypatch) -> None:
    long = " ".join(["word"] * 300)
    agent, _ = env.agent([([long], [], "end_turn"), (["Short."], [], "end_turn")])
    logged: list[dict[str, Any]] = []
    real = agent_mod.log_event
    monkeypatch.setattr(agent_mod, "log_event",
                        lambda lg, lvl, ev, **f: (logged.append({"event": ev, **f}), real(lg, lvl, ev, **f)))
    tid = agent.coach.coach_thread("friend")["id"]
    rec = asyncio.run(agent.run("friend", "Explain everything", lambda e: None, thread_id=tid))
    assert rec["assistant"] == long  # untouched
    assert [x["words"] for x in logged if x["event"] == "long_reply"] == [300]
    asyncio.run(agent.run("friend", "Quick one", lambda e: None, thread_id=tid))
    assert len([x for x in logged if x["event"] == "long_reply"]) == 1
