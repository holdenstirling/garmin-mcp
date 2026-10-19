"""Privacy & legal: documents, consent (re-asked on a version bump), download my data (secrets
removed, rate limited), delete my account (data and shared indexes gone)."""

from __future__ import annotations

import asyncio
import io
import json
import zipfile

import httpx2
from starlette.applications import Starlette

from garmin_mcp import legal
from garmin_mcp import consent as consent_mod
from garmin_mcp.account import REMOVED, AccountData, RateLimited, redact
from garmin_mcp.appstore import AppStore
from garmin_mcp.coaches import coach_user_id
from garmin_mcp.config import Settings
from garmin_mcp.consent import Consent, ConsentError
from garmin_mcp.tokens import generate_key
from garmin_mcp.webapp import COACH_PATHS, ChatRunner, build_app_routes
from garmin_mcp.webauth import WebAuth
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_profile import BASE, COACH

ALL = {"terms": True, "privacy": True, "age16": True, "health": True}


def _store(tmp_path) -> AppStore:
    return AppStore(tmp_path / "app", generate_key())


# ------------------------------------------------------------------- documents --
def test_documents_have_the_promises_and_operator() -> None:
    for slug in legal.DOCS:
        page = legal.page(slug)
        assert legal.OPERATOR in page and legal.VERSION in page and "holdenstirling@gmail.com" in page
        assert "@media print" in page and "prefers-color-scheme:dark" in page and "<nav" in page
    p, t = legal.privacy(), legal.terms()
    for phrase in ("Colorado Privacy Act", "CCPA", "GDPR", "under 16", "Anthropic", "14 days", "30 days",
                   "12 months", "Download your data", "delete your account", "Cookies and storage",
                   "doesn't sell", "Sponsored partner"):
        assert phrase in p, phrase
    for phrase in ("16 or older", "Not medical advice", "Colorado", "Sponsored partner", "community guidelines"):
        assert phrase in t, phrase
    assert "Secret Manager" in legal.security() and "Report" in legal.guidelines()
    # Owner-only lawyer note stays in the source, never on a page.
    assert "lawyer" not in "".join(legal.page(s) for s in legal.DOCS)
    assert "me@x.com" in legal.body_html("privacy", "me@x.com") and "<html" not in legal.body_html("privacy")


# --------------------------------------------------------------------- consent --
def test_consent_needs_every_box_and_reasks_on_version_bump(tmp_path, monkeypatch) -> None:
    c = Consent(_store(tmp_path), clock=lambda: 1000)
    assert c.needed("u") and c.view("u")["first"]
    for k in ALL:
        try:
            c.accept("u", dict(ALL, **{k: False}))
            raise AssertionError(k)
        except ConsentError:
            pass
    v = c.accept("u", ALL)
    assert not v["needed"] and v["accepted_at"] == 1000 and v["accepted_version"] == legal.VERSION
    monkeypatch.setattr(legal, "VERSION", "2099-01-01")
    assert c.needed("u") and not c.view("u")["first"]
    try:
        c.accept("u", dict(ALL, version="2026-01-01"))  # agreed to an old copy
        raise AssertionError
    except ConsentError:
        pass
    c.accept("u", ALL)
    assert not c.needed("u") and len(c.get("u")["history"]) == 2
    assert consent_mod.REQUIRED == ("terms", "privacy", "age16", "health")


# ---------------------------------------------------------------------- export --
def test_redact_removes_credentials_at_any_depth() -> None:
    d = redact({"refresh_token": "abc", "a": [{"cookie": "x", "keep": 1}], "settings": {"private": True},
                "push": {"endpoint": "https://p", "keys": {"p256dh": "k", "auth": "s"}}, "hash": "h",
                "name": "Bo", "token_count": 0})
    assert d["refresh_token"] == d["a"][0]["cookie"] == d["hash"] == REMOVED
    assert d["push"]["endpoint"] == REMOVED and d["push"]["keys"]["p256dh"] == REMOVED
    assert d["a"][0]["keep"] == 1 and d["name"] == "Bo" and d["settings"] == {"private": True}


def test_export_zip_has_every_doc_without_secrets_and_is_rate_limited(tmp_path) -> None:
    s = _store(tmp_path)
    s.user_doc("u", "profile").save({"name": "Bo", "goal": "marathon"})
    s.user_doc("u", "oura").save({"refresh_token": "SECRET-1", "workouts": [{"sport": "run"}]})
    s.user_doc("u", "trainingpeaks").save({"cookie": "SECRET-2", "athlete_id": 7})
    s.user_doc("u", "push").save({"subs": [{"endpoint": "https://push", "keys": {"auth": "SECRET-3"}}]})
    s.user_doc("other", "profile").save({"name": "Not me"})
    a = AccountData(s, clock=lambda: 0)
    a.add_extra("follows", lambda u: {"follows": [u]})
    z = zipfile.ZipFile(io.BytesIO(a.export_zip("u")))
    names = set(z.namelist())
    assert {"README.txt", "docs/profile.json", "docs/oura.json", "docs/trainingpeaks.json",
            "extra/follows.json"} <= names and "docs/push.json" not in names
    blob = b"".join(z.read(n) for n in names)
    assert b"SECRET" not in blob and b"Not me" not in blob
    assert json.loads(z.read("docs/oura.json"))["workouts"] == [{"sport": "run"}]
    a.export_zip("u")
    a.export_zip("u")
    try:
        a.export_zip("u")
        raise AssertionError("4th export within the hour")
    except RateLimited:
        pass


# ---------------------------------------------------------------------- delete --
def test_delete_runs_every_hook_even_if_one_fails_and_removes_the_folder(tmp_path) -> None:
    s = _store(tmp_path)
    s.user_doc("u", "profile").save({"name": "Bo"})
    s.user_doc("u", "events").save({"events": {}})
    s.user_doc("keep", "profile").save({"name": "Al"})
    a = AccountData(s)
    ran: list[str] = []

    async def ahook(u: str) -> None:
        ran.append("async:" + u)

    def boom(u: str) -> None:
        raise RuntimeError("down")
    a.on_delete("one", lambda u: ran.append("one:" + u))
    a.on_delete("boom", boom)
    a.on_delete("two", ahook)
    out = asyncio.run(a.delete("u", final=lambda u: ran.append("sessions")))
    assert ran == ["one:u", "async:u", "sessions"] and out == {"files": 2, "failed": ["boom"]}
    assert s.user_doc_names("u") == [] and s.user_doc("u", "profile").load() == {}
    assert s.user_doc("keep", "profile").load() == {"name": "Al"}


def _app(env, tmp_path, user: str):
    settings = Settings(public_base_url=BASE, data_dir=tmp_path, app_enabled=True, mcp_enabled=False,
                        allowed_google_users={"friend@example.com": "friend", "other@example.com": "other"},
                        owner_user_ids=("friend",), contact_email="")
    agent, _ = env.agent([])
    return Starlette(routes=build_app_routes(settings, WebAuth(settings, env.store, "", dev_user=user),
                                             env.tokens, None, None, ChatRunner(agent)))


def test_account_api_end_to_end(env, tmp_path) -> None:
    h = {"origin": BASE}
    me_app, other_app, coach_app = (_app(env, tmp_path, "friend"), _app(env, tmp_path, "other"),
                                    _app(env, tmp_path, coach_user_id(COACH)))

    async def go() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=me_app), base_url=BASE) as a, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=other_app), base_url=BASE) as o, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=coach_app), base_url=BASE) as c:
            # Consent: shown until accepted; coaches agree too.
            assert (await o.get("/app/api/me")).json()["consent"]["needed"] is True
            assert (await o.post("/app/api/consent", headers=h, json={"terms": True})).status_code == 400
            assert (await o.post("/app/api/consent", json=ALL)).status_code == 403  # no origin
            r = await o.post("/app/api/consent", headers=h, json=ALL)
            assert r.status_code == 200 and r.json()["needed"] is False
            assert (await o.get("/app/api/me")).json()["consent"]["needed"] is False
            assert (await c.get("/app/api/consent")).status_code == 200
            assert (await c.post("/app/api/consent", headers=h, json=ALL)).status_code == 200
            # In-app documents.
            r = await o.get("/app/api/legal/privacy")
            assert r.status_code == 200 and "never sent to the AI coach" in r.json()["html"]
            assert "holdenstirling@gmail.com" in r.json()["html"]  # default contact
            assert (await o.get("/app/api/legal/nope")).status_code == 404
            assert (await c.get("/app/api/legal/terms")).status_code == 200
            hd = await o.get("/app/api/legal/health-data")
            assert hd.status_code == 200 and "My Health My Data" in hd.json()["html"]
            for path in ("/app/security", "/app/guidelines", "/app/privacy", "/app/terms", "/app/about", "/app/health-data"):
                p = await o.get(path)
                assert p.status_code == 200 and "frame-ancestors 'none'" in p.headers["content-security-policy"]
            # Social data the other person shares with me.
            r = await o.post("/app/api/social/follow", headers=h, json={"email": "friend@example.com"})
            assert r.status_code in (200, 201), r.text
            assert (env.store.global_doc("social").load().get("edges") or {})
            env.store.user_doc("other", "profile").update(lambda d: d.update(name="Ozzy"))
            # Export.
            r = await o.get("/app/api/account/export")
            assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
            assert "attachment" in r.headers["content-disposition"]
            z = zipfile.ZipFile(io.BytesIO(r.content))
            assert "docs/profile.json" in z.namelist() and "docs/consent.json" in z.namelist()
            # Delete: needs the typed word; the owner can't.
            assert (await o.post("/app/api/account/delete", headers=h, json={"confirm": "delete"})).status_code == 400
            assert (await a.post("/app/api/account/delete", headers=h, json={"confirm": "DELETE"})).status_code == 409
            r = await o.post("/app/api/account/delete", headers=h, json={"confirm": "DELETE"})
            assert r.status_code == 200 and r.json()["ok"] is True, r.text
            assert env.store.user_doc_names("other") == []
            social = env.store.global_doc("social").load()
            assert "other" not in (social.get("users") or {})
            assert not any("other" in (e.get("follower"), e.get("followee")) for e in (social.get("edges") or {}).values())
            # Starting again means agreeing again.
            assert (await o.get("/app/api/me")).json()["consent"]["first"] is True
    asyncio.run(go())


def test_coach_accounts_can_reach_privacy_routes() -> None:
    for p in ("/app/api/consent", "/app/api/legal/privacy", "/app/api/account/export", "/app/api/account/delete"):
        assert p.startswith(COACH_PATHS)


def test_health_data_policy_breach_and_data_promise() -> None:
    assert legal.VERSION == "2026-10-19"
    hd = legal.health_data()
    for phrase in ("consumer health data", "My Health My Data", "Nevada", "Connecticut", "never sell",
                   "Withdraw consent", "Appeal", "attorney general", "45 days", "Google Cloud", "Anthropic",
                   "rabbt LLC", "holdenstirling@gmail.com"):
        assert phrase.lower() in hd.lower(), phrase
    for page in (legal.privacy(), legal.security()):
        assert "If there's a breach" in page and "60 days" in page and "Health Breach Notification Rule" in page
    t = legal.terms()
    assert "/app/health-data" in t and "at your own risk" in t and "Not medical advice" in t
    assert legal.DATA_PROMISE == "We never sell your data or use it for ads."
    assert legal.DATA_PROMISE in legal.FOOTER and "/app/health-data" in legal.FOOTER


def test_sharing_consent_is_separate_optional_and_recorded(tmp_path) -> None:
    c = Consent(_store(tmp_path), clock=lambda: 1000)
    v = c.accept("u", ALL)  # sharing is optional: not ticking it is fine
    assert not v["needed"] and v["share"] is None
    try:
        c.accept("u", dict(ALL, share="yes"))
        raise AssertionError
    except ConsentError:
        pass
    v = c.accept("u", dict(ALL, share=True))
    assert v["share"] is True and c.get("u")["share_ts"] == 1000
    assert c.accept("u", dict(ALL, share=False))["share"] is False


def test_every_legal_page_states_the_data_promise() -> None:
    from garmin_mcp import legal
    for slug in legal.DOCS:
        assert legal.DATA_PROMISE in legal.page(slug), slug
