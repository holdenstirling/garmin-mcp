"""Invite links, joining with a passkey, passkey sign-in, members and WebAuthn verification.

A small virtual authenticator (real ES256/RS256 keys, 'none' attestation) drives the real
ASGI app through the same harness as test_webapp.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import replace
from typing import Any

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa

from garmin_mcp.access import RateLimit
from garmin_mcp.appstore import AppStore
from garmin_mcp.config import Settings, _parse_email_map
from garmin_mcp.server import build_app
from garmin_mcp.tokens import EncryptedFileTokenStore
from garmin_mcp.webapp import build_app_routes
from garmin_mcp.webauth import WebAuth
from tests.conftest import make_service
from garmin_mcp.passkeys import (WebAuthnError, b64u, cbor_decode, verify_authentication,
                                 verify_registration)
from tests.test_webapp import BASE, HOST, JSON_HDRS, Google, run, sign_in


# ------------------------------------------------------- tiny CBOR encoder --
def _head(major: int, n: int) -> bytes:
    if n < 24:
        return bytes([major << 5 | n])
    for info, size in ((24, 1), (25, 2), (26, 4), (27, 8)):
        if n < 1 << (8 * size):
            return bytes([major << 5 | info]) + n.to_bytes(size, "big")
    raise ValueError(n)


def cbor(v: Any) -> bytes:
    if isinstance(v, bool):
        return b"\xf5" if v else b"\xf4"
    if isinstance(v, int):
        return _head(0, v) if v >= 0 else _head(1, -1 - v)
    if isinstance(v, bytes):
        return _head(2, len(v)) + v
    if isinstance(v, str):
        return _head(3, len(v.encode())) + v.encode()
    if isinstance(v, list):
        return _head(4, len(v)) + b"".join(cbor(x) for x in v)
    if isinstance(v, dict):
        return _head(5, len(v)) + b"".join(cbor(k) + cbor(x) for k, x in v.items())
    raise TypeError(v)


class Authenticator:
    """A platform authenticator with one discoverable credential."""

    def __init__(self, *, rsa_key: bool = False, rp_id: str = HOST, origin: str = BASE,
                 counter: bool = True) -> None:
        self.rsa = rsa_key
        self.key = rsa.generate_private_key(65537, 2048) if rsa_key else ec.generate_private_key(ec.SECP256R1())
        self.cred_id = os.urandom(16)
        self.rp_id, self.origin = rp_id, origin
        self.count = 0
        self.counter = counter
        self.handle: str | None = None

    @property
    def id(self) -> str:
        return b64u(self.cred_id)

    def cose(self) -> bytes:
        nums = self.key.public_key().public_numbers()
        if self.rsa:
            return cbor({1: 3, 3: -257, -1: nums.n.to_bytes(256, "big"), -2: nums.e.to_bytes(3, "big")})
        return cbor({1: 2, 3: -7, -1: 1, -2: nums.x.to_bytes(32, "big"), -3: nums.y.to_bytes(32, "big")})

    def create(self, opts: dict[str, Any], *, challenge: str | None = None) -> dict[str, Any]:
        pk = opts["publicKey"]
        assert pk["authenticatorSelection"]["residentKey"] == "required"
        assert pk["rp"]["id"] == HOST
        self.handle = pk["user"]["id"]
        cd = json.dumps({"type": "webauthn.create", "challenge": challenge or pk["challenge"],
                         "origin": self.origin, "crossOrigin": False}).encode()
        ad = (hashlib.sha256(self.rp_id.encode()).digest() + bytes([0x45]) + self.count.to_bytes(4, "big")
              + bytes(16) + len(self.cred_id).to_bytes(2, "big") + self.cred_id + self.cose())
        att = cbor({"fmt": "none", "attStmt": {}, "authData": ad})
        return {"id": self.id, "rawId": self.id, "type": "public-key",
                "response": {"clientDataJSON": b64u(cd), "attestationObject": b64u(att), "transports": ["internal"]}}

    def get(self, opts: dict[str, Any]) -> dict[str, Any]:
        pk = opts["publicKey"]
        if self.counter:
            self.count += 1
        cd = json.dumps({"type": "webauthn.get", "challenge": pk["challenge"], "origin": self.origin}).encode()
        ad = hashlib.sha256(self.rp_id.encode()).digest() + bytes([0x05]) + self.count.to_bytes(4, "big")
        data = ad + hashlib.sha256(cd).digest()
        sig = (self.key.sign(data, padding.PKCS1v15(), hashes.SHA256()) if self.rsa
               else self.key.sign(data, ec.ECDSA(hashes.SHA256())))
        return {"id": self.id, "rawId": self.id, "type": "public-key",
                "response": {"clientDataJSON": b64u(cd), "authenticatorData": b64u(ad), "signature": b64u(sig),
                             "userHandle": self.handle}}


class Harness:
    """Like test_webapp's harness, without Web Push (not needed here)."""

    def __init__(self, tmp_path, fernet_key, provider, registry) -> None:
        self.key = fernet_key
        self.settings = Settings(
            public_base_url=BASE, data_dir=tmp_path, app_enabled=True, google_client_id="g-client",
            allowed_google_users=_parse_email_map(["friend@example.com:friend", "holden@example.com:holden"]))
        self.google = Google()
        self.service = make_service(provider, registry)
        self.rebuild()

    def rebuild(self, settings: Settings | None = None) -> None:
        if settings is not None:
            self.settings = settings
        store = AppStore(self.settings.app_dir, self.key)
        self.auth = WebAuth(self.settings, store, "g-secret", http=self.google.client())
        tokens = EncryptedFileTokenStore(self.settings.token_dir, self.key)
        routes = build_app_routes(self.settings, self.auth, tokens, None, None)
        self.app = build_app(self.settings, self.service, None, None, routes)

    def client(self, host: str = HOST):
        import httpx2
        return httpx2.AsyncClient(transport=httpx2.ASGITransport(app=self.app), base_url=BASE,
                                  headers={"host": host})


@pytest.fixture
def h(tmp_path, fernet_key, provider, registry) -> Harness:
    return Harness(tmp_path, fernet_key, provider, registry)


async def make_invite(c, **body) -> str:
    r = await c.post("/app/api/invites", json=body, headers=JSON_HDRS)
    assert r.status_code == 201, r.text
    url = r.json()["url"]
    assert url.startswith(BASE + "/app/join/")
    return url.rsplit("/", 1)[1]


async def join(h: Harness, token: str, a: Authenticator, *, name: str = "Sam", email: str = "Sam@Example.org"):
    """Returns (client, verify response); the client keeps the new session cookie."""
    c = h.client()
    r = await c.post(f"/app/auth/join/{token}/options", json={"name": name, "email": email}, headers=JSON_HDRS)
    if r.status_code != 200:
        return c, r
    v = await c.post(f"/app/auth/join/{token}/verify", json={"credential": a.create(r.json())}, headers=JSON_HDRS)
    return c, v


async def passkey_login(h: Harness, a: Authenticator):
    c = h.client()
    o = await c.post("/app/auth/passkey/options", json={}, headers=JSON_HDRS)
    assert o.status_code == 200
    assert o.json()["publicKey"]["allowCredentials"] == []
    return c, await c.post("/app/auth/passkey/verify", json={"credential": a.get(o.json())}, headers=JSON_HDRS)


# ------------------------------------------------------------- WebAuthn unit --
def _reg(a: Authenticator, challenge: str = "abc"):
    opts = {"publicKey": {"challenge": challenge, "rp": {"id": HOST}, "user": {"id": "aGFuZGxl"},
                          "authenticatorSelection": {"residentKey": "required"}}}
    return verify_registration(a.create(opts), challenge=challenge, rp_id=HOST, origin=BASE)


@pytest.mark.parametrize("use_rsa", [False, True])
def test_registration_and_assertion_verify(use_rsa: bool) -> None:
    a = Authenticator(rsa_key=use_rsa)
    reg = _reg(a)
    assert reg.cred_id == a.id and reg.alg == (-257 if use_rsa else -7)
    count, _ = verify_authentication(a.get({"publicKey": {"challenge": "xyz"}}), challenge="xyz", rp_id=HOST,
                                     origin=BASE, public_key=reg.public_key, sign_count=0)
    assert count == 1
    with pytest.raises(WebAuthnError):  # counter went backwards / repeated: cloned authenticator
        a.count = 0
        verify_authentication(a.get({"publicKey": {"challenge": "x2"}}), challenge="x2", rp_id=HOST,
                              origin=BASE, public_key=reg.public_key, sign_count=5)


def test_zero_counter_passkeys_are_fine() -> None:
    a = Authenticator(counter=False)
    reg = _reg(a)
    for ch in ("a1", "a2"):
        assert verify_authentication(a.get({"publicKey": {"challenge": ch}}), challenge=ch, rp_id=HOST,
                                     origin=BASE, public_key=reg.public_key, sign_count=0)[0] == 0


def test_verification_rejects_wrong_origin_rp_challenge_and_signature() -> None:
    with pytest.raises(WebAuthnError):
        _reg(Authenticator(origin="https://evil.example.com"))
    with pytest.raises(WebAuthnError):
        _reg(Authenticator(rp_id="evil.example.com"))
    a = Authenticator()
    with pytest.raises(WebAuthnError):
        verify_registration(a.create({"publicKey": {"challenge": "one", "rp": {"id": HOST}, "user": {"id": "x"},
                                                    "authenticatorSelection": {"residentKey": "required"}}}),
                            challenge="two", rp_id=HOST, origin=BASE)
    reg = _reg(a)
    other = Authenticator()
    with pytest.raises(WebAuthnError):  # signed by a different key
        verify_authentication(other.get({"publicKey": {"challenge": "c"}}), challenge="c", rp_id=HOST,
                              origin=BASE, public_key=reg.public_key, sign_count=0)


def test_cbor_decoder_basics() -> None:
    assert cbor_decode(cbor({"a": [1, -2, b"x", True]})) == {"a": [1, -2, b"x", True]}
    with pytest.raises(WebAuthnError):
        cbor_decode(cbor(1) + b"\x00")
    with pytest.raises(WebAuthnError):
        cbor_decode(b"\x5a\xff\xff\xff\xff")  # length beyond the data


# ------------------------------------------------------------------ invites --
@run
async def test_join_with_invite_creates_member_and_session(h: Harness) -> None:
    async with h.client() as owner:
        await sign_in(h, owner)
        assert (await owner.get("/app/api/me")).json()["can_invite"] is True
        token = await make_invite(owner)
        info = await h.client().get(f"/app/api/join/{token}")
        assert info.json()["inviter"] == "Friend"
        a = Authenticator()
        c, v = await join(h, token, a)
        assert v.status_code == 200, v.text
        assert any(s.startswith("__Host-rabbit_session=") for s in v.headers.get_list("set-cookie"))
        me = (await c.get("/app/api/me")).json()
        assert me["user_id"].startswith("u_") and me["role"] == "athlete" and me["profile"]["name"] == "Sam"
        assert me["can_invite"] is False
        acc = (await owner.get("/app/api/access")).json()
        assert acc["owner"] and acc["invites"][0]["uses"] == 1
        assert acc["invites"][0]["joined"][0]["user_id"] == me["user_id"]
        assert acc["members"][0]["email"] == "sam@example.org"  # normalized
        # the token itself is never stored
        assert token.encode() not in (h.settings.app_dir / "invites.fernet").read_bytes()
        # sign in again later with the passkey
        c2, r = await passkey_login(h, a)
        assert r.status_code == 200
        assert (await c2.get("/app/api/me")).json()["user_id"] == me["user_id"]


@run
async def test_duplicate_email_is_told_to_sign_in(h: Harness) -> None:
    async with h.client() as owner:
        await sign_in(h, owner)
        token = await make_invite(owner)
        _, v = await join(h, token, Authenticator(), email="sam@example.org")
        assert v.status_code == 200
        for email in ("SAM@example.org", "friend@example.com"):
            _, r = await join(h, token, Authenticator(), email=email)
            assert r.status_code == 409 and r.json()["signin"] is True


@run
async def test_invite_expiry_revoke_and_max_uses(h: Harness) -> None:
    async with h.client() as owner:
        await sign_in(h, owner)
        one = await make_invite(owner, max_uses=1)
        _, ok = await join(h, one, Authenticator(), email="a@example.org")
        assert ok.status_code == 200
        _, full = await join(h, one, Authenticator(), email="b@example.org")
        assert full.status_code == 404
        assert (await h.client().get(f"/app/api/join/{one}")).status_code == 404

        made = (await owner.post("/app/api/invites", json={}, headers=JSON_HDRS)).json()
        tok, inv_id = made["url"].rsplit("/", 1)[1], made["invite"]["id"]
        assert (await owner.delete(f"/app/api/invites/{inv_id}", headers=JSON_HDRS)).status_code == 200
        _, revoked = await join(h, tok, Authenticator(), email="c@example.org")
        assert revoked.status_code == 404

        late = await make_invite(owner, days=1)
        real = h.auth.access._clock
        h.auth.access._clock = lambda: real() + 2 * 86400
        _, expired = await join(h, late, Authenticator(), email="d@example.org")
        assert expired.status_code == 404
        h.auth.access._clock = real
        assert (await h.client().get("/app/api/join/not-a-real-token-at-all-xx")).status_code == 404


@run
async def test_challenges_are_single_use(h: Harness) -> None:
    async with h.client() as owner:
        await sign_in(h, owner)
        token = await make_invite(owner)
        a = Authenticator()
        c = h.client()
        o = await c.post(f"/app/auth/join/{token}/options", json={"name": "Sam", "email": "s@example.org"},
                         headers=JSON_HDRS)
        cred = a.create(o.json())
        assert (await c.post(f"/app/auth/join/{token}/verify", json={"credential": cred},
                             headers=JSON_HDRS)).status_code == 200
        again = await c.post(f"/app/auth/join/{token}/verify", json={"credential": cred}, headers=JSON_HDRS)
        assert again.status_code == 400
        assert len((await owner.get("/app/api/access")).json()["members"]) == 1
        # login challenge replay
        lc = h.client()
        lo = await lc.post("/app/auth/passkey/options", json={}, headers=JSON_HDRS)
        assertion = a.get(lo.json())
        assert (await lc.post("/app/auth/passkey/verify", json={"credential": assertion},
                              headers=JSON_HDRS)).status_code == 200
        assert (await lc.post("/app/auth/passkey/verify", json={"credential": assertion},
                              headers=JSON_HDRS)).status_code == 400
        # a challenge older than 5 minutes is refused
        lo = await lc.post("/app/auth/passkey/options", json={}, headers=JSON_HDRS)
        real = h.auth.access._clock
        h.auth.access._clock = lambda: real() + 301
        late = await lc.post("/app/auth/passkey/verify", json={"credential": a.get(lo.json())}, headers=JSON_HDRS)
        assert late.status_code == 400


@run
async def test_removed_member_loses_access(h: Harness) -> None:
    async with h.client() as owner:
        await sign_in(h, owner)
        token = await make_invite(owner)
        a = Authenticator()
        c, _ = await join(h, token, a)
        uid = (await c.get("/app/api/me")).json()["user_id"]
        r = await owner.delete(f"/app/api/members/{uid}", headers=JSON_HDRS)
        assert r.status_code == 200
        assert (await c.get("/app/api/me")).status_code == 401
        _, login = await passkey_login(h, a)
        assert login.status_code == 400
        assert (await owner.delete("/app/api/members/friend", headers=JSON_HDRS)).status_code == 404


@run
async def test_public_posts_need_origin_and_are_rate_limited(h: Harness) -> None:
    async with h.client() as c:
        assert (await c.post("/app/auth/passkey/options", json={})).status_code == 403
        assert (await c.post("/app/auth/passkey/options", json={},
                             headers={"origin": "https://evil.example.com", "content-type": "application/json"})
                ).status_code == 403
    h.rebuild()
    # tighter limits to exercise the 429 path
    from garmin_mcp import passkey_web
    routes = passkey_web.make_routes(auth=h.auth, api=lambda f, mutating: f, host_ok=lambda r: True,
                                     read_json=lambda r: r.json(), login_limit=RateLimit(2, 60))
    from starlette.applications import Starlette
    import httpx2
    app = Starlette(routes=routes)
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE) as c:
        codes = [(await c.post("/app/auth/passkey/options", json={}, headers=JSON_HDRS)).status_code
                 for _ in range(3)]
        assert codes == [200, 200, 429]


@run
async def test_coach_accounts_still_get_403(h: Harness) -> None:
    h.auth.coach_links.is_coach_user = lambda uid: uid.startswith("coach_")  # type: ignore[method-assign]
    token = h.auth.mint_session("coach_abc")
    async with h.client() as c:
        c.cookies.set(h.auth.session_cookie, token, domain=HOST)
        assert (await c.get("/app/api/me")).status_code == 200
        for path in ("/app/api/access", "/app/api/passkeys"):
            assert (await c.get(path)).status_code == 403
        assert (await c.post("/app/api/invites", json={}, headers=JSON_HDRS)).status_code == 403


@run
async def test_non_owner_cannot_invite_unless_enabled(h: Harness) -> None:
    h.rebuild(replace(h.settings, owner_user_ids=("holden",)))
    async with h.client() as c:
        await sign_in(h, c)  # friend: allowlisted but not the owner
        assert (await c.post("/app/api/invites", json={}, headers=JSON_HDRS)).status_code == 403
        acc = (await c.get("/app/api/access")).json()
        assert acc["owner"] is False and acc["members"] == [] and acc["invites"] == []
    h.rebuild(replace(h.settings, members_can_invite=True))
    async with h.client() as c:
        await sign_in(h, c)
        assert (await c.post("/app/api/invites", json={}, headers=JSON_HDRS)).status_code == 201
        assert (await c.delete("/app/api/members/u_123", headers=JSON_HDRS)).status_code == 403


@run
async def test_google_user_adds_lists_and_removes_passkeys(h: Harness) -> None:
    async with h.client() as c:
        await sign_in(h, c)
        a = Authenticator()
        o = await c.post("/app/api/passkeys/options", json={}, headers=JSON_HDRS)
        assert o.json()["publicKey"]["excludeCredentials"] == []
        r = await c.post("/app/api/passkeys", json={"credential": a.create(o.json()), "label": "iPhone"},
                         headers=JSON_HDRS)
        assert r.status_code == 201 and r.json()["passkeys"][0]["name"] == "iPhone"
        o2 = await c.post("/app/api/passkeys/options", json={}, headers=JSON_HDRS)
        assert o2.json()["publicKey"]["excludeCredentials"][0]["id"] == a.id
        assert o2.json()["publicKey"]["user"]["id"] == o.json()["publicKey"]["user"]["id"]  # stable handle
        c2, login = await passkey_login(h, a)
        assert login.status_code == 200 and (await c2.get("/app/api/me")).json()["user_id"] == "friend"
        # Google users may remove their last passkey (they still have Google)
        d = await c.delete(f"/app/api/passkeys/{a.id}", headers=JSON_HDRS)
        assert d.status_code == 200 and d.json()["passkeys"] == []
        _, gone = await passkey_login(h, a)
        assert gone.status_code == 400


@run
async def test_member_keeps_at_least_one_passkey(h: Harness) -> None:
    async with h.client() as owner:
        await sign_in(h, owner)
        token = await make_invite(owner)
        a = Authenticator()
        c, _ = await join(h, token, a)
        assert (await c.delete(f"/app/api/passkeys/{a.id}", headers=JSON_HDRS)).status_code == 409
        b = Authenticator()
        o = await c.post("/app/api/passkeys/options", json={}, headers=JSON_HDRS)
        assert (await c.post("/app/api/passkeys", json={"credential": b.create(o.json())},
                             headers=JSON_HDRS)).status_code == 201
        assert (await c.delete(f"/app/api/passkeys/{a.id}", headers=JSON_HDRS)).status_code == 200
        # someone else's passkey can't be removed
        assert (await owner.delete(f"/app/api/passkeys/{b.id}", headers=JSON_HDRS)).status_code == 404


def test_rate_limit_window() -> None:
    now = [0.0]
    rl = RateLimit(2, 10, clock=lambda: now[0])
    assert rl.allow("ip") and rl.allow("ip") and not rl.allow("ip")
    now[0] = 11
    assert rl.allow("ip")
    assert time.time() > 0
