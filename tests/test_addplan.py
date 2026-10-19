"""Add a plan v3: header synonyms and duration/distance cells, week + weekday scheduling,
"When does it start?" (next Monday / a date / end on race day), merge vs fill vs replace and
conflicts, Word / OpenDocument / multi-sheet workbooks, Google Sheets/Docs links (allowlist,
redirects, size cap), several photos in one model call, a coach's own templates, and
permissions."""

from __future__ import annotations

import asyncio
import io
import json
import zipfile
from datetime import date, timedelta

import httpx2
import pytest

from garmin_mcp import planlinks
from garmin_mcp.coaches import coach_user_id
from garmin_mcp.planbuilder import iter_sessions
from garmin_mcp.planformats import (
    FormatError,
    align_rows,
    conflicts,
    docx_content,
    from_relative,
    merge_plans,
    ods_tables,
    template_rows,
    to_relative,
    zip_kind,
)
from garmin_mcp.planimport import (
    ImportService,
    PlanImportError,
    _header_map,
    build_import_plan,
    clean_rows,
    detect,
    parse_csv,
    parse_minutes,
    rows_from_file,
    week_templates,
)
from garmin_mcp.planlinks import (
    LinkError,
    fetch_google,
    google_export_url,
    html_text,
    redirect_ok,
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


# ------------------------------------------------- headers and durations --
def test_header_synonyms_any_order() -> None:
    m = _header_map(["Notes", "Time", "Name", "Workout Date", "Type", "Zone", "Distance (km)"])
    assert m == {"notes": [0], "duration": [1], "title": [2], "date": [3], "sport": [4], "intensity": [5],
                 "distance": [6]}
    m = _header_map(["Details", "Minutes", "Activity", "Day", "Week", "Workout", "RPE"])
    assert {"notes", "minutes", "sport", "weekday", "week", "title", "rpe"} == set(m)
    text = ("Details,Time,Workout,Workout Date,Activity,Zone\n"
            "Easy,1:30:00,Long ride,2026-10-24,Cycling,2\n"
            "Hills,45:00,Hill repeats,2026-10-21,Running,5\n"
            ",1h 30m,Long run,2026-10-25,Run,\n"
            ",90 min,Swim,2026-10-22,Swim,3\n")
    rows, warns = _csv(text)
    by = {r["date"]: r for r in rows}
    assert by["2026-10-24"]["minutes"] == 90 and by["2026-10-24"]["sport"] == "bike" and by["2026-10-24"]["kind"] == "easy"
    assert by["2026-10-21"]["minutes"] == 45 and by["2026-10-21"]["kind"] == "vo2"
    assert by["2026-10-25"]["minutes"] == 90 and by["2026-10-22"]["minutes"] == 90
    assert by["2026-10-21"]["notes"] == "Hills"
    assert not [w for w in warns if "skipped" in w]


def test_duration_and_distance_cells() -> None:
    for v, want in (("1:30:00", 90), ("45:00", 45), ("1h 30m", 90), ("90 min", 90), ("1.5h", 90),
                    ("2 hours", 120), ("75'", 75), ("1h30", 90)):
        assert parse_minutes(v) == want, v
    assert parse_minutes(1.25, hours=True) == 75 and parse_minutes("1.25", hours=True) == 75
    # Decimal hours column, distance in miles / meters / yards from header or cell.
    rows, warns = _csv("Date,Sport,Title,Hours,Distance (mi)\n2026-10-20,run,Easy,0.75,\n2026-10-22,run,Long,,10\n")
    assert rows[0]["minutes"] == 45 and rows[1]["notes"].startswith("10 mi") and rows[1]["minutes"] == 95
    rows, _ = _csv("Date,Sport,Title,Distance\n2026-10-20,swim,Main set,1650 yd\n2026-10-21,run,Track,5000m\n"
                   "2026-10-23,bike,Ride,40 km\n")
    assert [r["minutes"] for r in rows] == [30, 30, 80]


# ---------------------------------------------------- week / day + start --
def test_week_and_day_of_week_with_a_start_date() -> None:
    text = "Week,Day,Workout,Time\nWeek 1,Tue,Easy run,40\nWeek 1,Sat,Long run,1:30\nWeek 3,Thursday,Tempo run,50\n"
    rows, warns = _csv(text, start=MON)
    assert [(r["date"], r["minutes"]) for r in rows] == [("2026-10-20", 40), ("2026-10-24", 90), ("2026-11-05", 50)]
    rows, warns = _csv(text, start=None)
    assert not rows and any("needs a start date" in w for w in warns)


def test_align_next_monday_date_and_race_day() -> None:
    rows = [{"date": "2026-11-03", "sport": "run", "title": "A"}, {"date": "2026-11-15", "sport": "run", "title": "Race",
                                                                    "kind": "race"}]
    got, note = align_rows(rows, "monday", today=TODAY)
    assert [r["date"] for r in got] == ["2026-10-20", "2026-11-01"] and note is None
    got, _ = align_rows(rows, "date", today=TODAY, on=date(2026, 12, 2))     # a Wednesday: its Monday week
    assert [r["date"] for r in got] == ["2026-12-01", "2026-12-13"]
    # Race on a Sunday, plan's race session on a Sunday: exact.
    got, note = align_rows(rows, "race", today=TODAY, race_date=date(2027, 1, 10))
    assert got[-1]["date"] == "2027-01-10" and got[0]["date"] == "2026-12-29" and note is None
    # The race session is the anchor even when something comes after it.
    after = rows + [{"date": "2026-11-16", "sport": "run", "title": "Shakeout"}]
    got, _ = align_rows(after, "race", today=TODAY, race_date=date(2027, 1, 10))
    assert got[1]["date"] == "2027-01-10" and got[2]["date"] == "2027-01-11"
    # Race on a Saturday: whole weeks, weekdays kept, and the note says so.
    got, note = align_rows(rows, "race", today=TODAY, race_date=date(2027, 1, 9))
    assert got[-1]["date"] == "2027-01-10" and "Saturday" in note
    # Race closer than the plan is long: the first weeks are behind us.
    long = [{"date": (MON + timedelta(weeks=w)).isoformat(), "sport": "run", "title": f"W{w}"} for w in range(10)]
    got, note = align_rows(long, "race", today=TODAY, race_date=MON + timedelta(weeks=5))
    assert got[-1]["date"] == (MON + timedelta(weeks=5)).isoformat() and "already behind you" in note
    with pytest.raises(FormatError):
        align_rows(rows, "race", today=TODAY, race_date=None)
    with pytest.raises(FormatError):
        align_rows(rows, "sideways", today=TODAY)


def _plan(rows):
    p, _ = build_import_plan(rows, today=TODAY, athlete=_athlete(), goal=None, origin={"kind": "athlete"})
    return p


def test_fill_empty_days_vs_replace_and_conflicts() -> None:
    old = _plan([_row(MON, "run", 45, "Easy"), _row(MON + timedelta(days=2), "bike", 60, "Ride")])
    new_rows = [_row(MON, "swim", 40, "Swim"), _row(MON + timedelta(days=1), "strength", 30, "Gym", "strength")]
    new = _plan(new_rows)
    clash = conflicts(old, new_rows, TODAY)
    assert clash == [{"date": MON.isoformat(), "old": ["Easy"], "new": ["Swim"]}]

    def sessions(p):
        return sorted((d, s["title"]) for _, d, s in iter_sessions(p) if s["sport"] != "rest")
    filled = merge_plans(old, new, "fill", TODAY)
    assert sessions(filled) == [(MON.isoformat(), "Easy"), ((MON + timedelta(days=1)).isoformat(), "Gym"),
                                ((MON + timedelta(days=2)).isoformat(), "Ride")]
    assert sessions(merge_plans(old, new, "replace", TODAY)) == [(MON.isoformat(), "Swim"),
                                                                 ((MON + timedelta(days=1)).isoformat(), "Gym")]
    assert conflicts(None, new_rows, TODAY) == []


# ------------------------------------------------ Word / ODF / workbooks --
W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _p(text: str) -> str:
    return f"<w:p><w:r><w:t xml:space=\"preserve\">{text}</w:t></w:r></w:p>"


def _docx(body: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", f"<w:document {W}><w:body>{body}</w:body></w:document>")
    return buf.getvalue()


def _tbl(rows: list[list[str]]) -> str:
    return "<w:tbl>" + "".join("<w:tr>" + "".join(f"<w:tc>{_p(c)}</w:tc>" for c in r) + "</w:tr>" for r in rows) + "</w:tbl>"


def test_docx_text_and_tables() -> None:
    table = [["Date", "Sport", "Workout", "Minutes"], ["2026-10-20", "Run", "Easy run", "40"],
             ["2026-10-22", "Bike", "Sweet spot", "75"]]
    data = _docx(_p("Coach Ana's plan") + _tbl(table) + _p("Fuel well."))
    assert detect(data, "plan.docx") == "docx" and zip_kind(data) == "docx"
    text, tables = docx_content(data)
    assert text.splitlines()[0] == "Coach Ana's plan" and "2026-10-20\tRun\tEasy run\t40" in text and tables == [table]
    rows, _ = rows_from_file("docx", data)
    cleaned, _ = clean_rows(rows)
    assert [(r["date"], r["sport"], r["minutes"]) for r in cleaned] == [("2026-10-20", "run", 40), ("2026-10-22", "bike", 75)]
    # Prose only: the text goes to the model.
    prose = _docx(_p("Week 1") + _p("Tue: 6x400 at 5K pace") + _p("Sat: long run 90'"))
    got = rows_from_file("docx", prose)
    assert got == {"text": b"Week 1\nTue: 6x400 at 5K pace\nSat: long run 90'"}
    with pytest.raises(PlanImportError):
        detect(b"PK\x03\x04" + b"\x00" * 30, "x.zip")
    evil = _docx("<!DOCTYPE x [<!ENTITY a 'b'>]>")
    with pytest.raises(PlanImportError):
        rows_from_file("docx", evil)
    with pytest.raises(PlanImportError, match="HEIC"):
        detect(b"\x00\x00\x00\x18ftypheic" + b"\x00" * 20, "IMG_1.HEIC")


def _ods(sheets: list[tuple[str, list[list[object]]]]) -> bytes:
    ns = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
          'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
          'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"')
    tabs = []
    for name, rows in sheets:
        trs = []
        for r in rows:
            cells = []
            for v in r:
                if isinstance(v, int | float):
                    cells.append(f'<table:table-cell office:value-type="float" office:value="{v}"><text:p>{v}</text:p></table:table-cell>')
                else:
                    cells.append(f"<table:table-cell office:value-type=\"string\"><text:p>{v}</text:p></table:table-cell>")
            trs.append("<table:table-row>" + "".join(cells) + "</table:table-row>")
        tabs.append(f'<table:table table:name="{name}">' + "".join(trs) + "</table:table>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/vnd.oasis.opendocument.spreadsheet")
        z.writestr("content.xml", f"<office:document-content {ns}><office:body><office:spreadsheet>{''.join(tabs)}"
                   "</office:spreadsheet></office:body></office:document-content>")
    return buf.getvalue()


def _xlsx_book(sheets: list[tuple[str, list[list[object]]]]) -> bytes:
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    strings: list[str] = []
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", f'<workbook {ns} xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + "".join(f'<sheet name="{n}" sheetId="{i + 1}" r:id="rId{i + 1}"/>' for i, (n, _) in enumerate(sheets))
                   + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{i + 1}" Target="worksheets/sheet{i + 1}.xml"/>' for i in range(len(sheets)))
                   + "</Relationships>")
        for k, (_, cells) in enumerate(sheets):
            xml_rows = []
            for i, row in enumerate(cells, start=1):
                cs = []
                for j, v in enumerate(row):
                    ref = f"{chr(65 + j)}{i}"
                    if isinstance(v, str):
                        strings.append(v)
                        cs.append(f'<c r="{ref}" t="s"><v>{len(strings) - 1}</v></c>')
                    else:
                        cs.append(f'<c r="{ref}"><v>{v}</v></c>')
                xml_rows.append(f'<row r="{i}">{"".join(cs)}</row>')
            z.writestr(f"xl/worksheets/sheet{k + 1}.xml", f'<worksheet {ns}><sheetData>{"".join(xml_rows)}</sheetData></worksheet>')
        z.writestr("xl/sharedStrings.xml", f'<sst {ns}>' + "".join(f"<si><t>{s}</t></si>" for s in strings) + "</sst>")
    return buf.getvalue()


PLAN_SHEET = [["Date", "Sport", "Workout", "Minutes"], ["2026-10-20", "Run", "Easy", 40], ["2026-10-21", "Swim", "Drills", 45]]


def test_workbooks_pick_the_sheet_and_ods() -> None:
    book = _xlsx_book([("Read me", [["Hi! This plan is for the spring."]]), ("Plan", PLAN_SHEET)])
    meta: dict = {}
    rows, _ = rows_from_file("xlsx", book, meta=meta)
    assert meta == {"sheets": ["Read me", "Plan"], "sheet": 1} and len(rows) == 2
    with pytest.raises(PlanImportError, match="another sheet"):
        rows_from_file("xlsx", book, sheet=0)
    with pytest.raises(PlanImportError):
        rows_from_file("xlsx", book, sheet=7)
    ods = _ods([("Notes", [["just words"]]), ("Weeks", PLAN_SHEET)])
    assert detect(ods, "plan.ods") == "ods"
    assert [n for n, _ in ods_tables(ods)] == ["Notes", "Weeks"]
    meta = {}
    rows, _ = rows_from_file("ods", ods, meta=meta)
    cleaned, _ = clean_rows(rows)
    assert meta["sheet"] == 1 and [(r["date"], r["minutes"]) for r in cleaned] == [("2026-10-20", 40), ("2026-10-21", 45)]


# ---------------------------------------------------------- Google links --
def test_google_link_allowlist() -> None:
    ok = {
        "https://docs.google.com/spreadsheets/d/e/2PACX-1vQabcdefghijk/pub?output=csv":
            "https://docs.google.com/spreadsheets/d/e/2PACX-1vQabcdefghijk/pub?output=csv",
        "https://docs.google.com/spreadsheets/d/e/2PACX-1vQabcdefghijk/pubhtml?gid=12":
            "https://docs.google.com/spreadsheets/d/e/2PACX-1vQabcdefghijk/pub?output=csv&gid=12&single=true",
        "https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMn/edit#gid=345":
            "https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMn/export?format=csv&gid=345",
        "https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMn/export?format=csv":
            "https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMn/export?format=csv",
        "https://docs.google.com/document/d/1AbCdEfGhIjKlMn/edit?usp=sharing":
            "https://docs.google.com/document/d/1AbCdEfGhIjKlMn/export?format=txt",
    }
    for u, want in ok.items():
        assert google_export_url(u)[0] == want, u
    for bad in ("http://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMn/edit",          # not https
                "https://docs.google.com.evil.com/spreadsheets/d/1AbCdEfGhIjKlMn/edit",
                "https://docs.google.com@evil.com/spreadsheets/d/1AbCdEfGhIjKlMn/edit",
                "https://evil.com/?u=https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMn/edit",
                "https://docs.google.com:8443/spreadsheets/d/1AbCdEfGhIjKlMn/edit",
                "https://user:pw@docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMn/edit",
                "https://drive.google.com/file/d/1AbCdEfGhIjKlMn/view",
                "https://docs.google.com/forms/d/1AbCdEfGhIjKlMn/viewform",
                "https://docs.google.com/spreadsheets/d/../../etc/export?format=csv",
                "https://127.0.0.1/spreadsheets/d/1AbCdEfGhIjKlMn/edit", "file:///etc/passwd", "", "x" * 3000):
        assert google_export_url(bad) is None, bad
    assert redirect_ok("https://doc-0g-1c-sheets.googleusercontent.com/export/abc")
    for bad in ("http://doc-0g.googleusercontent.com/x", "https://googleusercontent.com.evil.com/x",
                "https://evil.com/x", "https://169.254.169.254/latest", "https://a.googleusercontent.com:81/x",
                "https://x@a.googleusercontent.com/x"):
        assert not redirect_ok(bad), bad
    assert html_text("<html><head><style>x{}</style></head><body><p>Week 1</p><p>Tue &amp; Thu: run</p>"
                     "<script>alert(1)</script></body></html>") == "Week 1\nTue & Thu: run"


def _transport(handler):
    return httpx2.MockTransport(handler)


def test_fetch_google_follows_only_safe_redirects() -> None:
    seen: list[str] = []
    url = "https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMn/edit#gid=0"

    def ok(req: httpx2.Request) -> httpx2.Response:
        seen.append(str(req.url))
        if req.url.host == "docs.google.com":
            return httpx2.Response(307, headers={"location": "https://doc-0s-sheets.googleusercontent.com/export/x"})
        return httpx2.Response(200, headers={"content-type": "text/csv"}, content=b"date,sport,title\n2026-10-20,run,Easy\n")
    kind, body, name = asyncio.run(fetch_google(url, transport=_transport(ok)))
    assert kind == "csv" and body.startswith(b"date,") and name.endswith(".csv")
    assert seen == ["https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMn/export?format=csv&gid=0",
                    "https://doc-0s-sheets.googleusercontent.com/export/x"]

    def evil(req: httpx2.Request) -> httpx2.Response:
        if req.url.host == "docs.google.com":
            return httpx2.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data"})
        raise AssertionError("must not follow")
    with pytest.raises(LinkError, match="doesn't open"):
        asyncio.run(fetch_google(url, transport=_transport(evil)))

    def private(req: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(302, headers={"location": "https://accounts.google.com/ServiceLogin?continue=x"})
    with pytest.raises(LinkError, match="isn't public"):
        asyncio.run(fetch_google(url, transport=_transport(private)))

    def html_login(req: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, headers={"content-type": "text/html"}, content=b"<html>Sign in</html>")
    with pytest.raises(LinkError, match="isn't public"):
        asyncio.run(fetch_google(url, transport=_transport(html_login)))

    def huge(req: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, headers={"content-type": "text/csv"}, content=b"a," * (planlinks.MAX_BYTES // 2 + 10))
    with pytest.raises(LinkError, match="too large"):
        asyncio.run(fetch_google(url, transport=_transport(huge)))

    def loop(req: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(302, headers={"location": "https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMn/export"})
    with pytest.raises(LinkError, match="too many"):
        asyncio.run(fetch_google(url, transport=_transport(loop)))

    def never(req: httpx2.Request) -> httpx2.Response:
        raise AssertionError("no request for a disallowed link")
    with pytest.raises(LinkError):
        asyncio.run(fetch_google("https://example.com/plan.csv", transport=_transport(never)))

    def doc(req: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, headers={"content-type": "text/plain"}, content=b"Week 1\nTue easy 40'\n")
    kind, body, _ = asyncio.run(fetch_google("https://docs.google.com/document/d/1AbCdEfGhIjKlMn/edit",
                                             transport=_transport(doc)))
    assert kind == "text" and body.startswith(b"Week 1")


# ------------------------------------------------------- coach templates --
def test_relative_templates_round_trip() -> None:
    rows = [{"date": "2026-10-21", "sport": "run", "title": "A", "minutes": 40, "kind": "easy"},
            {"date": "2026-11-01", "sport": "bike", "title": "B", "minutes": 90, "kind": "long"},
            {"date": "2026-10-22", "sport": "rest", "title": ""}]
    rel, weeks = to_relative(rows)
    assert weeks == 2 and [(r["week"], r["weekday"]) for r in rel] == [(1, 2), (2, 6)]
    again = from_relative(rel, date(2027, 3, 3))                              # any day: its Monday week
    assert [r["date"] for r in again] == ["2027-03-03", "2027-03-14"] and again[1]["minutes"] == 90
    with pytest.raises(FormatError):
        to_relative([])


def test_templates_level_and_end_on_race_day() -> None:
    a = _athlete(weekly_hours=6)
    race = date(2027, 2, 6)
    beg, name = template_rows("half", a, None, today=TODAY, start=MON, week_templates=week_templates, level="beginner", end=race)
    mid, _ = template_rows("half", a, None, today=TODAY, start=MON, week_templates=week_templates, level="intermediate", end=race)
    assert name == "Half marathon plan"
    assert max(r["date"] for r in beg) == race.isoformat() and [r for r in beg if r["kind"] == "race"][0]["date"] == race.isoformat()
    assert min(r["date"] for r in beg) >= (race - timedelta(weeks=12)).isoformat()
    assert sum(r["minutes"] or 0 for r in beg) < sum(r["minutes"] or 0 for r in mid)
    close, _ = template_rows("marathon", a, None, today=TODAY, start=MON, week_templates=week_templates,
                             end=TODAY + timedelta(weeks=6))
    assert min(r["date"] for r in close) >= TODAY.isoformat()                 # shorter, never in the past
    with pytest.raises(FormatError):
        template_rows("5k", a, None, today=TODAY, start=MON, week_templates=week_templates, level="elite")
    with pytest.raises(FormatError):
        template_rows("5k", a, None, today=TODAY, start=MON, week_templates=week_templates, end=TODAY - timedelta(days=1))


# ------------------------------------------------------------- service --
def test_schedule_and_fill_through_the_service(env) -> None:
    agent, _ = env.agent([])
    today = agent.plans.today("friend")
    agent.coach.update_athlete("friend", _athlete())
    race = today + timedelta(weeks=10)
    race = race + timedelta(days=(6 - race.weekday()))                       # a Sunday
    agent.coach.create_goal("friend", {"title": "Spring half", "distance": "half marathon", "date": race.isoformat()})
    agent.plans.build("friend")
    imp = ImportService(env.store, agent.plans, agent.coach)
    raw = [{"week": 1, "weekday": "tue", "sport": "run", "title": "Easy", "minutes": 40},
           {"week": 4, "weekday": "sun", "sport": "run", "title": "Race day", "intensity": "race"}]
    pv = imp.preview("friend", raw, actor="friend", source="CSV", start=today + timedelta(days=(7 - today.weekday()) % 7 or 7))
    assert pv["relative"] and pv["race_date"] == race.isoformat() and pv["race_title"] == "Spring half"
    assert pv["conflict_count"] >= 1 and pv["conflicts"][0]["old"]
    up = imp.update("friend", pv["id"], pv["rows"], actor="friend", schedule={"how": "race"})
    assert max(r["date"] for r in up["rows"]) == race.isoformat() and up["schedule"] == {"how": "race"}
    up = imp.update("friend", pv["id"], up["rows"], actor="friend", schedule={"how": "date", "date": (race + timedelta(days=30)).isoformat()})
    assert min(r["date"] for r in up["rows"]) > race.isoformat()
    with pytest.raises(PlanImportError):
        imp.update("friend", pv["id"], up["rows"], actor="friend", schedule={"how": "date"})
    up = imp.update("friend", pv["id"], up["rows"], actor="friend", schedule={"how": "monday"}, mode="fill")
    nm = today + timedelta(days=(7 - today.weekday()) % 7)
    assert min(r["date"] for r in up["rows"]) == (nm + timedelta(days=1)).isoformat() and up["mode"] == "fill"
    assert up["totals"]["removed"] == 0
    plan, summary = imp.apply("friend", pv["id"], actor="friend", actor_name="Me", actor_role="athlete")
    assert summary["mode"] == "fill"
    day = (nm + timedelta(days=1)).isoformat()
    titles = [s["title"] for _, d, s in iter_sessions(plan) if d == day]
    assert titles and ("Easy" not in titles or len(titles) == 1)              # a clash keeps the current session


# ------------------------------------------------------------------ API --
def test_api_link_photos_templates_and_permissions(env, tmp_path, monkeypatch) -> None:
    agent, _ = env.agent([])
    today = agent.plans.today("friend")
    agent.coach.update_athlete("friend", _athlete())
    agent.coach.create_goal("friend", {"title": "Race", "distance": "10k", "date": (today + timedelta(weeks=12)).isoformat()})
    calls: list[list] = []

    async def structured(system, prompt, tool, **kw):
        calls.append(prompt)
        return {"sessions": [{"week": 1, "weekday": "tue", "sport": "run", "title": "Intervals", "minutes": 50},
                             {"week": 2, "weekday": "sat", "sport": "run", "title": "Long run", "minutes": 80}]}
    agent._backend.structured = structured  # type: ignore[attr-defined]

    async def fake_fetch(url: str, *, transport=None):
        if "document" in url:
            return "text", b"Week 1: Tue easy run 40'", "Google Doc.txt"
        if "private" in url:
            raise LinkError("That document isn't public, so rabbt can't open it.")
        return "csv", b"date,sport,title,minutes\n2026-11-03,run,Easy,40\n2026-11-05,bike,Ride,60\n", "Google Sheet.csv"
    monkeypatch.setattr(planlinks, "fetch_google", fake_fetch)
    athlete_app, coach_app = _apps(env, tmp_path, agent)
    own = "/app/api/plan/import"
    base = "/app/api/coach/athletes/friend/plan/import"

    async def go() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=athlete_app), base_url=BASE) as a, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=coach_app), base_url=BASE) as c:
            # Three screenshots: one model call with three images.
            png = b"\x89PNG\r\n\x1a\n" + b"x" * 20
            q = "name=p1.png&name=p2.png&name=p3.png" + f"&size={len(png)}" * 3
            r = await a.post(f"{own}/file?{q}", headers=H, content=png * 3)
            assert r.status_code == 201, r.text
            assert len(calls) == 1 and [b["type"] for b in calls[0]] == ["image", "image", "image", "text"]
            assert "pages of one training plan" in calls[0][-1]["text"]
            # A Word document with only prose: one model call with its text.
            prose = _docx(_p("Week 1") + _p("Tue: easy 40'"))
            r = await a.post(f"{own}/file?name=coach.docx", headers=H, content=prose)
            assert r.status_code == 201 and len(calls) == 2 and calls[1][0]["source"]["data"] == "Week 1\nTue: easy 40'"
            assert r.json()["preview"]["source"] == "Word document (read by rabbt)"
            # A workbook with two sheets says which one it read.
            book = _xlsx_book([("Notes", [["Read me first"]]), ("Plan", PLAN_SHEET)])
            r = await a.post(f"{own}/file?name=b.xlsx", headers=H, content=book)
            pv = r.json()["preview"]
            assert pv["sheets"] == ["Notes", "Plan"] and pv["sheet"] == 1
            r = await a.post(f"{own}/file?name=b.xlsx&sheet=0", headers=H, content=book)
            assert r.status_code == 400 and "another sheet" in r.json()["error"]
            # Google links: Sheets parsed here, Docs read by the model, private ones explained.
            r = await a.post(f"{own}/link", headers=H, json={"url": "https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMn/edit#gid=0"})
            assert r.status_code == 200, r.text
            pv = r.json()["preview"]
            assert pv["source"] == "Google Sheets" and pv["totals"]["sessions"] == 2 and len(calls) == 2
            r = await a.post(f"{own}/link", headers=H, json={"url": "https://docs.google.com/document/d/1AbCdEfGhIjKlMn/edit"})
            assert r.status_code == 200 and r.json()["preview"]["source"].startswith("Google Docs") and len(calls) == 3
            r = await a.post(f"{own}/link", headers=H, json={"url": "https://docs.google.com/spreadsheets/d/1privateXXXXXX/edit"})
            assert r.status_code == 400 and "isn't public" in r.json()["error"]
            r = await a.post(f"{own}/link", headers=H, json={"url": "http://169.254.169.254/latest/meta-data"})
            assert r.status_code == 400 and "only opens Google" in r.json()["error"]
            # A pasted Google link goes the same way.
            r = await a.post(f"{own}/file?name=pasted.txt", headers=H,
                             content=b"https://docs.google.com/spreadsheets/d/e/2PACX-1vQabcdefghijk/pub?output=csv")
            assert r.status_code == 201 and r.json()["preview"]["source"] == "Google Sheets"
            # Status and templates carry the race date for "end on race day".
            st = (await a.get(own)).json()
            assert st["race_date"] == (today + timedelta(weeks=12)).isoformat() and st["can_save_templates"] is False
            t = (await a.get(f"{own}/templates")).json()
            assert t["levels"] == ["beginner", "intermediate"] and t["mine"] is None and t["race_date"]
            r = await a.post(f"{own}/template/10k", headers=H, json={"level": "beginner", "end": "race"})
            assert r.status_code == 200, r.text
            pv = r.json()["preview"]
            assert max(x["date"] for x in pv["rows"]) == st["race_date"] and pv["name"] == "10K plan (beginner)"
            # Schedule through the API.
            r = await a.post(f"{own}/{pv['id']}/update", headers=H, json={"rows": pv["rows"], "schedule": {"how": "monday"}})
            assert r.status_code == 200 and r.json()["preview"]["schedule"] == {"how": "monday"}
            assert (await a.post(f"{own}/{pv['id']}/update", headers=H,
                                 json={"rows": pv["rows"], "schedule": {"how": "warp"}})).status_code == 400
            # Athletes can't save coach templates; coaches can't use the athlete's routes.
            r = await a.post(f"{own}/mine", headers=H, json={"name": "Mine", "import_id": pv["id"]})
            assert r.status_code == 403
            assert (await a.post(f"{own}/template/my0123456789", headers=H, json={})).status_code == 404
            assert (await c.post(f"{own}/mine", headers=H, json={"name": "x", "from": "plan"})).status_code == 403
            assert (await c.post(f"{own}/link", headers=H, json={"url": "https://docs.google.com/document/d/1AbCdEfGhIjKlMn/edit"})).status_code == 403
            # A view-only coach can't save or load.
            await a.post("/app/api/coaches", headers=H, json={"email": COACH, "can_edit_plan": False})
            assert (await c.post(f"{base}/mine", headers=H, json={"name": "x", "from": "plan"})).status_code == 400
            await a.patch(f"/app/api/coaches/{COACH}", headers=H, json={"can_edit_plan": True})
            # Coach: build from a template, save it as theirs, reuse it from another start date.
            r = await c.post(f"{base}/template/5k", headers=H, json={})
            cpv = r.json()["preview"]
            r = await c.post(f"{base}/mine", headers=H, json={"name": "Ana's 5K block", "import_id": cpv["id"]})
            assert r.status_code == 200, r.text
            mine = r.json()["template"]
            assert mine["label"] == "Ana's 5K block" and mine["weeks"] == 8 and mine["id"].startswith("my")
            t = (await c.get(f"{base}/templates")).json()
            assert [m["id"] for m in t["mine"]] == [mine["id"]]
            assert (await c.get(f"{base}")).json()["can_save_templates"] is True
            later = (today + timedelta(weeks=3)).isoformat()
            r = await c.post(f"{base}/template/{mine['id']}", headers=H, json={"start": later})
            assert r.status_code == 200, r.text
            pv2 = r.json()["preview"]
            assert pv2["source"] == "My template" and pv2["name"] == "Ana's 5K block"
            lm = date.fromisoformat(later)
            assert lm - timedelta(days=lm.weekday()) <= date.fromisoformat(pv2["first_day"]) < lm + timedelta(days=7)
            assert pv2["totals"]["sessions"] == cpv["totals"]["sessions"] - sum(1 for x in cpv["rows"] if x["sport"] == "rest")
            r = await c.post(f"{base}/mine", headers=H, json={"name": "Current plan", "from": "plan"})
            assert r.status_code == 400                                     # the athlete has no plan yet
            r = await c.post(f"{base}/{pv2['id']}/apply", headers=H, json={})
            assert r.status_code == 200
            r = await c.post(f"{base}/mine", headers=H, json={"name": "Current plan", "from": "plan"})
            assert r.status_code == 200 and len(r.json()["mine"]) == 2
            r = await c.post(f"{base}/mine/{mine['id']}/delete", headers=H, json={})
            assert [m["label"] for m in r.json()["mine"]] == ["Current plan"]
            assert (await c.post(f"{base}/template/{mine['id']}", headers=H, json={})).status_code == 400
            # Drafts are per actor: the coach can't save the athlete's draft.
            assert (await c.post(f"{base}/mine", headers=H, json={"name": "Steal", "import_id": pv["id"]})).status_code == 400
            assert json.dumps(st)  # status serializes
    asyncio.run(go())
    assert coach_user_id(COACH).startswith("coach_")
