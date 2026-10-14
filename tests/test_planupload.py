"""Plan upload v2: header synonyms and column mapping, week grids, free-text durations and
distances, Zwift / ERG / MRC workouts, merge modes, date shifting, templates, CSV / iCal
export round trips, drafts and permissions."""

from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta

import httpx2
import pytest

from garmin_mcp.coaches import coach_user_id
from garmin_mcp.planbuilder import KINDS_BY_SPORT, garmin_workouts, iter_sessions
from garmin_mcp.planformats import (
    FormatError,
    compact_steps,
    export_csv,
    export_ics,
    find_week_grid,
    mapping_info,
    merge_plans,
    parse_distance,
    parse_erg,
    parse_zwo,
    shift_rows,
    template_catalog,
    template_rows,
    text_distance,
    text_minutes,
    week_day_from_name,
)
from garmin_mcp.planimport import (
    INTENSITIES,
    ImportService,
    PlanImportError,
    _header_map,
    build_import_plan,
    clean_rows,
    detect,
    parse_csv,
    parse_date,
    parse_ics,
    parse_minutes,
    table_rows,
    week_templates,
)
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_planimport import BASE, COACH, TODAY, H, _apps, _row
from tests.test_plans import _athlete

MON = date(2026, 10, 19)


def _csv(text: str, start: date | None = MON):
    got = parse_csv(text)
    assert got is not None, "header not recognized"
    rows, w2 = clean_rows(got[0], start=start)
    return rows, got[1] + w2


# --------------------------------------------------------------- durations --
def test_durations_in_cells_and_free_text() -> None:
    for v, want in (("1:15", 75), ("75'", 75), ("1h15", 75), ("45 min", 45), ("1h 15m", 75), ("90 mins", 90),
                    ("1.5 h", 90), ("2 hrs", 120), ("1:15:00", 75)):
        assert parse_minutes(v) == want or text_minutes(v) == want, v
    assert text_minutes("45' easy run") == 45 and text_minutes("Long ride 1h15 Z2") == 75
    assert text_minutes("3x10' tempo inside 60' total") == 60      # repeats aren't the total
    assert text_minutes("6x400m @ 4:30/km") is None                  # distances and paces aren't
    assert text_minutes("Swim 1500m") is None and text_minutes("Tempo 30m") == 30


def test_distances_with_units() -> None:
    assert text_distance("10k tempo") == (10000.0, "10k")
    assert text_distance("Easy 5 mi")[0] == pytest.approx(8046.72)
    assert text_distance("6x400m") is None and text_distance("Run 45m") is None
    assert parse_distance("1650 yd")[0] == pytest.approx(1508.76)
    assert parse_distance(6, "mi")[0] == pytest.approx(9656.064)
    assert parse_distance("1500m")[0] == 1500 and parse_distance("abc") is None


# ------------------------------------------------------- header synonyms --
def test_header_synonyms() -> None:
    text = ("Scheduled Date,Activity,Session Name,Duration (h:mm),Distance (mi),RPE,Description\n"
            "2026-10-20,Running,Easy,0:45,,3,Conversational\n"
            "2026-10-21,Ride,Sweet spot,1:15,,7,\n"
            "2026-10-22,Run,Long run,,10,,Fuel every 30'\n"
            "2026-10-23,Swim,Drills,45 min,,,\n")
    m = _header_map(next(iter(parse_csv_table(text))))
    assert {"date", "sport", "title", "duration", "distance", "rpe", "notes"} <= set(m)
    rows, warns = _csv(text)
    by = {r["date"]: r for r in rows}
    assert by["2026-10-20"]["minutes"] == 45 and by["2026-10-20"]["kind"] == "easy"
    assert by["2026-10-21"]["minutes"] == 75 and by["2026-10-21"]["kind"] == "threshold"   # RPE 7
    long = by["2026-10-22"]
    assert long["minutes"] == 95 and long["notes"].startswith("10 mi") and "estimated" in long["warn"]
    assert any("only a distance" in w for w in warns)
    assert by["2026-10-23"]["minutes"] == 45
    # Zone numbers in an intensity column; week + day + hours columns.
    rows, _ = _csv("Wk,Day,Type,Workout,Hrs,Zone\n1,Tue,Run,Intervals,1,5\n1,Thu,Bike,Steady,1.5,2\n")
    assert [(r["date"], r["minutes"], r["kind"]) for r in rows] == [
        ("2026-10-20", 60, "vo2"), ("2026-10-22", 90, "easy")]


def parse_csv_table(text: str):
    import csv
    import io
    return list(csv.reader(io.StringIO(text)))


def test_unknown_headers_ask_for_a_mapping(env) -> None:
    agent, _ = env.agent([])
    imp = ImportService(env.store, agent.plans, agent.coach)
    text = ("Quand,Sport,Séance,Durée\n2026-10-20,course,Footing,45\n2026-10-22,vélo,Sortie longue,120\n"
            "2026-10-24,course,Fractionné,50\n").encode()
    got = imp.rows_from_file(detect(text, "plan.csv"), text)
    assert isinstance(got, dict) and got["mapping"]["guess"]["date"] == 0 and got["mapping"]["guess"]["title"] == 2
    assert isinstance(got, dict) and "mapping" in got
    info = got["mapping"]
    assert info["headers"][:2] == ["Quand", "Sport"] and info["guess"]["sport"] == 1
    assert info["guess"]["duration"] == 3 and len(info["sample"]) == 3
    rows, _ = imp.rows_from_file("csv", text, mapping={"header_row": 0, "cols": {
        "date": 0, "sport": 1, "title": 2, "duration": 3}})
    cleaned, warns = clean_rows(rows)
    assert len(cleaned) == 3 and cleaned[0]["minutes"] == 45 and cleaned[1]["minutes"] == 120
    with pytest.raises(PlanImportError):
        imp.rows_from_file("csv", text, mapping={"header_row": 0, "cols": {"sport": 1}})
    # Prose with commas still goes to the model.
    assert imp.rows_from_file("csv", b"Week 1: Mon rest, Tue 6x400, Thu easy 40'\nWeek 2: more of the same, longer\n") is None


def test_mapping_info_guesses() -> None:
    info = mapping_info([["When", "What", "How long", "Notes"], ["2026-10-20", "Run", "45", ""]], _header_map)
    assert info["guess"]["date"] == 0 and info["guess"]["notes"] == 3 and info["guess"]["title"] == 1


# ---------------------------------------------------------------- grids --
GRID = ("Week,Mon,Tue,Wed,Thu,Fri,Sat,Sun,Total\n"
        "Week 1,Rest,45' easy run,Bike 1h threshold,30' easy run + strides,Off,2h long ride,75' long run,\n"
        "Week 2,Rest,\"6x400m track, 50 min\",Swim 45 min drills,40' easy run,-,Long ride 2h30 / Run 20',90' long run,\n"
        "Total,,,,,,,,10h\n")


def test_week_grid_detection() -> None:
    table = parse_csv_table(GRID)
    assert find_week_grid(table) == (0, {0: 1, 1: 2, 2: 3, 3: 4, 4: 5, 5: 6, 6: 7})
    assert table_rows(table) is None
    rows, warns = _csv_grid(GRID)
    by = {(r["date"], r["title"]): r for r in rows}
    assert len(rows) == 11 and not [w for w in warns if "skipped" in w]
    assert by[("2026-10-20", "45' easy run")]["minutes"] == 45
    assert by[("2026-10-21", "Bike 1h threshold")]["kind"] == "threshold"
    assert by[("2026-10-24", "2h long ride")]["sport"] == "bike" and by[("2026-10-24", "2h long ride")]["minutes"] == 120
    assert by[("2026-10-27", "6x400m track, 50 min")]["minutes"] == 50
    sat = [r for r in rows if r["date"] == "2026-10-31"]
    assert [(r["sport"], r["minutes"]) for r in sat] == [("bike", 150), ("run", 20)]
    # Week labels that are dates anchor the weeks without a start.
    dated = "Week of,Monday,Tuesday,Wednesday,Thursday,Friday,Saturday,Sunday\n10/19/2026,,Easy run 40',,,,,Long run 1:30\n"
    rows, _ = _csv_grid(dated, start=None)
    assert [(r["date"], r["minutes"]) for r in rows] == [("2026-10-20", 40), ("2026-10-25", 90)]


def _csv_grid(text: str, start: date | None = MON):
    from garmin_mcp.planformats import week_grid_rows
    got = week_grid_rows(parse_csv_table(text), parse_date)
    assert got is not None
    rows, w = clean_rows(got[0], start=start)
    return rows, got[1] + w


def test_grid_sport_guess_and_issues() -> None:
    text = "Week,Mon,Tue,Wed,Thu,Fri,Sat,Sun\n1,,Easy run 40',Tempo 45',Easy run 30',,8 mi,Long run 90'\n"
    from garmin_mcp.planformats import week_grid_rows
    issues: list = []
    rows, warns = clean_rows(week_grid_rows(parse_csv_table(text), parse_date)[0], start=MON, issues=issues)
    assert all(r["sport"] == "run" for r in rows) and len(rows) == 5 and not issues
    tempo = next(r for r in rows if r["title"] == "Tempo 45'")
    assert "guessed" in tempo["warn"] and next(r for r in rows if r["title"] == "8 mi")["minutes"] == 75
    # Nothing to go on: skipped, and listed as an issue the app can fix.
    rows, warns = clean_rows([{"line": 3, "date": "2026-10-20", "title": "Something"},
                              {"line": 4, "date": "nope", "sport": "run", "title": "x"}], issues=issues)
    assert not rows and sorted(i["line"] for i in issues) == [3, 4]
    assert next(i for i in issues if i["line"] == 3)["title"] == "Something"
    assert "sport" in next(i for i in issues if i["line"] == 3)["reason"].lower()


# ------------------------------------------------------------- workouts --
ZWO = b"""<workout_file><author>Coach</author><name>Over-unders</name>
<description>3 sets</description><sportType>bike</sportType><workout>
<Warmup Duration="600" PowerLow="0.40" PowerHigh="0.75"/>
<IntervalsT Repeat="4" OnDuration="120" OffDuration="60" OnPower="1.05" OffPower="0.55"/>
<SteadyState Duration="300" Power="0.88"/>
<SteadyState Duration="300" Power="0.88"/>
<FreeRide Duration="300"/>
<Cooldown Duration="300" PowerLow="0.65" PowerHigh="0.40"/>
</workout></workout_file>"""


def test_zwo_parsing_into_steps() -> None:
    w = parse_zwo(ZWO)
    assert w["name"] == "Over-unders" and w["sport"] == "bike" and w["minutes"] == 42
    st = w["steps"]
    assert st[0] == {"type": "warmup", "minutes": 10.0, "zone": 2, "pct": 57}
    assert st[1]["type"] == "repeat" and st[1]["reps"] == 4
    assert st[1]["steps"] == [{"type": "work", "minutes": 2.0, "zone": 4, "pct": 105},
                              {"type": "recover", "minutes": 1.0, "zone": 1, "pct": 55}]
    assert st[2] == {"type": "steady", "minutes": 10.0, "zone": 3, "pct": 88}    # merged
    assert st[3]["type"] == "steady" and "pct" not in st[3] and st[-1]["type"] == "cooldown"
    rows, warns = clean_rows([{"date": "2026-10-20", "sport": "bike", "title": w["name"], "minutes": w["minutes"],
                               "intensity": "threshold", "steps": w["steps"]}])
    assert not warns and rows[0]["steps"][1]["steps"][0]["pct"] == 105
    with pytest.raises(FormatError):
        parse_zwo(b"<!DOCTYPE x [<!ENTITY a 'b'>]><workout_file/>")
    with pytest.raises(FormatError):
        parse_zwo(b"<workout_file><workout></workout></workout_file>")
    run = parse_zwo(b"<workout_file><sportType>run</sportType><workout><SteadyState Duration='1800' Power='0.8'/></workout></workout_file>")
    assert run["sport"] == "run" and run["minutes"] == 30


def test_erg_and_mrc_parsing() -> None:
    erg = (b"[COURSE HEADER]\nVERSION = 2\nUNITS = ENGLISH\nDESCRIPTION = Threshold\nFILE NAME = 2x20.erg\nFTP = 250\n"
           b"MINUTES WATTS\n[END COURSE HEADER]\n[COURSE DATA]\n0 100\n10 180\n10 240\n30 240\n30 125\n35 125\n"
           b"35 240\n55 240\n55 120\n65 100\n[END COURSE DATA]\n")
    w = parse_erg(erg)
    assert w["name"] == "2x20" and w["minutes"] == 65
    types = [s["type"] for s in w["steps"]]
    assert types[0] == "warmup" and types[-1] == "cooldown" and types.count("work") == 2
    assert w["steps"][1] == {"type": "work", "minutes": 20.0, "zone": 4, "pct": 96}
    mrc = (b"[COURSE HEADER]\nMINUTES PERCENT\n[END COURSE HEADER]\n[COURSE DATA]\n0 50\n5 50\n5 110\n8 110\n"
           b"8 50\n10 50\n[END COURSE DATA]\n")
    m = parse_erg(mrc)
    assert [s["pct"] for s in m["steps"]] == [50, 110, 50] and m["minutes"] == 10
    nofpt = parse_erg(erg.replace(b"FTP = 250\n", b""))
    assert nofpt["warning"] and parse_erg(erg.replace(b"FTP = 250\n", b""), ftp=300)["steps"][1]["pct"] == 80
    assert detect(erg, "x.erg") == "erg" and detect(mrc, "x.mrc") == "erg" and detect(ZWO, "a.zwo") == "zwo"
    with pytest.raises(FormatError):
        parse_erg(b"[COURSE HEADER]\n[END COURSE HEADER]\n")


def test_workout_pct_targets_reach_garmin() -> None:
    w = parse_zwo(ZWO)
    rows, _ = clean_rows([{"date": MON.isoformat(), "sport": "bike", "title": "Over-unders", "minutes": 42,
                           "intensity": "threshold", "steps": w["steps"]}])
    plan, _ = build_import_plan(rows, today=TODAY, athlete=_athlete(), goal=None, origin={})
    s = plan["weeks"][0]["days"][MON.isoformat()][0]
    wo = garmin_workouts(s, {"ftp_w": 200})[0]
    rep = wo["workoutSegments"][0]["workoutSteps"][1]
    work = rep["workoutSteps"][0]
    assert (work["targetValueOne"], work["targetValueTwo"]) == (204, 216)   # 105% +-3%
    plain = garmin_workouts(s, {})[0]["workoutSegments"][0]["workoutSteps"][0]
    assert plain["targetType"]["workoutTargetTypeKey"] == "heart.rate.zone"


def test_compact_steps_and_names() -> None:
    many = [{"type": "work", "minutes": 1, "zone": 5}, {"type": "recover", "minutes": 1, "zone": 1}] * 40
    st = compact_steps(many)
    assert st == [{"type": "repeat", "reps": 30, "steps": many[:2]}, {"type": "repeat", "reps": 10, "steps": many[:2]}]
    assert compact_steps([{"type": "steady", "minutes": 1, "zone": z % 5 + 1} for z in range(25)]) is None
    assert week_day_from_name("Week 3 Day 2 - Tempo.zwo") == (3, 1) and week_day_from_name("W10D7.erg") == (10, 6)
    assert week_day_from_name("Tempo.zwo") is None


def test_fit_and_links_get_clear_messages() -> None:
    fit = b"\x0e\x10\x00\x00\x00\x00\x00\x00.FIT" + b"\x00" * 20
    with pytest.raises(PlanImportError, match=r"\.zwo"):
        detect(fit, "workout.fit")
    with pytest.raises(PlanImportError, match="File → Download → CSV"):
        detect(b"https://docs.google.com/spreadsheets/d/abc/edit#gid=0\n", "pasted.txt")
    with pytest.raises(PlanImportError, match="File → Download → PDF"):
        detect(b"  https://docs.google.com/document/d/abc/edit  ", "pasted.txt")
    with pytest.raises(PlanImportError, match="can't open links"):
        detect(b"https://example.com/plan", "pasted.txt")
    assert detect(b"Week 1\nMon rest\nTue 6x400 see https://docs.google.com/x\n", "pasted.txt") == "text"
    assert detect(b"date\tsport\ttitle\n2026-10-20\trun\tEasy\n", "pasted.txt") == "csv"


# ------------------------------------------------------- merge + shift --
def _plan(rows):
    p, _ = build_import_plan(rows, today=TODAY, athlete=_athlete(), goal=None, origin={"kind": "athlete"})
    return p


def test_merge_modes() -> None:
    old = _plan([_row(MON, "run", 45, "Easy"), _row(MON + timedelta(days=7), "bike", 60, "Ride"),
                 _row(MON + timedelta(days=14), "swim", 40, "Swim")])
    for _, _, s in iter_sessions(old):
        if s["sport"] == "bike":
            s["garmin"] = {"workout_ids": [5], "hash": "x"}
    new = _plan([_row(MON + timedelta(days=8), "strength", 30, "Gym", "strength")])
    assert merge_plans(old, new, "replace", TODAY) is new

    def sessions(p):
        return sorted((d, s["title"]) for _, d, s in iter_sessions(p) if s["sport"] != "rest")
    added = merge_plans(old, new, "add", TODAY)
    assert sessions(added) == [(MON.isoformat(), "Easy"), ((MON + timedelta(days=7)).isoformat(), "Ride"),
                               ((MON + timedelta(days=8)).isoformat(), "Gym"), ((MON + timedelta(days=14)).isoformat(), "Swim")]
    assert not any(s.get("garmin") for _, _, s in iter_sessions(added))     # re-synced
    assert added["start"] == MON.isoformat() and [w["index"] for w in added["weeks"]] == [1, 2, 3]
    weeks = merge_plans(old, new, "weeks", TODAY)
    assert sessions(weeks) == [(MON.isoformat(), "Easy"), ((MON + timedelta(days=8)).isoformat(), "Gym"),
                               ((MON + timedelta(days=14)).isoformat(), "Swim")]
    full = _plan([_row(MON, "run", 30, f"R{i}") for i in range(4)])
    with pytest.raises(FormatError, match="up to 4 a day"):
        merge_plans(full, _plan([_row(MON, "bike", 30, "B")]), "add", TODAY)
    assert merge_plans(None, new, "add", TODAY) is new


def test_shift_dates() -> None:
    rows = [{"date": "2026-10-20", "sport": "run"}, {"date": "2026-10-31", "sport": "bike"}]
    assert [r["date"] for r in shift_rows(rows, 7)] == ["2026-10-27", "2026-11-07"]
    assert [r["date"] for r in shift_rows(rows, -1)] == ["2026-10-19", "2026-10-30"]
    assert rows[0]["date"] == "2026-10-20"


# ------------------------------------------------------------- templates --
def test_templates_are_generated_for_the_athlete() -> None:
    cat = {t["id"]: t for t in template_catalog()}
    assert {"5k", "10k", "half", "marathon", "50k", "100mi", "sprint", "olympic", "70.3", "140.6", "century",
            "base8", "strength"} == set(cat)
    assert cat["strength"]["mode"] == "add"
    small, big = _athlete(weekly_hours=4, level="new"), _athlete(weekly_hours=9, level="advanced")

    def hours(rows):
        return sum(r["minutes"] or 0 for r in rows) / 60
    m_small, name = template_rows("marathon", small, None, today=TODAY, start=MON, week_templates=week_templates)
    m_big, _ = template_rows("marathon", big, None, today=TODAY, start=MON, week_templates=week_templates)
    assert name == "Marathon plan" and hours(m_small) < hours(m_big)
    assert min(r["date"] for r in m_small) >= MON.isoformat()
    assert max(r["date"] for r in m_small) == (MON + timedelta(weeks=16, days=-1)).isoformat()
    race = [r for r in m_small if r["kind"] == "race"]
    assert race and race[0]["title"] == "Race day: Marathon"
    tri, _ = template_rows("70.3", big, None, today=TODAY, start=MON, week_templates=week_templates)
    assert {"swim", "bike", "run"} <= {r["sport"] for r in tri}
    rows, warns = clean_rows(tri)
    assert len(rows) == len(tri) and not [w for w in warns if "skipped" in w]
    for r in rows:
        assert r["kind"] in KINDS_BY_SPORT[r["sport"]] or r["kind"] == "race"
    base, _ = template_rows("base8", big, None, today=TODAY, start=MON, week_templates=week_templates)
    per_week = [sum(r["minutes"] for r in base if MON + timedelta(weeks=w) <= date.fromisoformat(r["date"]) < MON + timedelta(weeks=w + 1))
                for w in range(8)]
    assert per_week[3] < per_week[2] and per_week[7] < per_week[6]          # recovery weeks
    st, _ = template_rows("strength", _athlete(available_days=["mon", "wed", "fri", "sat"], long_day="sat"), None,
                          today=TODAY, start=MON, week_templates=week_templates)
    assert {r["sport"] for r in st} == {"strength"} and len(st) == 8 * 3 - 2
    assert not any(date.fromisoformat(r["date"]).weekday() == 5 for r in st)   # not on the long day
    short, _ = template_rows("5k", small, None, today=TODAY, start=MON, weeks=4, week_templates=week_templates)
    assert max(r["date"] for r in short) <= (MON + timedelta(weeks=4)).isoformat()
    with pytest.raises(FormatError):
        template_rows("nope", small, None, today=TODAY, start=MON, week_templates=week_templates)


# ----------------------------------------------------------------- export --
def test_csv_and_ics_export_round_trip(env) -> None:
    agent, _ = env.agent([])
    agent.coach.update_athlete("friend", _athlete())
    today = agent.plans.today("friend")
    agent.coach.create_goal("friend", {"title": "Race", "distance": "olympic triathlon",
                                       "date": (today + timedelta(weeks=10)).isoformat()})
    plan = agent.plans.build("friend")
    want = sorted((d, s["sport"], s["title"], s.get("minutes")) for _, d, s in iter_sessions(plan) if s["sport"] != "rest")
    text = export_csv(plan, tuple(INTENSITIES))
    assert text.startswith("date,sport,title,minutes,intensity,notes\n")
    rows, warns = _csv(text, start=None)
    assert not [w for w in warns if "skipped" in w]
    assert sorted((r["date"], r["sport"], r["title"], r["minutes"]) for r in rows) == want
    ics = export_ics(plan, name="Olympic, Tri")
    assert "X-WR-CALNAME:Olympic\\, Tri" in ics and all(len(x.encode()) <= 75 for x in ics.split("\r\n"))
    raw, _ = parse_ics(ics)
    rows, warns = clean_rows(raw)
    got = sorted((r["date"], r["sport"], r["title"], r["minutes"]) for r in rows)
    assert got == [(d, sp, t, None if sp == "rest" else m) for d, sp, t, m in want]


# -------------------------------------------------------------- service --
def test_preview_update_latest_and_modes(env) -> None:
    agent, _ = env.agent([])
    today = agent.plans.today("friend")
    agent.coach.update_athlete("friend", _athlete())
    agent.coach.create_goal("friend", {"title": "Race", "distance": "half marathon",
                                       "date": (today + timedelta(weeks=12)).isoformat()})
    agent.plans.build("friend")
    imp = ImportService(env.store, agent.plans, agent.coach)
    start = today + timedelta(days=(7 - today.weekday()) % 7 or 7)
    raw = [{"date": (start + timedelta(days=1)).isoformat(), "sport": "strength", "title": "Gym", "minutes": 30},
           {"date": (start + timedelta(days=3)).isoformat(), "title": "Mystery"}]
    pv = imp.preview("friend", raw, actor="friend", source="CSV", mode="add")
    assert pv["mode"] == "add" and pv["has_plan"] and pv["totals"]["removed"] == 0 and pv["totals"]["added"] == 1
    assert len(pv["rows"]) == 1 and pv["issues"][0]["title"] == "Mystery" and pv["skipped"] == 1
    # Edit: fix the issue as a row, duplicate, shift, switch to replace weeks.
    rows = pv["rows"] + [{"date": (start + timedelta(days=3)).isoformat(), "sport": "run", "title": "Mystery run",
                          "minutes": 40, "intensity": "easy"}]
    rows = shift_rows(rows + [dict(pv["rows"][0])], 7)
    up = imp.update("friend", pv["id"], rows, actor="friend", mode="weeks", issues=[])
    assert up["id"] == pv["id"] and up["mode"] == "weeks" and up["issues"] == []
    assert [r["date"] for r in up["rows"]].count((start + timedelta(days=8)).isoformat()) == 2
    assert up["totals"]["removed"] > 0       # the rest of that week of the built plan is replaced
    with pytest.raises(PlanImportError):
        imp.update("friend", pv["id"], rows, actor="coach_x")
    with pytest.raises(PlanImportError, match="no sessions left"):
        imp.update("friend", pv["id"], [], actor="friend")
    # The draft comes back (same id) until it's applied.
    again = imp.latest("friend", "friend")
    assert again is not None and again["id"] == pv["id"] and again["mode"] == "weeks"
    assert imp.latest("friend", "someone") is None
    plan, summary = imp.apply("friend", pv["id"], actor="friend", actor_name="Me", actor_role="athlete")
    assert summary["mode"] == "weeks"
    titles = [s["title"] for _, d, s in iter_sessions(plan)]
    assert "Mystery run" in titles and titles.count("Gym") == 2
    assert any(s["sport"] == "run" and s["title"] != "Mystery run" for _, d, s in iter_sessions(plan)
               if d >= (start + timedelta(weeks=2)).isoformat())          # later weeks kept
    assert imp.latest("friend", "friend") is None
    # Dates in the past move to next week, same weekdays.
    old = [{"date": "2025-03-04", "sport": "run", "title": "Tue", "minutes": 30},
           {"date": "2025-03-09", "sport": "run", "title": "Sun", "minutes": 60}]
    pv = imp.preview("friend", old, actor="friend", source="CSV")
    nm = today + timedelta(days=(7 - today.weekday()) % 7)
    assert [r["date"] for r in pv["rows"]] == [(nm + timedelta(days=1)).isoformat(), (nm + timedelta(days=6)).isoformat()]
    assert "already passed" in pv["warnings"][0]


# ------------------------------------------------------------------- API --
def test_upload_api_formats_templates_export_and_permissions(env, tmp_path) -> None:
    agent, _ = env.agent([])
    today = agent.plans.today("friend")
    agent.coach.update_athlete("friend", _athlete(ftp_w=250))
    agent.coach.create_goal("friend", {"title": "Race", "distance": "marathon",
                                       "date": (today + timedelta(weeks=16)).isoformat()})
    agent.plans.build("friend")
    athlete_app, coach_app = _apps(env, tmp_path, agent)
    own = "/app/api/plan/import"
    base = "/app/api/coach/athletes/friend/plan/import"

    async def go() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=athlete_app), base_url=BASE) as a, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=coach_app), base_url=BASE) as c:
            # A week grid, pasted as TSV.
            tsv = GRID.replace(",", "\t").replace('"6x400m track\t 50 min"', "6x400m track 50 min")
            r = await a.post(f"{own}/file?name=pasted.txt", headers=H, content=tsv.encode())
            assert r.status_code == 201, r.text
            pv = r.json()["preview"]
            assert pv["totals"]["sessions"] == 11 and pv["name"] is None and "week grid" in pv["warnings"][0]
            # Unknown columns: a mapping step, then the same file with the mapping.
            odd = b"Quand,Sport,Seance,Duree\n2026-11-03,run,Footing,45\n2026-11-05,bike,Velo,90\n2026-11-07,run,Long,100\n"
            r = await a.post(f"{own}/file?name=fr.csv", headers=H, content=odd)
            assert r.status_code == 200 and r.json()["mapping"]["name"] == "fr.csv"
            m = json.dumps({"header_row": 0, "cols": {"date": 0, "sport": 1, "title": 2, "duration": 3}})
            r = await a.post(f"{own}/file?name=fr.csv&map={m}", headers=H, content=odd)
            assert r.status_code == 201 and r.json()["preview"]["totals"]["sessions"] == 3
            # Several files in one request: a Zwift workout named by week/day + a CSV.
            csv = b"date,sport,title,minutes\n2026-11-04,swim,Drills,40\n"
            q = f"name=W1D3%20Over.zwo&name=more.csv&size={len(ZWO)}&size={len(csv)}&mode=replace"
            start = (today + timedelta(days=(7 - today.weekday()) % 7 or 7)).isoformat()
            r = await a.post(f"{own}/file?{q}&start={start}", headers=H, content=ZWO + csv)
            assert r.status_code == 201, r.text
            pv = r.json()["preview"]
            zw = next(x for x in pv["rows"] if x["title"] == "Over-unders")
            assert zw["date"] == (date.fromisoformat(start) + timedelta(days=2)).isoformat() and zw["steps"]
            assert pv["source"] == "files"
            # A single workout file onto an existing plan defaults to "add".
            r = await a.post(f"{own}/file?name=o.zwo", headers=H, content=ZWO)
            pv = r.json()["preview"]
            assert pv["mode"] == "add" and pv["suggested_mode"] == "add" and pv["totals"]["removed"] == 0
            assert pv["rows"][0]["date"] == (today + timedelta(days=1)).isoformat()
            r = await a.post(f"{own}/file?name=w.fit", headers=H, content=b"\x0e\x10" + b"\x00" * 6 + b".FIT" + b"\x00" * 8)
            assert r.status_code == 400 and ".zwo" in r.json()["error"]
            r = await a.post(f"{own}/file?name=pasted.txt", headers=H, content=b"https://docs.google.com/spreadsheets/d/x/edit")
            assert r.status_code == 400 and "Download" in r.json()["error"]
            r = await a.post(f"{own}/file?name=x.csv&size=5&size=5", headers=H, content=b"abc")
            assert r.status_code == 400
            # Templates.
            t = (await a.get(f"{own}/templates")).json()
            assert len(t["templates"]) == 13 and t["groups"][0]["id"] == "run"
            r = await a.post(f"{own}/template/10k", headers=H, json={})
            assert r.status_code == 200, r.text
            pv = r.json()["preview"]
            assert pv["name"] == "10K plan" and pv["source"] == "Template" and pv["mode"] == "replace"
            nm = today + timedelta(days=(7 - today.weekday()) % 7)
            assert pv["totals"]["weeks"] == 10 and nm.isoformat() <= pv["first_day"] < (nm + timedelta(days=7)).isoformat()
            r = await a.post(f"{own}/template/strength", headers=H, json={})
            assert r.json()["preview"]["mode"] == "add"
            assert (await a.post(f"{own}/template/nope", headers=H, json={})).status_code == 400
            # Draft: edit, come back to it, apply.
            pv = r.json()["preview"]
            rows = pv["rows"][:3]
            r = await a.post(f"{own}/{pv['id']}/update", headers=H, json={"rows": rows, "mode": "add"})
            assert r.status_code == 200 and r.json()["preview"]["totals"]["added"] == 3
            got = (await a.get(f"{own}/pending")).json()["preview"]
            assert got["id"] == pv["id"] and len(got["rows"]) == 3
            assert (await a.post(f"{own}/{pv['id']}/update", headers=H, json={"rows": rows, "mode": "bogus"})).status_code == 400
            r = await a.post(f"{own}/{pv['id']}/apply", headers=H, json={})
            assert r.status_code == 200 and r.json()["summary"]["mode"] == "add"
            # Export.
            r = await a.get(f"{own}/export.csv")
            assert r.status_code == 200 and r.text.startswith("date,sport,title") and "attachment" in r.headers["content-disposition"]
            assert "Strength" in r.text
            r = await a.get(f"{own}/export.ics")
            assert r.status_code == 200 and r.text.startswith("BEGIN:VCALENDAR") and "text/calendar" in r.headers["content-type"]
            assert (await a.get(f"{own}/export.pdf")).status_code == 404
            # Coach: view-only can export but not load; edit access can use the same flow.
            await a.post("/app/api/coaches", headers=H, json={"email": COACH, "can_edit_plan": False})
            assert (await c.get(f"{base}/export.csv")).status_code == 200
            assert (await c.get(f"{base}/templates")).status_code == 400
            assert (await c.post(f"{base}/template/5k", headers=H, json={})).status_code == 400
            assert (await c.get(f"{base}/pending")).status_code == 400
            await a.patch(f"/app/api/coaches/{COACH}", headers=H, json={"can_edit_plan": True})
            r = await c.post(f"{base}/template/5k", headers=H, json={"mode": "replace"})
            assert r.status_code == 200
            cpv = r.json()["preview"]
            # Drafts are per actor: the athlete can't touch the coach's.
            assert (await a.post(f"{own}/{cpv['id']}/update", headers=H, json={"rows": cpv["rows"]})).status_code == 400
            assert (await c.get(f"{base}/pending")).json()["preview"]["id"] == cpv["id"]
            assert (await c.post(f"{base}/{cpv['id']}/discard", headers=H, json={})).status_code == 200
            assert (await c.get(f"{base}/pending")).json()["preview"] is None
            # Coach accounts get 403 on the athlete's own routes.
            for path in ("/export.csv", "/export.ics", "/pending", "/templates"):
                assert (await c.get(own + path)).status_code == 403, path
            assert (await c.post(f"{own}/template/5k", headers=H, json={})).status_code == 403
            assert (await c.post(f"{own}/{cpv['id']}/update", headers=H, json={"rows": []})).status_code == 403
            # A coach for someone else gets nothing.
            await a.request("DELETE", f"/app/api/coaches/{COACH}", headers=H, json={})
            assert (await c.get(f"{base}/export.csv")).status_code == 400
            # The athlete's own plan download needs a plan.
    asyncio.run(go())
    assert coach_user_id(COACH).startswith("coach_")
