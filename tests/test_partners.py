"""Club name search ("5280 run club" finds "5280 Runners"), the targeted web look-up for a named
club, and Partners (owner-curated, labelled, metro-scoped, owner-only admin, coach 403)."""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from types import SimpleNamespace

from garmin_mcp import clubdir as cd
from garmin_mcp import partners as pt
from garmin_mcp.appstore import AppStore
from garmin_mcp.clubdir import Directory
from garmin_mcp.coaches import coach_user_id
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_clubdir import TUESDAY, T0, Web, _apps, crawler
from tests.test_social import H

RUNNERS_HTML = """<html><head><title>5280 Runners</title></head><body><h1>5280 Runners</h1>
<p>Run with Altitude. Group runs Saturdays at 7:30 am from Washington Park.</p>
<a href="https://runsignup.com/Club/CO/DENVER/5280Runners">Join</a></body></html>"""


# ------------------------------------------------------------ matching --
def test_fuzzy_club_names() -> None:
    assert cd.name_match("5280 run club", "5280 Runners")
    assert cd.name_match("5280 runners", "5280 Runners")
    assert cd.name_match("wash park", "Washington Park Striders")
    assert cd.name_match("Denver Run Club", "Denver Run Club")
    assert not cd.name_match("boulder", "5280 Runners")
    assert cd.key_words("The 5280 Run Club") == ["5280"]
    assert pt.about_kind("run club", "run_club") and pt.about_kind("running groups", "run_club")
    assert not pt.about_kind("5280", "run_club") and not pt.about_kind("swim", "run_club")
    assert pt.monogram("5280 Runners") == "5280" and pt.monogram("Denver Run Club") == "DR"


# ------------------------------------------------------------ partners --
def make_partners(tmp_path, fernet_key, owner: str = "ann", day: date = date(2026, 10, 13)):
    store = AppStore(tmp_path / "app", fernet_key)
    t = SimpleNamespace(t=datetime(day.year, day.month, day.day, 12).timestamp())
    return pt.Partners(store, is_owner=lambda u: u == owner, clock=lambda: t.t), store, t


def test_seed_is_5280_runners_for_denver_and_the_front_range(tmp_path, fernet_key) -> None:
    p, store, _ = make_partners(tmp_path, fernet_key)
    (row,) = p.near("Denver", "CO")
    assert row["name"] == "5280 Runners" and row["label"] == "Partner" and row["tagline"] == "Run with Altitude"
    assert row["website"] == "https://5280runners.com/" and row["signup"].startswith("https://runsignup.com/")
    assert row["schedule"] == ""  # no public times were found: none invented
    assert p.near("Lakewood", "CO") and p.near("Aurora", "CO")
    assert p.near("Boulder", "UT") == [] and p.near("Austin", "TX") == []
    # relevant queries only
    assert p.near("Denver", "CO", query="5280 run club") and p.near("Denver", "CO", query="run club")
    assert p.near("Denver", "CO", query="masters swim") == [] and p.near("Denver", "CO", query="pickleball") == []
    # removing it is final: no re-seed
    p.remove("ann", row["id"])
    assert p.near("Denver", "CO") == [] and store.global_doc("partners").load()["seeded"] is True


def test_owner_only_admin_validation_and_dates(tmp_path, fernet_key) -> None:
    p, _, _ = make_partners(tmp_path, fernet_key)
    for uid in ("bob", coach_user_id("c@x.com")):
        for call in (lambda u: p.admin_list(u), lambda u: p.save(u, {}), lambda u: p.remove(u, pt.SEED["id"])):
            try:
                call(uid)
                raise AssertionError("expected 403")
            except pt.PartnerError as e:
                assert e.status == 403
    body = {"name": "Sloan Lake Tri", "kind": "tri_club", "website": "sloantri.example", "instagram": "@sloantri",
            "metros": ["Denver, CO"], "tagline": "Swim bike run", "starts": "2026-11-01"}
    out = p.save("ann", body)
    added = next(r for r in out["partners"] if r["id"] == out["id"])
    assert added["website"] == "https://sloantri.example/" and added["instagram"] == "https://www.instagram.com/sloantri/"
    assert added["live"] is False  # starts in November
    assert [r["name"] for r in p.near("Denver", "CO")] == ["5280 Runners"]
    for bad, msg in (({**body, "website": "http://x.example"}, "https"), ({**body, "metros": ["Nowhere"]}, "city"),
                     ({**body, "instagram": "https://evil.example/x"}, "Instagram"),
                     ({**body, "website": "", "instagram": "", "signup": ""}, "link"),
                     ({**body, "kind": "rocket"}, "kind"), ({**body, "ends": "2026-10-01"}, "before")):
        try:
            p.save("ann", bad)
            raise AssertionError(bad)
        except pt.PartnerError as e:
            assert msg.lower() in e.message.lower(), (msg, e.message)
    p.save("ann", {**body, "starts": None}, out["id"])
    assert {r["name"] for r in p.near("Denver", "CO", limit=5)} == {"5280 Runners", "Sloan Lake Tri"}


def test_counts_are_anonymous_and_once_per_person_kind_day(tmp_path, fernet_key) -> None:
    p, store, t = make_partners(tmp_path, fernet_key)
    pid = pt.SEED["id"]
    assert p.count("bob", pid, "view", "Denver", "CO") is True
    assert p.count("bob", pid, "view", "Denver", "CO") is False
    assert p.count("cat", pid, "view", "Denver", "CO") is True
    assert p.count("bob", pid, "website", "Denver", "CO") is True
    try:
        p.count("dan", pid, "view", "Austin", "TX")  # not in that partner's area
        raise AssertionError
    except pt.PartnerError as e:
        assert e.status == 404
    stats = next(r for r in p.admin_list("ann")["partners"] if r["id"] == pid)["stats"]
    assert stats["view"] == 2 and stats["website"] == 1 and stats["interested"] == 0
    assert "bob" not in str(store.global_doc("partners").load())


# --------------------------------------------------------- name look-up --
def make_lookup_dir(tmp_path, fernet_key, research_out):
    web = Web({"https://5280runners.example/robots.txt": "", "https://5280runners.example/": RUNNERS_HTML})
    calls = SimpleNamespace(research=[], extract=[])

    async def research(system, prompt, *, max_searches, report_tool):
        assert "5280 run club" in prompt and "Denver, CO" in prompt and max_searches <= 2
        calls.research.append(prompt)
        return research_out

    async def extract(system, prompt, tool, *, max_tokens):
        calls.extract.append(prompt)
        return {"listings": [{"name": "5280 Runners", "kind": "run_club", "sessions": [{"weekday": "sat", "time": "07:30"}],
                              "meet_spot": "Washington Park", "cost": "unknown"},
                             {"name": "Some Other Group", "kind": "run_club"}]}
    store = AppStore(tmp_path / "app", fernet_key)
    d = Directory(store, research=research, extract=extract, crawler=crawler(web), clock=lambda: T0)
    return d, web, calls


def test_look_up_finds_adds_and_rate_limits(tmp_path, fernet_key) -> None:
    out = {"candidates": [{"name": "5280 Runners", "url": "https://5280runners.example/", "kind": "run_club"},
                          {"name": "5280 Runners", "url": "https://www.instagram.com/5280runners/", "kind": "run_club"},
                          {"name": "Unrelated Club", "url": "https://other.example/", "kind": "run_club"}]}
    d, web, calls = make_lookup_dir(tmp_path, fernet_key, out)
    m = cd.metro("Denver", "CO")
    assert d.search(m, "5280 run club", now_local=TUESDAY) == []
    r = asyncio.run(d.look_up(m, "5280 run club", uid="ann", now_local=TUESDAY))
    assert r["status"] == "found" and [x["name"] for x in r["listings"]] == ["5280 Runners"]
    assert r["listings"][0]["found_by"] == "search" and r["listings"][0]["next"]["weekday"] == "sat"
    assert not any("instagram" in u or "other.example" in u for u in web.seen)  # social never fetched; unrelated skipped
    # Now the plain search finds it, and the directory lists it.
    assert [x["name"] for x in d.search(m, "5280", now_local=TUESDAY)] == ["5280 Runners"]
    assert any(x["name"] == "5280 Runners" for x in d.view(m, now_local=TUESDAY)["listings"])
    for _ in range(cd.LOOKUPS_PER_DAY - 1):
        asyncio.run(d.look_up(m, "5280 run club", uid="ann", now_local=TUESDAY))
    assert asyncio.run(d.look_up(m, "5280 run club", uid="ann", now_local=TUESDAY))["status"] == "limit"
    assert not d.can_look_up("ann") and d.can_look_up("bob")


def test_look_up_keeps_social_links_when_no_site(tmp_path, fernet_key) -> None:
    out = {"candidates": [{"name": "5280 Run Club", "url": "https://www.instagram.com/5280runclub/", "kind": "run_club"}]}
    d, web, _ = make_lookup_dir(tmp_path, fernet_key, out)
    r = asyncio.run(d.look_up(cd.metro("Denver", "CO"), "5280 run club", uid="ann", now_local=TUESDAY))
    assert r["status"] == "found" and r["listings"][0]["link_only"] == "Instagram" and web.seen == []
    d2, _, _ = make_lookup_dir(tmp_path / "b", fernet_key, {"candidates": []})
    assert asyncio.run(d2.look_up(cd.metro("Denver", "CO"), "5280 run club", uid="ann", now_local=TUESDAY))["status"] == "none"


def test_discovery_includes_social_run_clubs() -> None:
    assert any(tag == "social" and "Instagram" in what for tag, what in cd.QUERIES)


# ----------------------------------------------------------------- HTTP --
def test_http_search_partners_and_admin(env, tmp_path) -> None:  # noqa: F811
    c, lid, _ = _apps(env, tmp_path)

    async def go() -> None:
        ann, bob, cat = c["ann"], c["bob"], c["cat"]
        coach = c[coach_user_id("c@x.com")]
        body = (await bob.get("/app/api/community/directory")).json()
        (p,) = body["partners"]
        assert p["name"] == "5280 Runners" and p["label"] == "Partner"
        s = (await bob.get("/app/api/community/directory/search?q=5280%20run%20club")).json()
        assert s["partners"][0]["name"] == "5280 Runners" and s["listings"] == [] and s["metro"]["label"] == "Denver, CO"
        s = (await bob.get("/app/api/community/directory/search?q=wash%20park")).json()
        assert [x["name"] for x in s["listings"]] == ["Wash Park Runners"] and s["partners"] == []
        assert (await cat.get("/app/api/community/directory/search?q=run")).json()["metro"] is None
        # No research backend in tests: the look-up says unavailable.
        r = await bob.post("/app/api/community/directory/lookup", headers=H, json={"q": "5280 run club"})
        assert r.status_code == 200 and r.json()["status"] == "unavailable"
        # Detail + counts
        assert (await bob.get(f"/app/api/partners/{p['id']}")).json()["name"] == "5280 Runners"
        assert (await bob.post(f"/app/api/partners/{p['id']}/count", headers=H, json={"what": "website"})).json() == {"counted": True}
        assert (await bob.post(f"/app/api/partners/{p['id']}/count", headers=H, json={"what": "hack"})).status_code == 400
        assert (await cat.get(f"/app/api/partners/{p['id']}")).status_code == 404  # no home city
        # Global search shows it, labelled
        g = (await bob.get("/app/api/search?q=5280%20run%20club")).json()
        assert g["partners"][0]["label"] == "Sponsored partner" and "Denver" in g["partners"][0]["why"]
        # Admin: owner only; coach 403 everywhere
        assert (await bob.get("/app/api/partners/admin")).status_code == 403
        assert (await bob.post("/app/api/partners/admin", headers=H, json={"name": "X"})).status_code == 403
        assert (await coach.get("/app/api/partners/admin")).status_code == 403
        assert (await coach.get(f"/app/api/partners/{p['id']}")).status_code == 403
        assert (await coach.post("/app/api/community/directory/lookup", headers=H, json={"q": "x"})).status_code == 403
        adm = (await ann.get("/app/api/partners/admin")).json()
        assert adm["partners"][0]["stats"]["website"] == 1
        r = await ann.post("/app/api/partners/admin", headers=H, json={
            "name": "Mile High Masters", "kind": "swim", "website": "https://mhm.example/", "metros": ["Denver, CO"]})
        assert r.status_code == 201
        new = r.json()["id"]
        r = await ann.put(f"/app/api/partners/admin/{new}", headers=H, json={
            "name": "Mile High Masters Swim", "kind": "swim", "website": "https://mhm.example/", "metros": ["Denver, CO"]})
        assert any(x["name"] == "Mile High Masters Swim" for x in r.json()["partners"])
        assert (await bob.request("DELETE", f"/app/api/partners/admin/{new}", headers=H, json={})).status_code == 403
        r = await ann.request("DELETE", f"/app/api/partners/admin/{new}", headers=H, json={})
        assert r.status_code == 200, (r.status_code, r.text)
        assert all(x["id"] != new for x in r.json()["partners"])
        for x in c.values():
            await x.aclose()
    asyncio.run(go())



# ------------------------------------------------------------ sponsored --
def test_zip_metro_maps_front_range_zips_only() -> None:
    assert pt.zip_metro("80209") == ("Denver", "CO") and pt.zip_metro("80204") == ("Denver", "CO")
    assert pt.zip_metro("80014") == ("Aurora", "CO") and pt.zip_metro("80401") == ("Golden", "CO")
    assert pt.zip_metro("02116") is None  # Boston
    assert pt.zip_metro("80301") is None  # Boulder: not one of the partner's cities
    assert pt.zip_metro("8020") is None and pt.zip_metro("abcde") is None and pt.zip_metro(None) is None


def test_sponsored_card_rules_disclosure_hide_and_counts(tmp_path, fernet_key) -> None:
    p, _, t = make_partners(tmp_path, fernet_key)
    card = p.sponsored("bob", "local", "Denver", "CO")
    assert card and card["label"] == "Sponsored partner" and card["sponsored"] is True
    assert card["why"] == "5280 Runners is a rabbt partner shown to people near Denver, CO."
    # a Denver zip searched from anywhere shows it; Boston doesn't
    assert p.sponsored("cat", "search", "", "", ["80209"])["name"] == "5280 Runners"
    assert p.sponsored("cat", "search", "Boston", "MA", ["02116"]) is None
    assert p.sponsored("cat", "local", "Austin", "TX") is None
    # one card at a time, even with two sponsored partners in the metro
    p.save("ann", {"name": "Mile High Masters", "kind": "swim", "website": "https://mhm.example/",
                   "metros": ["Denver, CO"]})
    assert isinstance(p.sponsored("bob", "discover", "Denver", "CO"), dict)
    # a partner that isn't a paid placement never shows as sponsored
    mhm = next(x for x in p.admin_list("ann")["partners"] if x["name"] == "Mile High Masters")
    p.save("ann", {"name": "Mile High Masters", "kind": "swim", "website": "https://mhm.example/",
                   "metros": ["Denver, CO"], "sponsored": False}, mhm["id"])
    for _ in range(7):
        t.t += 86400
        assert p.sponsored("bob", "discover", "Denver", "CO")["name"] == "5280 Runners"
    # hide: gone from that screen for 30 days, still shows on others
    p.hide("bob", card["id"], "local")
    assert p.sponsored("bob", "local", "Denver", "CO") is None
    assert p.sponsored("bob", "explore", "Denver", "CO") is not None
    assert p.sponsored("eve", "local", "Denver", "CO") is not None  # per person
    t.t += 31 * 86400
    assert p.sponsored("bob", "local", "Denver", "CO") is not None
    # anonymous placement counts for the owner; no user ids stored
    assert p.placement_count("bob", card["id"], "impression", "local") is True
    assert p.placement_count("bob", card["id"], "impression", "local") is False  # once a day
    assert p.placement_count("eve", card["id"], "tap", "local") is True
    row = next(x for x in p.admin_list("ann")["partners"] if x["id"] == card["id"])
    assert row["placements"]["local"]["impression"] == 1 and row["placements"]["local"]["tap"] == 1
    doc = str(p._doc.load())
    assert "'bob'" not in doc and "'eve'" not in doc
    # bad input; coaches never get one
    for bad in (lambda: p.sponsored("bob", "nowhere", "Denver", "CO"),
                lambda: p.hide("bob", card["id"], "nowhere"),
                lambda: p.placement_count("bob", card["id"], "view", "local")):
        try:
            bad()
            raise AssertionError("expected PartnerError")
        except pt.PartnerError:
            pass
    assert p.sponsored(coach_user_id("c@x.com"), "local", "Denver", "CO") is None


def test_http_sponsored_placements(env, tmp_path) -> None:  # noqa: F811
    c, _, _ = _apps(env, tmp_path)

    async def go() -> None:
        bob, cat = c["bob"], c["cat"]
        coach = c[coach_user_id("c@x.com")]
        r = (await bob.get("/app/api/partners/sponsored?placement=local")).json()["card"]
        assert r["name"] == "5280 Runners" and r["label"] == "Sponsored partner"
        # no home city, but a Denver zip searched: shown; a Boston zip: not
        assert (await cat.get("/app/api/partners/sponsored?placement=local")).json()["card"] is None
        z = (await cat.get("/app/api/partners/sponsored?placement=explore&zip=80209")).json()["card"]
        assert z and z["name"] == "5280 Runners"
        assert (await cat.get("/app/api/partners/sponsored?placement=explore&zip=02116")).json()["card"] is None
        assert (await cat.get(f"/app/api/partners/{z['id']}?zip=80209")).status_code == 200
        assert (await bob.get("/app/api/partners/sponsored?placement=bogus")).status_code == 400
        # counts + hide
        assert (await bob.post(f"/app/api/partners/{r['id']}/count", headers=H,
                               json={"what": "impression", "placement": "local"})).json() == {"counted": True}
        assert (await bob.post(f"/app/api/partners/{r['id']}/hide", headers=H, json={"placement": "local"})).status_code == 200
        assert (await bob.get("/app/api/partners/sponsored?placement=local")).json()["card"] is None
        assert (await bob.get("/app/api/partners/sponsored?placement=discover")).json()["card"] is not None
        # global search: a Denver zip shows the sponsored partner; Boston doesn't
        g = (await cat.get("/app/api/search?q=80209")).json()
        assert g["partners"] and g["partners"][0]["label"] == "Sponsored partner"
        assert (await cat.get("/app/api/search?q=02116")).json().get("partners", []) == []
        # coaches: 403 as before
        assert (await coach.get("/app/api/partners/sponsored?placement=local")).status_code == 403
        assert (await coach.post(f"/app/api/partners/{r['id']}/hide", headers=H, json={"placement": "local"})).status_code == 403
        for x in c.values():
            await x.aclose()
    asyncio.run(go())
