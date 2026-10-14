"""Plan imports: parsing (CSV, XLSX, iCal), validation, preview diff, apply + undo (with
Garmin orphans), permissions, the athlete's notification and AI extraction."""

from __future__ import annotations

import asyncio
import io
import zipfile
from datetime import date, timedelta

import httpx2
import pytest
from starlette.applications import Starlette

from garmin_mcp.coaches import coach_user_id
from garmin_mcp.config import Settings
from garmin_mcp.planbuilder import KINDS_BY_SPORT, iter_sessions
from garmin_mcp.planimport import (
    AI_PER_DAY, ImportService, PlanImportError, build_import_plan, clean_rows, csv_template, detect,
    diff, kind_for, parse_csv, parse_date, parse_ics, parse_minutes, plan_rows, table_rows,
    week_templates, xlsx_table,
)
from garmin_mcp.webapp import build_app_routes
from garmin_mcp.webauth import WebAuth
from garmin_mcp.webchat import ChatRunner
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_plans import _athlete

BASE = "http://localhost:8001"
H = {"origin": BASE}
COACH = "bill@example.com"
TODAY = date(2026, 10, 14)  # a Wednesday
MON = date(2026, 10, 19)


def _rows(text: str, start: date | None = None):
    got = parse_csv(text)
    assert got is not None
    raw, warns = got
    rows, w2 = clean_rows(raw, start=start)
    return rows, warns + w2


# ---------------------------------------------------------------- parsing --
def test_template_round_trips() -> None:
    rows, warns = _rows(csv_template(TODAY))
    assert not warns and len(rows) == 7
    assert rows[0]["date"] == MON.isoformat() and rows[0]["sport"] == "rest"
    assert [r["sport"] for r in rows[1:]] == ["run", "bike", "swim", "strength", "bike", "run"]
    assert rows[2]["kind"] == "threshold" and rows[5]["kind"] == "long" and rows[5]["minutes"] == 150
    for r in rows:
        assert r["kind"] in KINDS_BY_SPORT[r["sport"]]


def test_csv_edge_cases() -> None:
    text = ("﻿My coach's plan\n"
            "Date;Sport;Workout;Duration;Effort;Notes\n"
            "10/20/2026;Running;Easy jog;1:00;;\n"
            "21/10/2026;Bike;Sweet spot 3x15;1.5;;\"Keep it, at 90%\"\n"
            "Oct 22 2026;swim;CSS 10x100;45 min;;\n"
            "2026-10-23;;Long run;1h30;long;\n"
            "2026-10-24;Zumba;;;;\n"
            "not a date;run;x;30;;\n"
            "2026-10-25;run;Recovery shakeout;2000;;\n"
            ";;;;;\n")
    rows, warns = _rows(text)
    by = {r["date"]: r for r in rows}
    assert by["2026-10-20"]["minutes"] == 60 and by["2026-10-20"]["kind"] == "easy"
    assert by["2026-10-21"]["minutes"] == 90 and by["2026-10-21"]["kind"] == "threshold"
    assert by["2026-10-21"]["notes"] == "Keep it, at 90%"
    assert by["2026-10-22"]["sport"] == "swim" and by["2026-10-22"]["kind"] == "css"
    assert by["2026-10-23"]["sport"] == "run" and by["2026-10-23"]["minutes"] == 90  # sport from title
    assert by["2026-10-24"]["sport"] == "other"   # unknown sport word: kept as other
    assert by["2026-10-25"]["minutes"] == 600     # clamped
    assert any("couldn't read the date" in w for w in warns)
    assert any("no duration" in w for w in warns) and any("adjusted" in w for w in warns)
    assert parse_csv("hello there\nthis is prose\n") is None


def test_trainingpeaks_workouts_export() -> None:
    text = ("Title,WorkoutType,WorkoutDescription,PlannedDuration,PlannedDistanceInMeters,WorkoutDay,CoachComments\n"
            "Aerobic Endurance,Run,Z2 the whole way,1.25,,2026-10-20,Stay patient\n"
            "Day Off,Day Off,,,,2026-10-21,\n"
            "VO2 Max Intervals,Bike,5x4' Z5,1,,2026-10-22,\n")
    rows, warns = _rows(text)
    assert not warns
    assert [(r["sport"], r["minutes"], r["kind"]) for r in rows] == [
        ("run", 75, "easy"), ("rest", None, "rest"), ("bike", 60, "vo2")]
    assert rows[0]["notes"] == "Z2 the whole way · Stay patient"


def test_week_and_day_columns_need_a_start() -> None:
    text = "week,day,sport,title,minutes\n1,Mon,run,Easy,40\n2,Sat,bike,Long ride,180\n"
    rows, _ = _rows(text, start=MON)
    assert [r["date"] for r in rows] == ["2026-10-19", "2026-10-31"]
    rows, warns = _rows(text)
    assert not rows and "needs a start date" in warns[0]


def test_parsers() -> None:
    assert parse_minutes("1:30") == 90 and parse_minutes("45:00") == 45 and parse_minutes("1:05:30") == 65
    assert parse_minutes("1h 15m") == 75 and parse_minutes("90'") == 90 and parse_minutes(1.5, hours=True) == 90
    assert parse_minutes("abc") is None and parse_minutes(-3) is None
    assert parse_date("13/10/2026") == date(2026, 10, 13) and parse_date("10/13/26") == date(2026, 10, 13)
    assert parse_date("Mon, Oct 19th, 2026") == MON and parse_date(46314) == date(2026, 10, 19)
    assert parse_date("2026-02-30") is None
    assert kind_for("swim", "intervals") == "css" and kind_for("strength", "mobility") == "mobility"
    assert kind_for("run", "race") == "race" and kind_for("bike", "strides") == "easy"


def test_ics_parsing() -> None:
    ics = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
           "BEGIN:VEVENT\r\nDTSTART;VALUE=DATE:20261020\r\nSUMMARY:Run: Tempo 3x10'\r\n"
           "DESCRIPTION:Planned Duration: 1:00:00\\nWarm up 15'\\, then\r\n  3x10' tempo\r\nEND:VEVENT\r\n"
           "BEGIN:VEVENT\r\nDTSTART:20261021T120000Z\r\nDTEND:20261021T133000Z\r\nSUMMARY:Endurance ride\r\nEND:VEVENT\r\n"
           "BEGIN:VEVENT\r\nDTSTART;VALUE=DATE:20261022\r\nDURATION:PT45M\r\nSUMMARY:Swim technique\r\nEND:VEVENT\r\n"
           "BEGIN:VEVENT\r\nDTSTART;VALUE=DATE:20261023\r\nSUMMARY:Week 2: Long run 90 min\r\nEND:VEVENT\r\n"
           "END:VCALENDAR\r\n")
    raw, _ = parse_ics(ics)
    rows, warns = clean_rows(raw)
    assert not warns
    assert [(r["date"], r["sport"], r["minutes"], r["kind"]) for r in rows] == [
        ("2026-10-20", "run", 60, "tempo"), ("2026-10-21", "bike", 90, "endurance"),
        ("2026-10-22", "swim", 45, "technique"), ("2026-10-23", "run", 90, "long")]
    assert rows[0]["title"] == "Tempo 3x10'" and "Warm up 15', then 3x10' tempo" in rows[0]["notes"]
    assert detect(ics.encode(), "tp.ics") == "ics"
    with pytest.raises(PlanImportError):
        parse_ics("BEGIN:VCALENDAR\nEND:VCALENDAR\n")


def _xlsx(cells: list[list[object]]) -> bytes:
    strings: list[str] = []
    xml_rows = []
    for i, row in enumerate(cells, start=1):
        cs = []
        for j, v in enumerate(row):
            ref = f"{chr(65 + j)}{i}"
            if isinstance(v, str):
                strings.append(v)
                cs.append(f'<c r="{ref}" t="s"><v>{len(strings) - 1}</v></c>')
            elif v is not None:
                cs.append(f'<c r="{ref}"><v>{v}</v></c>')
        xml_rows.append(f'<row r="{i}">{"".join(cs)}</row>')
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", f'<workbook {ns} xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                   '<sheets><sheet name="Plan" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/sharedStrings.xml", f'<sst {ns}>' + "".join(f"<si><t>{s}</t></si>" for s in strings) + "</sst>")
        z.writestr("xl/worksheets/sheet1.xml", f'<worksheet {ns}><sheetData>{"".join(xml_rows)}</sheetData></worksheet>')
    return buf.getvalue()


def test_xlsx_with_date_serials() -> None:
    data = _xlsx([["date", "sport", "title", "minutes", "intensity", "notes"],
                  [46314, "run", "Easy run", 40, "easy", None],
                  [46315, "bike", "Tempo ride", 75, "tempo", "Hold 85%"]])
    assert detect(data, "plan.xlsx") == "xlsx"
    got = table_rows(xlsx_table(data))
    assert got is not None
    rows, warns = clean_rows(got[0])
    assert not warns and [(r["date"], r["kind"], r["minutes"]) for r in rows] == [
        ("2026-10-19", "easy", 40), ("2026-10-20", "tempo", 75)]
    with pytest.raises(PlanImportError):
        xlsx_table(b"PK\x03\x04garbage")


# ------------------------------------------------------------- validation --
def _row(d: date, sport="run", minutes=45, title="Easy", kind=None):
    return {"date": d.isoformat(), "sport": sport, "kind": kind or KINDS_BY_SPORT[sport][0],
            "minutes": minutes, "title": title, "notes": "", "steps": None}


def test_build_validates_limits() -> None:
    a = _athlete()
    with pytest.raises(PlanImportError, match="up to 60 weeks"):
        build_import_plan([_row(MON), _row(MON + timedelta(weeks=60))], today=TODAY, athlete=a, goal=None, origin={})
    with pytest.raises(PlanImportError, match="up to 4 a day"):
        build_import_plan([_row(MON)] * 5, today=TODAY, athlete=a, goal=None, origin={})
    with pytest.raises(PlanImportError, match="nothing from today"):
        build_import_plan([_row(TODAY - timedelta(days=1))], today=TODAY, athlete=a, goal=None, origin={})
    plan, past = build_import_plan([_row(TODAY - timedelta(days=2)), _row(TODAY), _row(MON, "bike", 120, "Long", "long"),
                                    _row(MON + timedelta(days=13), "swim", 50, "Drills", "technique")],
                                   today=TODAY, athlete=a, goal={"date": "2026-11-01", "distance": "Olympic triathlon"},
                                   origin={"kind": "coach"})
    assert past == 1 and len(plan["weeks"]) == 3 and plan["first_day"] == TODAY.isoformat()
    assert plan["start"] == "2026-10-12" and min(plan["weeks"][0]["days"]) == TODAY.isoformat()
    assert plan["race_date"] == "2026-11-01" and plan["distance"] == "olympic triathlon"
    assert plan["weeks"][2]["phase"] == "race"
    long = plan["weeks"][1]["days"][MON.isoformat()][0]
    assert long["minutes"] == 120 and long["title"] == "Long" and long["steps"]
    for w in plan["weeks"]:
        assert len(w["days"]) <= 7
        for ss in w["days"].values():
            assert ss and all(s["kind"] in KINDS_BY_SPORT.get(s["sport"], ()) or s["kind"] == "race" for s in ss)


def test_steps_from_model_are_validated() -> None:
    good = [{"type": "warmup", "minutes": 10, "zone": 1},
            {"type": "repeat", "reps": 4, "steps": [{"type": "work", "minutes": 4, "zone": 5},
                                                    {"type": "recover", "minutes": 2, "zone": 1}]},
            {"type": "cooldown", "minutes": 10}]
    rows, _ = clean_rows([{"date": "2026-10-20", "sport": "run", "title": "VO2", "steps": good}])
    assert rows[0]["minutes"] == 44 and rows[0]["steps"][1]["reps"] == 4
    rows, _ = clean_rows([{"date": "2026-10-20", "sport": "run", "title": "x", "minutes": 30,
                           "steps": [{"type": "repeat", "reps": 99, "steps": []}]}])
    assert rows[0]["steps"] is None


def test_preview_diff_and_templates() -> None:
    a = _athlete()
    old, _ = build_import_plan([_row(MON, "run", 45, "Easy"), _row(MON + timedelta(days=1), "bike", 60, "Ride"),
                                _row(MON + timedelta(days=2), "swim", 40, "Swim")],
                               today=TODAY, athlete=a, goal=None, origin={})
    new, _ = build_import_plan([_row(MON, "run", 50, "Easy"), _row(MON + timedelta(days=1), "bike", 60, "Ride"),
                                _row(MON + timedelta(days=3), "run", 30, "Strides", "strides")],
                               today=TODAY, athlete=a, goal=None, origin={})
    weeks = diff(old, new, TODAY)
    assert len(weeks) == 1 and (weeks[0]["added"], weeks[0]["changed"], weeks[0]["removed"]) == (1, 1, 1)
    types = {c["type"]: c for c in weeks[0]["changes"]}
    assert types["changed"]["was"]["minutes"] == 45 and types["removed"]["sport"] == "swim"
    t = week_templates(_athlete(weekly_hours=8), {"distance": "70.3"})
    assert set(t["weeks"]) == {"base", "build", "recovery"}
    tot = {k: sum(r["minutes"] for r in v) for k, v in t["weeks"].items()}
    assert tot["recovery"] < tot["base"] < tot["build"]
    assert {r["sport"] for r in t["weeks"]["build"]} >= {"swim", "bike", "run"}
    assert all(0 <= r["weekday"] <= 6 for r in t["weeks"]["base"])


# ------------------------------------------------------------ apply / undo --
def _plan_with_sync(agent, today):
    agent.coach.update_athlete("friend", _athlete())
    agent.coach.create_goal("friend", {"title": "Race", "distance": "half marathon",
                                       "date": (today + timedelta(weeks=12)).isoformat()})
    plan = agent.plans.build("friend")
    goal = agent.coach.active_goal("friend")
    future = [s["id"] for _, d, s in iter_sessions(plan) if d > today.isoformat() and s["sport"] == "run"][:2]

    def mark(p):
        n = 900
        for _, _, s in iter_sessions(p):
            if s["id"] in future:
                n += 1
                s["garmin"] = {"workout_ids": [n], "hash": "x"}
    agent.plans._update_plan("friend", goal, mark)
    return goal


def test_apply_and_undo_keep_garmin_orphans(env) -> None:
    agent, _ = env.agent([])
    today = agent.plans.today("friend")
    goal = _plan_with_sync(agent, today)
    imp = ImportService(env.store, agent.plans, agent.coach)
    start = today + timedelta(days=(7 - today.weekday()) % 7 or 7)
    raw = [{"date": (start + timedelta(days=i)).isoformat(), "sport": "run", "title": f"Run {i}", "minutes": 40}
           for i in range(0, 21, 2)]
    pv = imp.preview("friend", raw, actor="coach_x", source="CSV", name="Fall block")
    assert pv["replaces"] and pv["garmin_synced"] == 2 and pv["totals"]["sessions"] == 11
    assert pv["totals"]["removed"] > 0 and pv["weeks"][-1]["start"] > pv["weeks"][0]["start"]
    with pytest.raises(PlanImportError, match="isn't available"):
        imp.apply("friend", pv["id"], actor="coach_other", actor_name="X", actor_role="coach")
    plan, summary = imp.apply("friend", pv["id"], actor="coach_x", actor_name="Bill Smith", actor_role="coach")
    assert summary["weeks"] == 3 and summary["sessions"] == 11
    doc = agent.plans.load_doc("friend", goal["id"])
    assert sorted(doc["garmin_orphans"]) == [901, 902]
    assert doc["origin"]["by_name"] == "Bill Smith"
    g = agent.coach.active_goal("friend")
    assert g["plan_source"] == "builder" and "their coach Bill Smith" in g["plan"]
    got = agent.plans.get("friend")
    assert got is not None and not got["race_changed"] and not got["events_changed"]
    # Plan editing still works on an imported plan.
    sid = next(s["id"] for _, d, s in iter_sessions(got) if s["sport"] == "run")
    agent.plans.update_session("friend", sid, {"minutes": 50})
    # Edits keep the import's origin, so undo is still offered.
    assert imp.status("friend")["undo"]["by_name"] == "Bill Smith"
    assert agent.plans.get("friend")["origin"]["import_id"] == pv["id"]
    # Undo: the built plan is back, its future sessions no longer claim Garmin workouts
    # (those are orphans now), and nothing is lost.
    restored = imp.undo("friend", actor="coach_x")
    assert restored is not None and restored.get("origin") is None
    doc = agent.plans.load_doc("friend", goal["id"])
    assert sorted(doc["garmin_orphans"]) == [901, 902]
    assert not any((s.get("garmin") or {}).get("workout_ids") for _, d, s in iter_sessions(doc) if d >= today.isoformat())
    assert "plan builder" in agent.coach.active_goal("friend")["plan"]
    with pytest.raises(PlanImportError, match="no plan import"):
        imp.undo("friend", actor="coach_x")


def test_undo_without_previous_plan_and_new_goal(env) -> None:
    agent, _ = env.agent([])
    today = agent.plans.today("friend")
    imp = ImportService(env.store, agent.plans, agent.coach)
    d = (today + timedelta(days=1)).isoformat()
    # No goal at all: applying creates one, undo archives it.
    pv = imp.preview("friend", [{"date": d, "sport": "bike", "title": "Ride", "minutes": 60}], actor="friend", source="CSV", name="Base")
    imp.apply("friend", pv["id"], actor="friend", actor_name="Me", actor_role="athlete")
    g = agent.coach.active_goal("friend")
    assert g["title"] == "Base" and agent.plans.get("friend") is not None
    agent.plans._update_plan("friend", g, lambda p: next(iter_sessions(p))[2].__setitem__("garmin", {"workout_ids": [77]}))
    assert imp.status("friend")["undo"]["restores"] == "no plan"
    imp.undo("friend", actor="friend")
    assert agent.coach.active_goal("friend") is None
    assert env.store.user_doc("friend", "garmin-pending").load()["ids"] == [77]
    # Goal without a plan: undo removes the plan and puts the goal back as it was.
    agent.coach.create_goal("friend", {"title": "Spring"})
    pv = imp.preview("friend", [{"date": d, "sport": "run", "title": "Run", "minutes": 30}], actor="friend", source="CSV")
    imp.apply("friend", pv["id"], actor="friend", actor_name="Me", actor_role="athlete")
    assert agent.coach.active_goal("friend")["plan_source"] == "builder"
    # The parked workout was adopted by the new plan.
    assert 77 in agent.plans.load_doc("friend", agent.coach.active_goal("friend")["id"])["garmin_orphans"]
    imp.undo("friend", actor="friend")
    g = agent.coach.active_goal("friend")
    assert g["title"] == "Spring" and "plan_source" not in g and agent.plans.get("friend") is None
    assert 77 in env.store.user_doc("friend", "garmin-pending").load()["ids"]


def test_plan_rows_round_trip(env) -> None:
    agent, _ = env.agent([])
    today = agent.plans.today("friend")
    _plan_with_sync(agent, today)
    rows = plan_rows(agent.plans.get("friend"), today)
    assert rows and all(r["date"] >= today.isoformat() for r in rows)
    cleaned, warns = clean_rows(rows)
    assert len(cleaned) == len(rows) and not [w for w in warns if "skipped" in w]


# --------------------------------------------------------------------- API --
class _Push:
    public_key = "k"

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    def send(self, to, title, body, url="/app/"):
        self.sent.append((to, title, body))

    def count(self, uid):
        return 1


def _apps(env, tmp_path, agent, push=None):
    settings = Settings(public_base_url=BASE, data_dir=tmp_path, app_enabled=True, mcp_enabled=False,
                        allowed_google_users={"friend@example.com": "friend"})
    runner = ChatRunner(agent)
    mk = lambda uid: Starlette(routes=build_app_routes(settings, WebAuth(settings, env.store, "", dev_user=uid),  # noqa: E731
                                                        env.tokens, push, None, runner))
    return mk("friend"), mk(coach_user_id(COACH))


def test_coach_import_api_end_to_end(env, tmp_path) -> None:
    agent, _ = env.agent([])
    today = agent.plans.today("friend")
    agent.coach.update_athlete("friend", _athlete())
    agent.coach.create_goal("friend", {"title": "Race", "distance": "marathon",
                                       "date": (today + timedelta(weeks=16)).isoformat()})
    env.store.user_doc(coach_user_id(COACH), "account").save({"name": "Bill Smith"})
    push = _Push()
    athlete_app, coach_app = _apps(env, tmp_path, agent, push)
    base = "/app/api/coach/athletes/friend/plan/import"
    start = today + timedelta(days=(7 - today.weekday()) % 7 or 7)
    rows = [{"date": (start + timedelta(days=i)).isoformat(), "sport": "run", "title": "Easy run",
             "minutes": 45, "intensity": "easy"} for i in range(0, 14, 2)]

    async def go() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=athlete_app), base_url=BASE) as a, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=coach_app), base_url=BASE) as c:
            await a.post("/app/api/coaches", headers=H, json={"email": COACH, "can_edit_plan": False})
            assert (await c.get("/app/api/coach/athletes")).status_code == 200
            # View-only coach: status works, nothing else.
            st = (await c.get(base)).json()
            assert st["can_edit"] is False and st["undo"] is None
            r = await c.post(f"{base}/rows", headers=H, json={"rows": rows})
            assert r.status_code == 400 and "access" in r.json()["error"]
            r = await c.post(f"{base}/file?name=plan.csv", headers=H, content=csv_template(today).encode())
            assert r.status_code == 400
            assert (await c.get(f"{base}/draft")).status_code == 400
            await a.patch(f"/app/api/coaches/{COACH}", headers=H, json={"can_edit_plan": True})
            # Draft: templates + current rows.
            dr = (await c.get(f"{base}/draft")).json()
            assert dr["rows"] == [] and set(dr["templates"]["weeks"]) == {"base", "build", "recovery"}
            tpl = await c.get(f"{base}/template.csv")
            assert tpl.status_code == 200 and tpl.text.startswith("date,sport,title,minutes,intensity,notes")
            # Grid rows -> preview -> apply.
            r = await c.post(f"{base}/rows", headers=H, json={"rows": rows, "name": "Base block"})
            assert r.status_code == 200, r.text
            pv = r.json()["preview"]
            assert pv["totals"]["sessions"] == 7 and pv["replaces"] is False and pv["source"] == "Rabbit"
            r = await c.post(f"{base}/{pv['id']}/apply", headers=H, json={})
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["plan"]["origin"]["by_name"] == "Bill Smith" and body["summary"]["weeks"] == 2
            # The athlete is told: push + a message from the coach, and sees the plan.
            assert push.sent and push.sent[-1][0] == "friend" and "loaded your plan: 2 weeks, starts" in push.sent[-1][2]
            th = (await a.get("/app/api/coachchat")).json()["threads"]
            assert th and "Bill loaded your plan: 2 weeks, starts" in th[0]["last"]["text"]
            mine = (await a.get("/app/api/plan")).json()["plan"]
            assert mine["origin"]["kind"] == "coach" and mine["weeks"]
            assert (await a.get("/app/api/plan/week")).status_code == 200
            ast = (await a.get("/app/api/plan/import")).json()
            assert ast["last"]["by_name"] == "Bill Smith" and ast["undo"]["by_name"] == "Bill Smith"
            # A preview can be applied once.
            assert (await c.post(f"{base}/{pv['id']}/apply", headers=H, json={})).status_code == 400
            # File upload (the CSV template) -> preview; undo the first import.
            r = await c.post(f"{base}/file?name=plan.csv&via=trainingpeaks", headers=H, content=csv_template(today).encode())
            assert r.status_code == 201 and r.json()["preview"]["source"] == "TrainingPeaks CSV"
            r = await c.post(f"{base}/undo", headers=H, json={})
            assert r.status_code == 200 and r.json()["plan"] is None
            assert "undid the plan" in push.sent[-1][2]
            # Coach accounts can't use the athlete's own import routes.
            assert (await c.get("/app/api/plan/import")).status_code == 403
            assert (await c.post("/app/api/plan/import/file?name=x.csv", headers=H, content=b"x")).status_code == 403
            # Removing the coach ends access.
            await a.request("DELETE", f"/app/api/coaches/{COACH}", headers=H, json={})
            assert (await c.get(base)).status_code == 400
    asyncio.run(go())


def test_ai_extraction_with_fake_backend(env, tmp_path) -> None:
    agent, _ = env.agent([])
    today = agent.plans.today("friend")
    agent.coach.update_athlete("friend", _athlete())
    agent.coach.create_goal("friend", {"title": "Race", "distance": "10k",
                                       "date": (today + timedelta(weeks=8)).isoformat()})
    seen: dict = {}

    async def structured(system, prompt, tool, **kw):
        seen.update(system=system, prompt=prompt, tool=tool["name"], kw=kw)
        return {"name": "Ten K", "sessions": [
            {"week": 1, "weekday": "tue", "sport": "run", "title": "Intervals", "minutes": 50, "intensity": "intervals",
             "notes": "6x800 at 5k pace"},
            {"week": 1, "weekday": "sat", "sport": "run", "title": "Long run", "minutes": 80},
            {"week": 2, "weekday": "thu", "sport": "strength", "title": "Gym"}],
            "warnings": ["Week 3 was cut off in the photo"]}
    agent._backend.structured = structured  # type: ignore[attr-defined]
    athlete_app, _ = _apps(env, tmp_path, agent)
    start = today + timedelta(days=(7 - today.weekday()) % 7 or 7)

    async def go() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=athlete_app), base_url=BASE) as a:
            r = await a.post(f"/app/api/plan/import/file?name=plan.pdf&start={start.isoformat()}", headers=H,
                             content=b"%PDF-1.4 fake plan")
            assert r.status_code == 201, r.text
            pv = r.json()["preview"]
            assert pv["source"] == "PDF (read by Rabbit)" and pv["name"] == "Ten K"
            assert pv["totals"]["sessions"] == 3 and pv["first_day"] == (start + timedelta(days=1)).isoformat()
            assert any("cut off" in w for w in pv["warnings"]) and any("no duration" in w for w in pv["warnings"])
            assert seen["tool"] == "save_training_plan" and seen["kw"]["max_tokens"] > 2000
            blocks = seen["prompt"]
            assert blocks[0]["type"] == "document" and blocks[0]["source"]["media_type"] == "application/pdf"
            facts = blocks[1]["text"]
            assert start.isoformat() in facts and "oura" not in str(blocks).lower() and "ftp" not in facts
            st = (await a.get("/app/api/plan/import")).json()
            assert st["ai_left"] == AI_PER_DAY - 1
            r = await a.post(f"/app/api/plan/import/{pv['id']}/apply", headers=H, json={})
            assert r.status_code == 200
            plan = r.json()["plan"]
            assert plan["origin"]["kind"] == "athlete"
            s = next(s for w in plan["weeks"] for d in w["days"] for s in d["sessions"] if s["title"] == "Intervals")
            assert s["kind"] == "vo2" and s["detail"] == "6x800 at 5k pace" and s["minutes"] == 50
            # Imported plans work everywhere a built plan does.
            for path in ("/app/api/today", f"/app/api/workout/today?session_id={s['id']}", "/app/api/plan/week",
                         "/app/api/stats", "/app/api/load"):
                assert (await a.get(path)).status_code == 200, path
            r = await a.patch(f"/app/api/plan/sessions/{s['id']}", headers=H, json={"minutes": 55})
            assert r.status_code == 200
            agent.plans._pause = 0
            r = await a.post("/app/api/plan/garmin/sync", headers=H, json={"days": 28})
            assert r.status_code == 200, r.text
            assert r.json()["result"]["uploaded"] >= 2 and not r.json()["result"]["errors"]
            # Daily allowance.
            for _ in range(AI_PER_DAY - 1):
                assert (await a.post("/app/api/plan/import/file?name=p.png", headers=H,
                                     content=b"\x89PNG\r\n\x1a\nxx")).status_code == 201
            r = await a.post("/app/api/plan/import/file?name=p.png", headers=H, content=b"\x89PNG\r\n\x1a\nxx")
            assert r.status_code == 400 and "used up" in r.json()["error"]
            # Model trouble is a friendly error, and a bad origin is refused.
            async def boom(*a, **k):
                raise RuntimeError("down")
            agent._backend.structured = boom  # type: ignore[attr-defined]
            assert (await a.post("/app/api/plan/import/file?name=x.txt", headers={"origin": "https://evil"},
                                 content=b"week 1 run")).status_code == 403
    asyncio.run(go())
