"""Connected screens (people.py / people_web.py): profiles, notifications, friends today,
who else, club chat. Over HTTP with the community test app (ann, bob, cat + a coach)."""

from __future__ import annotations

import asyncio

from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_community import _clients, _setup
from tests.test_social import H


def test_profiles_inbox_friends_today_also_block_and_coach(env, tmp_path) -> None:
    apps, push, agent = _setup(env, tmp_path)

    async def go() -> None:
        c = _clients(apps)
        ann, bob, cat = c["ann"], c["bob"], c["cat"]
        # Strangers can't look each other up.
        assert (await bob.get("/app/api/people/ann")).status_code == 404
        await bob.post("/app/api/social/follow", headers=H, json={"email": "ann@x.com"})
        inbox = (await ann.get("/app/api/notifications")).json()
        assert any(i["kind"] == "follow_request" and i["open"] == {"k": "people"} for i in inbox["items"])
        eid = (await ann.get("/app/api/social")).json()["pending_in"][0]["edge_id"]
        await ann.post(f"/app/api/social/requests/{eid}/accept", headers=H, json={})
        p = (await bob.get("/app/api/people/ann")).json()
        assert p["following"] and p["workouts"] == [] and p["workouts_private"]  # Ann hasn't said yes
        await ann.put("/app/api/community/settings", headers=H, json={"share_workouts": True})

        p = (await bob.get("/app/api/people/ann")).json()
        assert p["person"]["name"] == "Ann" and p["following"] and not p["workouts_hidden"]
        assert p["workouts"] and all("avg_hr" not in w and "max_hr" not in w for w in p["workouts"])
        assert p["stats"]["workouts_4w"] >= 1 and p["can_message"] == "request"
        back = (await ann.get("/app/api/people/bob")).json()
        assert back["follows_you"] and back["workouts_hidden"] and back["workouts"] == []
        assert (await cat.get("/app/api/people/ann")).status_code == 404  # no relation

        today = (await bob.get("/app/api/friends/today")).json()
        assert [r["person"]["id"] for r in today["trained"]] == ["ann"]
        sport = today["trained"][0]["workout"]["sport"]
        also = (await bob.get(f"/app/api/people/also?sport={sport}")).json()
        assert [r["person"]["id"] for r in also["same_sport"]] == ["ann"]
        assert today["trained"][0]["kudos"] == 0 and not today["trained"][0]["you_cheered"]
        fam = {"running": "run", "cycling": "bike", "lap_swimming": "swim"}.get(sport)
        if fam:  # a plan's sport word matches Garmin's type key
            also2 = (await bob.get(f"/app/api/people/also?sport={fam}")).json()
            assert [r["person"]["id"] for r in also2["same_sport"]] == ["ann"]
        assert (await bob.get("/app/api/people/also?sport=../x")).status_code == 400

        aid = today["trained"][0]["workout"]["id"]
        assert (await bob.post(f"/app/api/social/kudos/ann/{aid}", headers=H, json={})).status_code == 200
        inbox = (await ann.get("/app/api/notifications")).json()
        kudos = [i for i in inbox["items"] if i["kind"] == "kudos"]
        assert kudos and kudos[0]["open"] == {"k": "activity", "id": aid} and kudos[0]["unread"]
        assert inbox["unread"] >= 2
        r = await ann.post("/app/api/notifications/read", headers=H, json={})
        assert r.status_code == 200 and r.json()["unread"] == 0
        assert (await ann.post("/app/api/notifications/read", headers={}, json={})).status_code == 403  # origin

        # Unfollow / follow again from the profile.
        r = await bob.request("DELETE", "/app/api/people/ann/follow", headers=H, json={})
        assert r.status_code == 200
        # Block: gone for both.
        assert (await ann.post("/app/api/people/bob/block", headers=H, json={})).status_code == 200
        assert (await bob.get("/app/api/people/ann")).status_code == 404
        assert (await ann.get("/app/api/people/bob")).status_code == 404

        coach = next(k for k in c if k.startswith("coach_"))
        assert (await c[coach].get("/app/api/people/ann")).status_code == 403
        assert (await c[coach].get("/app/api/notifications")).status_code == 403
    asyncio.run(go())


def test_club_chat_members_only(env, tmp_path) -> None:
    apps, push, agent = _setup(env, tmp_path)

    async def go() -> None:
        c = _clients(apps)
        ann, bob, cat = c["ann"], c["bob"], c["cat"]
        g = (await ann.post("/app/api/community/clubs", headers=H,
                            json={"name": "Crew", "emoji": "🐇", "privacy": "open", "city": "Denver"})).json()["club"]
        assert (await bob.post(f"/app/api/community/clubs/{g['id']}/join", headers=H, json={})).status_code == 200
        r = await ann.post(f"/app/api/clubs/{g['id']}/chat", headers=H, json={})
        assert r.status_code == 200, r.text
        conv = r.json()["conv"]
        assert conv["name"] == "Crew" and conv["kind"] == "group"
        again = (await bob.post(f"/app/api/clubs/{g['id']}/chat", headers=H, json={})).json()["conv"]
        assert again["id"] == conv["id"]  # one chat per club
        assert (await cat.post(f"/app/api/clubs/{g['id']}/chat", headers=H, json={})).status_code == 404
        # Club members can see each other's profiles (shared club).
        p = (await bob.get("/app/api/people/ann")).json()
        assert p["clubs"] and p["clubs"][0]["shared"] and p["in_common"]["clubs"] == ["Crew"]
    asyncio.run(go())
