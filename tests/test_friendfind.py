"""Find friends: handles, search, contact matching, suggestions, privacy and the HTTP routes."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx2
import pytest

from garmin_mcp.appstore import AppStore
from garmin_mcp.friendfind import FindError, FriendFinder, handle_base, norm_email, norm_phone
from garmin_mcp.social import Social
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_community import ALLOW, BASE, H, _clients, _setup

NAMES = {"ann": "Ann Smith", "bob": "Bob Jones", "cat": "Cat Smith", "dan": "Dan Brown", "eve": "Eve Ng"}
EMAILS = {"ann@x.com": "ann", "bob@x.com": "bob", "cat@x.com": "cat", "dan@x.com": "dan", "eve@x.com": "eve"}


@pytest.fixture
def ff(tmp_path, fernet_key):
    clock = SimpleNamespace(t=1_800_000_000.0)
    store = AppStore(tmp_path / "app", fernet_key)
    soc = Social(store, athletes=lambda: EMAILS, clock=lambda: clock.t)
    extra = SimpleNamespace(base={}, races={}, metro={}, buddies={})
    f = FriendFinder(store, soc=soc, emails=lambda: EMAILS, name=lambda u: NAMES.get(u, ""),
                     base_suggestions=lambda u: extra.base.get(u, []), races=lambda u: extra.races.get(u, []),
                     metro=lambda u: extra.metro.get(u, ""), buddies=lambda u: extra.buddies.get(u, []),
                     clock=lambda: clock.t)
    return SimpleNamespace(f=f, soc=soc, clock=clock, extra=extra, store=store)


def _mutual(soc, a, b):
    soc.connect_invited(a, b)


def test_normalizers() -> None:
    assert norm_phone("(303) 555-1234") == "+13035551234"
    assert norm_phone("1-303-555-1234") == "+13035551234"
    assert norm_phone("+44 20 7946 0958") == "+442079460958"
    assert norm_phone("555-1234") is None and norm_phone("") is None
    assert norm_email(" Ann@X.com ") == "ann@x.com" and norm_email("nope") is None
    assert handle_base("Jesse O'Neil") == "jesse" and handle_base("Zoë") == "zoe"
    assert handle_base("Al") == "al_runner" and handle_base("") == "runner"


def test_handles_unique_and_validated(ff) -> None:
    f = ff.f
    assert f.handle_of("ann") == "ann"
    NAMES["dan"] = "Ann Other"
    try:
        assert f.handle_of("dan") == "ann2"
    finally:
        NAMES["dan"] = "Dan Brown"
    assert f.set_handle("bob", "@Bobby_Runs") == "bobby_runs"
    assert f.uid_for_handle("@bobby_runs") == "bob"
    with pytest.raises(FindError) as e:
        f.set_handle("cat", "bobby_runs")
    assert e.value.status == 409
    for bad in ("ab", "has space", "x" * 21, "rabbit", "emoji🐇"):
        with pytest.raises(FindError):
            f.set_handle("cat", bad)
    f.set_handle("bob", "bob.j")
    assert f.uid_for_handle("bobby_runs") is None and f.uid_for_handle("bob.j") == "bob"
    assert f.handles(["ann", "bob", "eve"]) == {"ann": "ann", "bob": "bob.j", "eve": "eve"}


def test_search_by_name_handle_email_phone_and_privacy(ff) -> None:
    f, soc = ff.f, ff.soc
    names = [r["user_id"] for r in f.search("ann", "smi")]
    assert names == ["cat"]  # never yourself
    assert [r["user_id"] for r in f.search("bob", "@ca")] == ["cat"]
    assert [r["user_id"] for r in f.search("bob", "cat smith")] == ["cat"]
    assert f.search("bob", "a") == []  # too short
    assert [r["user_id"] for r in f.search("bob", "CAT@x.com")] == ["cat"]
    assert f.search("bob", "nobody@x.com") == []
    f.put_prefs("cat", {"phone": "303.555.1234"})
    assert [r["user_id"] for r in f.search("bob", "(303) 555-1234")] == ["cat"]
    # Turned off: that route stops finding them.
    f.put_prefs("cat", {"find": {"phone": False, "email": False, "name": False}})
    assert f.search("bob", "303 555 1234") == [] and f.search("bob", "cat@x.com") == []
    assert f.search("bob", "cat") == []
    _mutual(soc, "bob", "cat")  # already connected: name search still finds them
    assert [r["user_id"] for r in f.search("bob", "cat")] == ["cat"]
    assert f.search("bob", "cat")[0]["status"] == "following"
    # Blocked either way: never.
    soc.block("eve", "bob")
    assert f.search("bob", "eve") == [] and f.search("eve", "bob") == []
    # Phone stored only in the person's own entry; the index holds an HMAC.
    f.put_prefs("dan", {"phone": "+1 720 555 0000"})
    raw = json.dumps(ff.store.global_doc("directory").load())
    assert raw.count("+17205550000") == 1
    with pytest.raises(FindError):
        f.put_prefs("ann", {"phone": "720-555-0000"})  # someone else's number
    with pytest.raises(FindError):
        f.put_prefs("ann", {"phone": "12"})
    f.put_prefs("dan", {"phone": None})
    assert f.prefs("dan")["phone"] is None and f.search("ann", "720 555 0000") == []


def test_match_compares_and_discards(ff) -> None:
    f = ff.f
    f.put_prefs("dan", {"phone": "303-555-9999"})
    f.put_prefs("eve", {"find": {"email": False}})
    before = json.dumps(ff.store.global_doc("directory").load())
    res = f.match("ann", [
        {"emails": ["BOB@x.com"], "phones": []},
        {"emails": ["stranger@y.com"], "phones": ["+1 999 000 1111"]},
        {"emails": [], "phones": ["(303) 555-9999"]},
        {"emails": ["eve@x.com"]},          # email matching turned off
        {"emails": ["ann@x.com"]},          # yourself
        {"emails": ["bob@x.com"]},          # the same person twice
        "junk",
    ])
    assert [(r["index"], r["user_id"]) for r in res["on_rabbit"]] == [(0, "bob"), (2, "dan")]
    after = json.dumps(ff.store.global_doc("directory").load())
    assert "stranger@y.com" not in after and "9990001111" not in after and before == after
    with pytest.raises(FindError) as e:
        f.match("ann", [{"emails": [f"p{i}@x.com" for i in range(501)]}])
    assert e.value.status == 413
    with pytest.raises(FindError):
        f.match("ann", {"emails": []})
    for _ in range(9):
        f.match("ann", [])
    with pytest.raises(FindError) as e:
        f.match("ann", [])
    assert e.value.status == 429
    ff.clock.t += 3601
    f.match("ann", [])


def test_suggestions_rank_dismiss_and_exclude(ff) -> None:
    f, soc, x = ff.f, ff.soc, ff.extra
    _mutual(soc, "ann", "bob")
    _mutual(soc, "bob", "cat")
    _mutual(soc, "bob", "dan")
    soc.follow("eve", code=soc.invite_code("ann"))  # eve asked to follow ann: still "pending", not a follower
    x.races = {"ann": ["bolder boulder|2027-05-31"], "eve": ["bolder boulder|2027-05-31"]}
    x.metro = {"ann": "Denver, CO", "dan": "Denver, CO"}
    rows = f.suggestions("ann")
    order = [r["user_id"] for r in rows]
    assert order == ["eve", "dan", "cat"]  # same race, then mutual (+ same city for dan)
    assert rows[0]["reason"] == "Same race as you"
    assert rows[1]["reason"] == "1 mutual friend" and rows[1]["mutual"] == 1
    assert "bob" not in order and "ann" not in order
    x.base = {"ann": [{"user_id": "eve", "reason": "Follows you"}]}
    assert f.suggestions("ann")[0]["user_id"] == "eve"
    f.dismiss("ann", "eve")
    assert "eve" not in [r["user_id"] for r in f.suggestions("ann")]
    soc.block("cat", "ann")
    assert "cat" not in [r["user_id"] for r in f.suggestions("ann")]
    assert f.can_follow("ann", "dan") and not f.can_follow("ann", "cat") and not f.can_follow("ann", "ann")


def test_forget_and_export(ff) -> None:
    f = ff.f
    f.set_handle("ann", "annie")
    f.put_prefs("ann", {"phone": "303-555-1000"})
    f.dismiss("bob", "ann")
    assert f.export_user("ann")["handle"] == "annie"
    f.forget_user("ann")
    d = ff.store.global_doc("directory").load()
    assert "annie" not in (d.get("handles") or {}) and not d.get("phones") and "ann" not in d["users"]["bob"]["dismissed"]


def test_http_routes(env, tmp_path) -> None:
    apps, push, agent = _setup(env, tmp_path)

    async def go() -> None:
        c = _clients(apps)
        ann, bob = c["ann"], c["bob"]
        me = (await ann.get("/app/api/friends/me")).json()
        assert me["handle"] == "ann" and me["find"] == {"name": True, "email": True, "phone": True}
        assert me["invite_link"].startswith(f"{BASE}/app/?add=")
        r = await ann.put("/app/api/friends/me", headers=H, json={"handle": "ann_runs", "phone": "3035551234"})
        assert r.json()["handle"] == "ann_runs" and r.json()["phone"] == "+13035551234"
        assert (await bob.put("/app/api/friends/me", headers=H, json={"handle": "ann_runs"})).status_code == 409
        people = (await bob.get("/app/api/friends/search?q=@ann")).json()["people"]
        assert [p["user"]["name"] for p in people] == ["Ann"] and people[0]["user"]["handle"] == "ann_runs"
        r = await bob.post("/app/api/friends/match", headers=H,
                           json={"contacts": [{"phones": ["303 555 1234"]}, {"emails": ["zed@q.com"]}]})
        body = r.json()
        assert [x["index"] for x in body["on_rabbit"]] == [0] and body["checked"] == 2
        r = await bob.post("/app/api/friends/follow", headers=H, json={"user_id": "ann"})
        assert r.json()["status"] == "requested" and any(p[0] == "ann" for p in push.sent)
        assert (await bob.post("/app/api/friends/follow", headers=H, json={"user_id": "nobody"})).status_code == 404
        assert (await bob.post("/app/api/friends/follow", headers={"origin": "https://evil"}, json={"user_id": "ann"})).status_code == 403
        sug = (await ann.get("/app/api/friends/suggested")).json()["people"]
        assert isinstance(sug, list)
        r = await ann.post("/app/api/friends/suggested/cat/dismiss", headers=H, json={})
        assert r.json() == {"ok": True}
        code = me["invite_link"].rsplit("=", 1)[1]
        who = (await bob.get(f"/app/api/friends/code/{code}")).json()
        assert who["user"]["name"] == "Ann" and who["status"] == "requested"
        assert (await ann.get(f"/app/api/friends/code/{code}")).json()["status"] == "self"
        assert (await bob.get("/app/api/friends/code/ZZZZZZZZ")).status_code == 404
        assert (await bob.get("/app/api/friends/code/bad")).status_code == 404
        coach = next(k for k in c if k.startswith("coach_"))
        assert (await c[coach].get("/app/api/friends/me")).status_code == 403
    asyncio.run(go())
    assert ALLOW  # shared fixture data
