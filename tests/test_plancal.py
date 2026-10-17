"""Plan calendar (plancal.py): move / swap / undo, re-balance rules, weekly mileage, missed
sessions + fixes, notes per kind, the morning-after moment and the API (coach 403)."""

from __future__ import annotations

import asyncio
import copy
from datetime import date, datetime, timedelta

import httpx2
import pytest

from garmin_mcp import plancal as pc
from garmin_mcp.planbuilder import PlanError, iter_sessions, make_session, week_for
from garmin_mcp.weekring import ring
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_profile import BASE, _apps
from tests.test_stats import act

MON = date(2026, 10, 12)       # fixed: nothing depends on the clock
WED = MON + timedelta(days=2)  # "today"
THR = 270.0                    # 4:30/km threshold
ATHLETE = {"available_days": ["tue", "wed", "thu", "sat", "sun"], "long_day": "sat",
           "run_threshold_pace": THR, "units": "imperial"}


def S(sid: str, sport: str, kind: str, minutes: int) -> dict:
    s = make_session(sport, kind, minutes)
    s["id"] = sid
    return s


def plan() -> dict:
    """Mon rest, Tue tempo, Wed easy (today), Thu threshold, Fri rest, Sat long, Sun easy; next week easy runs."""
    layout = {0: [], 1: [S("tue", "run", "tempo", 50)], 2: [S("wed", "run", "easy", 40)],
              3: [S("thu", "run", "threshold", 50)], 4: [], 5: [S("sat", "run", "long", 90)],
              6: [S("sun", "run", "easy", 40)]}
    weeks = []
    for k in range(2):
        start = MON + timedelta(weeks=k)
        days = {}
        for i in range(7):
            ss = copy.deepcopy(layout[i]) if k == 0 else ([S(f"n{i}", "run", "easy", 40)] if i in (1, 3, 5) else [])
            days[(start + timedelta(days=i)).isoformat()] = ss or [make_session("rest", "rest", 0)]
        weeks.append({"index": k + 1, "start": start.isoformat(), "phase": "build", "recovery": False,
                      "hours": 0, "focus": "", "days": days})
    return {"start": MON.isoformat(), "first_day": MON.isoformat(), "race_date": "2027-03-01",
            "distance": "half marathon", "weeks": weeks}


class FakePlans:
    def __init__(self, p: dict, today: date = WED) -> None:
        self.plan, self._today = p, today

    def get(self, uid: str) -> dict:
        return copy.deepcopy(self.plan)

    def today(self, uid: str) -> date:
        return self._today

    def _edit(self, uid: str, fn) -> dict:
        work = copy.deepcopy(self.plan)
        fn(work, self._today)
        self.plan = work  # all or nothing, like the doc update
        return copy.deepcopy(work)


class FakeCoach:
    def __init__(self, athlete: dict) -> None:
        self.a = athlete

    def athlete(self, uid: str) -> dict:
        return self.a


def cal(p: dict | None = None, acts: list | None = None, athlete: dict | None = None, today: date = WED):
    fp = FakePlans(p or plan(), today)
    svc = pc.PlanCal(fp, FakeCoach(athlete or ATHLETE), activities=lambda u: (today, acts or []),
                     now=lambda u: datetime.combine(today, datetime.min.time()).replace(hour=9))
    return svc, fp


def day_of(p: dict, sid: str) -> str:
    return next(d for _, d, s in iter_sessions(p) if s["id"] == sid)


def hard_days(p: dict) -> list[str]:
    return sorted({d for _, d, s in iter_sessions(p) if pc.is_hard(s)})


def back_to_back(p: dict) -> set:
    st = pc.statuses(p, [], WED)
    return {x for x in pc.hard_pairs(p, MON, st) if x[0] >= WED.isoformat()}


# ------------------------------------------------------------ move/swap/undo --
def test_move_and_undo() -> None:
    svc, fp = cal()
    out = svc.op("u", "move", {"session_id": "wed", "date": (MON + timedelta(days=4)).isoformat()})
    assert day_of(fp.plan, "wed") == "2026-10-16" and out["change"]["summary"] == "Moved easy run to Friday"
    assert fp.plan["weeks"][0]["days"]["2026-10-14"][0]["sport"] == "rest"  # the emptied day is a rest day
    assert out["cal"]["sessions"]["wed"]["moved_from"] == "2026-10-14"
    svc.op("u", "undo", {"id": out["change"]["id"]})
    assert day_of(fp.plan, "wed") == "2026-10-14" and not fp.plan["cal_undo"]
    with pytest.raises(PlanError):
        svc.op("u", "undo", {"id": out["change"]["id"]})  # once only


def test_move_rules() -> None:
    svc, fp = cal(acts=[act(MON + timedelta(days=1))])  # Tuesday's tempo is done
    for body, msg in [({"session_id": "tue", "date": "2026-10-17"}, "already done"),
                      ({"session_id": "wed", "date": "2026-10-13"}, "today or a later"),
                      ({"session_id": "wed", "date": "2027-05-01"}, "outside your plan"),
                      ({"session_id": "nope", "date": "2026-10-16"}, "isn't in your plan"),
                      ({"session_id": "wed", "date": "bad"}, "Pick a day")]:
        with pytest.raises(PlanError, match=msg):
            svc.op("u", "move", body)


def test_swap_days_and_garmin_orphans() -> None:
    p = plan()
    p["weeks"][0]["days"]["2026-10-18"][0]["garmin"] = {"workout_ids": [77], "hash": "x"}
    svc, fp = cal(p)
    out = svc.op("u", "swap", {"a": "2026-10-14", "b": "2026-10-18"})
    assert day_of(fp.plan, "wed") == "2026-10-18" and day_of(fp.plan, "sun") == "2026-10-14"
    assert 77 in fp.plan["garmin_orphans"] and "garmin" not in fp.plan["weeks"][0]["days"]["2026-10-14"][0]
    assert out["change"]["summary"] == "Swapped Wednesday and Sunday"
    svc.op("u", "undo", {"id": out["change"]["id"]})
    # Back on Sunday; its workout is already queued for removal, so it syncs again (no stale id).
    sun = fp.plan["weeks"][0]["days"]["2026-10-18"][0]
    assert sun["id"] == "sun" and "garmin" not in sun


# ---------------------------------------------------------------- re-balance --
def test_no_new_back_to_back_hard_days() -> None:
    svc, fp = cal()
    assert not back_to_back(fp.plan)
    out = svc.op("u", "move", {"session_id": "thu", "date": "2026-10-16"})  # threshold next to Saturday's long run
    assert day_of(fp.plan, "thu") == "2026-10-16"  # what the athlete placed stays put
    assert not back_to_back(fp.plan)
    assert out["change"]["rebalanced"][0] == "Saturday long run moved to Sunday"
    # Accept is a no-op; Undo of only the re-balance keeps the move.
    svc.op("u", "undo", {"id": out["change"]["rebalance_undo"]})
    assert day_of(fp.plan, "thu") == "2026-10-16" and day_of(fp.plan, "sat") == "2026-10-17"


def test_rebalance_respects_available_days() -> None:
    a = dict(ATHLETE, available_days=["tue", "wed", "thu", "fri", "sat"])  # no Sunday
    svc, fp = cal(athlete=a)
    out = svc.op("u", "move", {"session_id": "thu", "date": "2026-10-16"})
    assert day_of(fp.plan, "sat") != "2026-10-18"  # never onto a day they can't train
    assert all("moved to Sunday" not in x for x in out["change"]["rebalanced"])


def test_missed_quality_eased_when_no_room() -> None:
    p = plan()
    p["weeks"][0]["days"]["2026-10-18"] = [S("sun", "run", "vo2", 45)]
    svc, fp = cal(p, athlete=dict(ATHLETE, available_days=["thu", "fri", "sat", "sun"], long_day="sun"))
    out = svc.op("u", "move", {"session_id": "sat", "date": "2026-10-16"})  # long run next to Thursday's threshold
    lines = out["change"]["rebalanced"]
    assert not back_to_back(fp.plan) and any("easy run (no room for another hard day)" in x for x in lines)


def test_skip_respreads_miles_within_caps() -> None:
    svc, fp = cal()  # Tuesday's tempo was missed (no activity)
    v0 = svc.view("u")
    assert v0["sessions"]["tue"]["status"] == "missed"
    assert v0["sessions"]["tue"]["missed"]["why"] == "That was this week's tempo run."
    goal0 = v0["weeks"][MON.isoformat()]["run"]["goal"]
    hard0 = hard_days(fp.plan)
    before = {s["id"]: s["minutes"] for _, _, s in iter_sessions(fp.plan) if s.get("minutes")}
    out = svc.op("u", "fix", {"session_id": "tue", "how": "skip"})
    assert out["change"]["summary"] == "Skipped tempo run"
    lines = out["change"]["rebalanced"]
    assert lines and all(" +" in x and x.endswith(" mi") for x in lines)
    for _, d, s in iter_sessions(fp.plan):
        if s["id"] in before and s["minutes"] != before[s["id"]]:
            assert d > WED.isoformat() and s["kind"] in ("easy", "long")       # only future easy/long
            assert s["minutes"] <= before[s["id"]] * 1.15 and s["base_minutes"] == before[s["id"]]
    assert set(hard_days(fp.plan)) <= set(hard0)                               # no new hard day
    w = out["cal"]["weeks"][MON.isoformat()]["run"]
    assert w["goal"] == goal0 and w["planned"] > v0["weeks"][MON.isoformat()]["run"]["planned"] - 13
    assert out["cal"]["sessions"]["tue"]["status"] == "skipped"
    assert ring(fp.plan, [], WED)["target"] == ring(plan(), [], WED)["target"] - 1  # a skip leaves the home ring
    # A second re-balance never stacks past the cap.
    svc.op("u", "move", {"session_id": "wed", "date": "2026-10-16"})
    for _, _, s in iter_sessions(fp.plan):
        if s.get("base_minutes"):
            assert s["minutes"] <= s["base_minutes"] * 1.15


def test_fix_easy_and_fix_move() -> None:
    svc, fp = cal()
    out = svc.op("u", "fix", {"session_id": "tue", "how": "easy"})
    new = next(s for _, _, s in iter_sessions(fp.plan) if s.get("made_up_for") == "tue")
    assert new["kind"] == "easy" and new.get("base_minutes", new["minutes"]) <= 40 and out["change"]["summary"].startswith("Easy run added on ")
    assert next(s for _, _, s in iter_sessions(fp.plan) if s["id"] == "tue")["skipped"]
    assert not back_to_back(fp.plan)
    svc2, fp2 = cal()
    svc2.op("u", "fix", {"session_id": "tue", "how": "move", "date": "2026-10-16"})
    assert day_of(fp2.plan, "tue") == "2026-10-16" and not back_to_back(fp2.plan)
    with pytest.raises(PlanError, match="isn't missed"):
        svc2.op("u", "fix", {"session_id": "wed", "how": "skip"})


# ------------------------------------------------------------------ mileage --
def test_weekly_mileage_in_units_and_override() -> None:
    acts = [act(MON + timedelta(days=1), km=10.0), act(MON + timedelta(days=1), sport="cycling", km=30.0, hour=17)]
    svc, fp = cal(acts=acts)
    v = svc.view("u")
    run = v["weeks"][MON.isoformat()]["run"]
    assert run["done"] == 10.0 and run["goal"] > 30 and not run["custom"]
    assert "bike" not in v["weeks"][MON.isoformat()]  # a run plan shows run miles only
    assert v["imperial"] is True and v["months"]["2026-10"]["run"]["done"] == 10.0
    assert v["total"]["run"]["planned"] >= v["months"]["2026-10"]["run"]["planned"] - 0.1
    assert pc.fmt_km(40.2336, True) == "25 mi" and pc.fmt_km(18.25, False) == "18.2 km"
    svc.op("u", "goal", {"week": MON.isoformat(), "sport": "run", "km": 40.2336})
    w = svc.view("u")["weeks"][MON.isoformat()]["run"]
    assert w["goal"] == 40.2 and w["custom"]
    svc.op("u", "goal", {"week": MON.isoformat(), "sport": "run", "km": None})
    assert not svc.view("u")["weeks"][MON.isoformat()]["run"]["custom"]
    with pytest.raises(PlanError):
        svc.op("u", "goal", {"week": MON.isoformat(), "sport": "run", "km": -3})
    # Home ring field.
    m = svc.week_miles("u")
    assert m["primary"] == "run" and m["imperial"] and m["sports"]["run"]["done"] == 10.0


def test_multisport_totals_per_sport() -> None:
    p = plan()
    p["weeks"][0]["days"]["2026-10-15"] = [S("bk", "bike", "endurance", 90), S("sw", "swim", "technique", 45)]
    svc, _ = cal(p)
    w = svc.view("u")["weeks"][MON.isoformat()]
    assert set(w) == {"run", "bike", "swim"} and w["bike"]["goal"] > 30 and 1 < w["swim"]["goal"] < 4


def test_distance_and_pace_estimates() -> None:
    easy = S("e", "run", "easy", 60)
    km = pc.session_km(easy, THR)["run"]
    assert 10.5 < km < 12.5  # ~5:30/km easy at a 4:30 threshold
    assert pc.session_km(dict(easy, km=8.0), THR) == {"run": 8.0}  # explicit distance wins
    assert pc.session_km(S("r", "rest", "rest", 0), THR) == {}
    p = pc.target_pace(S("t", "run", "tempo", 50), THR)
    assert p["zone"] == 3 and p["fast"] < p["slow"]
    assert pc.threshold_pace({}, [])[1] == "default"
    recent = [act(MON - timedelta(days=i), minutes=55, km=10.0) for i in range(1, 5)]
    thr, src = pc.threshold_pace({}, recent)
    assert src == "recent" and 260 < thr < 280


# -------------------------------------------------------------------- notes --
def test_notes_per_kind_and_coach_override() -> None:
    p = plan()
    for sport, kinds in {"run": ("easy", "long", "recovery", "strides", "tempo", "threshold", "vo2", "racepace",
                                 "openers", "shakeout"),
                         "bike": ("endurance",), "swim": ("technique", "css"), "brick": ("brick",),
                         "strength": ("strength", "mobility")}.items():
        for k in kinds:
            n = pc.note_for(S("x", sport, k, 50), p, THR, True)
            assert n and n["source"] == "rabbit" and n["line"].endswith(".") and n["how"] and n["cues"]
    tempo = pc.note_for(S("t", "run", "tempo", 50), p, THR, True)
    assert "/mi" in tempo["how"] and "Comfortably hard" in tempo["how"]
    assert "/km" in pc.note_for(S("t", "run", "tempo", 50), p, THR, False)["how"]
    assert pc.note_for(S("r", "rest", "rest", 0), p, THR, True) is None
    tp = pc.note_for(dict(S("t", "run", "tempo", 50), note="3x10' at HM pace. Keep it smooth."), p, THR, True)
    assert tp["source"] == "coach" and tp["line"] == "3x10' at HM pace." and "smooth" in tp["why"]
    coach_plan = dict(p, origin={"kind": "coach"})
    assert pc.note_for(dict(S("t", "run", "easy", 40), detail="Hills, 6 reps"), coach_plan, THR, True)["source"] == "coach"
    assert pc.note_for(S("t", "run", "easy", 40), coach_plan, THR, True)["source"] == "rabbit"  # generated detail


# ------------------------------------------------------------- missed moment --
class FakeMoments:
    def __init__(self, profile: dict | None = None) -> None:
        self.posted: list[dict] = []
        self.claims: set = set()
        self.profile = profile or {}

    def _profile(self, uid):
        return self.profile

    def _claim(self, uid, what, day):
        if (what, day) in self.claims:
            return False
        self.claims.add((what, day))
        return True

    def post(self, uid, m):
        self.posted.append(m)
        return "posted"


def test_missed_moment_morning_after() -> None:
    thu = WED + timedelta(days=1)  # Wednesday's easy run had no activity
    m = pc.missed_moment(plan(), [], thu, thr=THR, imperial=True)
    assert m["type"] == "plan_missed" and m["key"] == "planmissed:wed" and len(m["text"]) <= 140
    assert m["text"].startswith("🗓️ Yesterday's easy run (") and " mi) didn't happen." in m["text"]
    assert m["actions"][0] == {"id": "plan_fix", "label": "Fix my week", "session_id": "wed"}
    assert pc.missed_moment(plan(), [act(WED)], thu, thr=THR, imperial=True) is None  # it was done

    def svc_at(hour: int, profile: dict | None = None):
        fm = FakeMoments(profile)
        s = pc.PlanCal(FakePlans(plan(), thu), FakeCoach(ATHLETE), activities=lambda u: (thu, []),
                       now=lambda u: datetime.combine(thu, datetime.min.time()).replace(hour=hour), moments=fm)
        return s, fm
    for hour in (6, 22, 13):
        assert svc_at(hour)[0].check_missed("u") == "not_now"  # quiet hours / not morning
    assert svc_at(8, {"moments_push": False})[0].check_missed("u") == "off"
    s, fm = svc_at(8)
    assert s.check_missed("u") == "posted" and fm.posted[0]["key"] == "planmissed:wed"
    assert s.check_missed("u") == "claimed" and len(fm.posted) == 1
    assert s.check_missed("coach_x") == "skipped"


# ---------------------------------------------------------------------- http --
def test_api_move_hook_and_coach_403(env, tmp_path) -> None:
    agent, _ = env.agent([])
    agent.plans._pause = 0
    today = agent._now("friend").date()
    agent.coach.update_athlete("friend", dict(ATHLETE))
    agent.coach.create_goal("friend", {"title": "Half", "distance": "half marathon",
                                       "date": (today + timedelta(weeks=12)).isoformat()})
    agent.plans.build("friend")
    seen: list = []
    agent.plans.add_listener(lambda uid, ch: seen.append((uid, ch)))
    athlete_app, coach_app, _ = _apps(env, tmp_path, agent)
    h = {"origin": BASE}

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=athlete_app), base_url=BASE) as a, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=coach_app), base_url=BASE) as c:
            v = (await a.get("/app/api/plan/calendar")).json()["cal"]
            assert set(v) >= {"sessions", "weeks", "months", "total", "imperial"}
            plan = agent.plans.get("friend")
            future = [(d, s) for _, d, s in iter_sessions(plan)
                      if d > today.isoformat() and s["sport"] != "rest" and s.get("kind") != "race"]
            d0, s0 = future[0]
            w = week_for(plan, date.fromisoformat(d0))
            free = next(k for k in sorted(w["days"]) if k > today.isoformat() and k != d0) if w else None
            target = free or (date.fromisoformat(d0) + timedelta(days=1)).isoformat()
            r = await a.post("/app/api/plan/calendar/move", headers=h, json={"session_id": s0["id"], "date": target})
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["change"]["summary"].startswith("Moved ") and body["plan"]["weeks"]
            moved = [x for _, ch in seen for x in ch if x["id"] == s0["id"]]
            assert moved and moved[0]["type"] == "moved" and moved[0]["from"] == d0 and moved[0]["to"] == target
            assert "garmin" not in moved[0]["session"]
            assert (await a.post("/app/api/plan/calendar/undo", headers=h, json={"id": body["change"]["id"]})).status_code == 200
            bad = await a.post("/app/api/plan/calendar/move", headers=h, json={"session_id": "nope", "date": target})
            assert bad.status_code == 400 and "isn't in your plan" in bad.json()["error"]
            assert (await a.post("/app/api/plan/calendar/move", json={})).status_code == 403  # no origin
            ring = (await a.get("/app/api/weekring")).json()["ring"]
            assert ring is None or "miles" in ring
            ics = await a.get(f"/app/api/plan/sessions/{s0['id']}/calendar.ics")
            assert ics.status_code == 200 and ics.headers["content-type"].startswith("text/calendar")
            assert ics.text.count("BEGIN:VEVENT") == 1 and f"UID:{s0['id']}@rabbit" in ics.text
            assert (await a.get("/app/api/plan/sessions/nope/calendar.ics")).status_code == 404
            assert (await c.get(f"/app/api/plan/sessions/{s0['id']}/calendar.ics")).status_code == 403
            assert any("targets" in x for x in v["sessions"].values())
            assert (await c.get("/app/api/plan/calendar")).status_code == 403
            for k in ("move", "swap", "fix", "undo", "goal"):
                assert (await c.post(f"/app/api/plan/calendar/{k}", headers=h, json={})).status_code == 403
    asyncio.run(go_())


# ------------------------------------------ targets, how it went, adjusted --
def test_view_has_targets_how_it_went_and_adjust_reasons() -> None:
    tue = MON + timedelta(days=1)
    a = act(tue, minutes=20, km=4.0)            # Tue tempo done, but short
    a["avg_hr"] = 150
    svc, fp = cal(acts=[a], athlete=dict(ATHLETE, threshold_hr=170))
    v = svc.view("u")
    t = v["sessions"]["thu"]["targets"]
    work = [x for st in t["steps"] for x in (st["steps"] if st["type"] == "repeat" else [st]) if x["type"] == "work"]
    assert work and work[0]["hr"] and work[0]["pace"] and work[0]["cadence"]
    went = v["sessions"]["tue"]["went"]
    assert went["verdict"] == "short" and went["actual"]["avg_hr"] == 150
    assert "went" not in v["sessions"]["thu"]
    # a missed session made up as an easy run says why it's there
    svc2, fp2 = cal(today=WED + timedelta(days=0))
    svc2.op("u", "fix", {"session_id": "tue", "how": "easy"})
    new = next(s for _, _, s in iter_sessions(fp2.plan) if s.get("made_up_for") == "tue")
    line = svc2.view("u")["sessions"][new["id"]]["adjusted"]
    assert line.startswith("Added to make up for") and "Tuesday" in line


def test_calendar_lists_workouts_outside_the_plan_on_their_day() -> None:
    from datetime import date
    from garmin_mcp.plancal import _dur_min, calendar_view
    assert _dur_min("0:39:12") == 39 and _dur_min("39:12") == 39 and _dur_min(2400) == 40 and _dur_min("x") is None
    plan = {"weeks": [], "race_date": "2027-06-06", "start": "2026-10-12"}
    acts = [{"activity_id": 7, "date": "2026-10-13 07:00:00", "name": "Lunch Run", "sport": "running",
             "distance_km": 8.0, "duration": "0:45:00", "avg_hr": 150}]
    v = calendar_view(plan, acts, date(2026, 10, 16), athlete={}, thr=300.0, pace_source="default", imperial=False)
    assert v["extra"]["2026-10-13"] == [{"id": 7, "name": "Lunch Run", "sport": "run", "km": 8.0, "minutes": 45, "avg_hr": 150.0}]
