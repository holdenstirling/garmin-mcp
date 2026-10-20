"""Joining from an invite link with "Continue with Google" (webauth.start_join).

The invite is used once, the Google account is bound to the new member so they can sign in
with Google later, expired / revoked / used-up invites are refused, and Google sign-in stays
closed to people with no account and no invite.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from tests.test_passkeys import Authenticator, Harness, h, join, make_invite  # noqa: F401 (fixture)
from tests.test_webapp import BASE, JSON_HDRS, run, sign_in


async def google_join(h: Harness, c, token: str):
    r = await c.get(f"/app/auth/google/join/{token}")
    if r.status_code != 302 or urlparse(r.headers["location"]).netloc != "accounts.google.com":
        return r
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["scope"] == ["openid email profile"]
    assert q["redirect_uri"] == [BASE + "/app/auth/google/callback"]
    return await c.get("/app/auth/google/callback", params={"state": q["state"][0], "code": "abc"})


def as_new_person(h: Harness, sub: str = "g-new", email: str = "Jesse@Example.org") -> None:
    h.google.sub, h.google.email, h.google.verified = sub, email, True


@run
async def test_google_join_creates_member_uses_invite_once_and_signs_in_again(h: Harness) -> None:
    async with h.client() as owner:
        await sign_in(h, owner)
        token = await make_invite(owner, max_uses=5)
        as_new_person(h)
        async with h.client() as c:
            r = await google_join(h, c, token)
            assert r.status_code == 302 and r.headers["location"] == "/app/", r.headers.get("location")
            me = (await c.get("/app/api/me")).json()
            assert me["user_id"].startswith("u_") and me["role"] == "athlete"
            uid = me["user_id"]
        acc = (await owner.get("/app/api/access")).json()
        assert acc["invites"][0]["uses"] == 1
        assert any(m["user_id"] == uid and m["email"] == "jesse@example.org" for m in acc["members"])
        # Later: plain Google sign-in works for them, and doesn't use the invite again.
        async with h.client() as c2:
            r = await sign_in(h, c2)
            assert r.status_code == 302 and r.headers["location"] == "/app/"
            assert (await c2.get("/app/api/me")).json()["user_id"] == uid
        # Joining again with the same Google account just signs in (no second member, no use).
        async with h.client() as c3:
            r = await google_join(h, c3, token)
            assert r.headers["location"] == "/app/"
            assert (await c3.get("/app/api/me")).json()["user_id"] == uid
        acc = (await owner.get("/app/api/access")).json()
        assert acc["invites"][0]["uses"] == 1


@run
async def test_google_join_refuses_bad_invites_and_existing_emails(h: Harness) -> None:
    async with h.client() as owner:
        await sign_in(h, owner)
        one = await make_invite(owner, max_uses=1)
        as_new_person(h, "g-a", "a@example.org")
        async with h.client() as c:
            assert (await google_join(h, c, one)).headers["location"] == "/app/"
        # used up
        as_new_person(h, "g-b", "b@example.org")
        async with h.client() as c:
            r = await google_join(h, c, one)
            assert r.status_code == 302 and "auth_error=invite" in r.headers["location"]
        # revoked
        made = (await owner.post("/app/api/invites", json={}, headers=JSON_HDRS)).json()
        tok, inv_id = made["url"].rsplit("/", 1)[1], made["invite"]["id"]
        assert (await owner.delete(f"/app/api/invites/{inv_id}", headers=JSON_HDRS)).status_code == 200
        async with h.client() as c:
            assert "auth_error=invite" in (await google_join(h, c, tok)).headers["location"]
        # expired
        late = await make_invite(owner, days=1)
        real = h.auth.access._clock
        h.auth.access._clock = lambda: real() + 2 * 86400
        async with h.client() as c:
            assert "auth_error=invite" in (await google_join(h, c, late)).headers["location"]
        h.auth.access._clock = real
        # an email that already belongs to a passkey member is never linked to it
        tok2 = await make_invite(owner)
        _, v = await join(h, tok2, Authenticator(), email="sam@example.org")
        assert v.status_code == 200
        as_new_person(h, "g-sam", "Sam@Example.org")
        async with h.client() as c:
            r = await google_join(h, c, tok2)
            assert "auth_error=account_exists" in r.headers["location"]
            assert (await c.get("/app/api/me")).status_code == 401
        # an unverified Google email can't join
        as_new_person(h, "g-u", "u@example.org")
        h.google.verified = False
        async with h.client() as c:
            r = await google_join(h, c, tok2)
            assert "auth_error=not_allowed" in r.headers["location"]


@run
async def test_google_sign_in_stays_closed_without_an_invite(h: Harness) -> None:
    as_new_person(h, "g-stranger", "stranger@example.org")
    async with h.client() as c:
        r = await sign_in(h, c)
        assert r.status_code == 302 and "auth_error=not_allowed" in r.headers["location"]
        assert (await c.get("/app/api/me")).status_code == 401
