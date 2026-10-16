"""Never lose people's information: server writes, deploys, backups, health, idempotent retries.

* every write to the data dirs goes through the atomic encrypted store (static scan);
* deploy / bootstrap / backup scripts never delete or overwrite the data dirs;
* the nightly off-server backup script and its one-time setup (text assertions + a dry run);
* /healthz reports whether DATA_DIR can take a write;
* an Idempotency-Key makes retried check-ins, posts and comments happen once;
* sessions survive a restart (new WebAuth over the same store).
All clock-independent (fake clocks where time matters)."""

from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
import tarfile
from pathlib import Path

import httpx2
import pytest
from starlette.requests import Request

from garmin_mcp.appstore import AppStore
from garmin_mcp.config import Settings
from garmin_mcp.datadir import WritableProbe, writable
from garmin_mcp.idempotency import MAX_KEYS, TTL_S, Idempotency, InFlight, Mismatch, valid_key
from garmin_mcp.webauth import WebAuth
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_checkins import BASE, H, _apps
from tests.test_community import _clients, _setup

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "garmin_mcp"
INFRA = ROOT / "infra"

# ------------------------------------------------------- atomic writes only --
# The only modules allowed to open files for writing: the encrypted atomic store (tokens.py,
# which AppStore uses), the poller's atomic state file and the /healthz probe.
WRITERS = {"tokens.py", "poller.py", "datadir.py"}
WRITE_PATTERNS = re.compile(
    r"""open\([^)]*['"][wax]b?\+?['"]|\.write_text\(|\.write_bytes\(|json\.dump\(|pickle\.dump|"""
    r"""O_WRONLY|O_CREAT|O_RDWR|shutil\.(copy|move|rmtree)|os\.remove\(|os\.replace\(|os\.rename\(|"""
    r"""\.rename\(|\.unlink\(|mkstemp|NamedTemporaryFile|sqlite3""")


def test_no_direct_file_writes_outside_the_atomic_store() -> None:
    bad = []
    for p in sorted(SRC.rglob("*.py")):
        if p.name in WRITERS:
            continue
        for n, line in enumerate(p.read_text().splitlines(), 1):
            code = line.split("#", 1)[0]
            if WRITE_PATTERNS.search(code):
                bad.append(f"{p.relative_to(ROOT)}:{n}: {line.strip()}")
    assert not bad, "write through AppStore/EncryptedFileTokenStore instead:\n" + "\n".join(bad)


def test_the_allowed_writers_are_atomic() -> None:
    for name in ("tokens.py", "poller.py"):
        s = (SRC / name).read_text()
        assert "O_EXCL" in s and "fsync" in s and "os.replace(" in s, name
        assert s.index("fsync") < s.index("os.replace("), f"{name}: fsync before the rename"
    assert "EncryptedFileTokenStore" in (SRC / "appstore.py").read_text()


def test_appstore_write_is_complete_or_absent(tmp_path, fernet_key) -> None:
    store = AppStore(tmp_path, fernet_key)
    doc = store.user_doc("friend", "profile")
    doc.save({"a": 1})
    doc.update(lambda d: d.update(b=2))
    assert doc.load() == {"a": 1, "b": 2}
    leftovers = [p.name for p in (tmp_path / "users" / "friend").iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []
    assert oct((tmp_path / "users" / "friend" / "profile.fernet").stat().st_mode & 0o777) == "0o600"


# --------------------------------------------------- deploys keep the data --
DATA_REF = re.compile(r"/var/lib/(rabbit|garmin-mcp)(?![-\w])|\$\{?DATA_DIR\b")
DESTRUCTIVE = re.compile(r"\brm\b|\brmdir\b|\bshred\b|\btruncate\b|-delete\b|\bmv\b|\brsync\b.*--delete|"
                         r"tar\s+(-\w*x|x)|--extract|(^|[^0-9&>])>\s*[\"']?/var/lib/|\bdd\b|\bmkfs\b|\bchmod\s+-R\b")


def _scripts() -> list[Path]:
    out = [ROOT / "deploy.sh", *sorted(INFRA.glob("*.sh")), *sorted((INFRA / "backup").glob("*.sh")),
           *sorted((INFRA / "cloudshell").glob("*.sh"))]
    out += [p for p in sorted(INFRA.glob("*.service"))] + [p for p in sorted((INFRA / "backup").glob("*.service"))]
    return out


def test_deploy_and_bootstrap_scripts_never_delete_or_overwrite_data_dirs() -> None:
    bad = []
    for p in _scripts():
        for n, line in enumerate(p.read_text().splitlines(), 1):
            code = line.split("#", 1)[0] if not line.lstrip().startswith("#") else ""
            if DATA_REF.search(code) and DESTRUCTIVE.search(code):
                bad.append(f"{p.relative_to(ROOT)}:{n}: {line.strip()}")
    assert not bad, "\n".join(bad)


def test_deploy_only_removes_releases_and_its_own_bundle() -> None:
    lines = [ln for ln in (ROOT / "deploy.sh").read_text().splitlines()
             if re.search(r"\brm\b", ln) and not ln.lstrip().startswith("#")]
    assert lines, "deploy.sh cleanup lines moved?"
    for ln in lines:
        assert ("$BUNDLE" in ln or '"/tmp/$APP-$REL.tgz"' in ln
                or ('cd "/opt/$APP/releases"' in ln and "tail -n +4" in ln)), ln
    s = (ROOT / "deploy.sh").read_text()
    assert 'D=/opt/$APP/releases/$REL' in s and 'ln -sfn "$D" "/opt/$APP/current"' in s
    # The services may only write their own data dir, never the release.
    for unit in ("rabbit.service", "garmin-mcp.service"):
        u = (INFRA / unit).read_text()
        assert "ProtectSystem=strict" in u and re.search(r"ReadWritePaths=/var/lib/(rabbit|garmin-mcp)\b", u)
        assert "ExecStartPre" not in u


# ---------------------------------------------------- off-server backup kit --
BACKUP = INFRA / "backup" / "rabbit-backup.sh"
SETUP = INFRA / "cloudshell" / "14-offsite-backups.sh"


def test_backup_script_uploads_encrypted_data_only_and_never_keys() -> None:
    s = BACKUP.read_text()
    assert "SOURCES=(/var/lib/rabbit /var/lib/garmin-mcp)" in s
    for ex in ("--exclude='*fernet*key*'", "--exclude='*.key'", "--exclude='*.tmp'", "--exclude='.healthz-*'"):
        assert ex in s
    code = "\n".join(ln for ln in s.splitlines() if not ln.lstrip().startswith("#"))
    assert "secretmanager" not in code.lower() and "FERNET_KEY" not in code and "get_secret" not in code
    assert "/etc/" not in code.replace("/etc/rabbit-backup.env", "")
    # GCS: metadata-server token + curl, create-only, integrity-checked, no gcloud/gsutil dependency.
    assert "MD=http://metadata.google.internal/computeMetadata/v1" in s
    assert "$MD/instance/service-accounts/default/token" in s
    assert "x-goog-if-generation-match: 0" in s and "Content-MD5" in s
    assert "https://storage.googleapis.com/$BUCKET/$obj" in s
    assert "gsutil" not in code and "gcloud" not in code
    assert 'daily/$host/$stamp.tgz' in s and "monthly/" in s
    assert "last-success" in s and "set -euo pipefail" in s


def test_backup_units_and_installer() -> None:
    svc = (INFRA / "backup" / "rabbit-backup.service").read_text()
    timer = (INFRA / "backup" / "rabbit-backup.timer").read_text()
    inst = (INFRA / "backup" / "install.sh").read_text()
    assert "Type=oneshot" in svc and "ProtectSystem=strict" in svc and "ReadWritePaths=/var/lib/rabbit\n" not in svc
    assert "CapabilityBoundingSet=CAP_DAC_READ_SEARCH" in svc
    assert "OnCalendar=*-*-* 08:20:00 UTC" in timer and "Persistent=true" in timer
    assert "systemctl enable --now rabbit-backup.timer" in inst
    assert "/var/lib/rabbit-backup" in inst
    boot = (INFRA / "bootstrap-rabbit.sh").read_text()
    assert "infra/backup/install.sh" in boot


def test_offsite_setup_bucket_flags_iam_and_lifecycle() -> None:
    s = SETUP.read_text()
    assert "BUCKET=${BACKUP_BUCKET:-$PROJECT-rabbit-backups}" in s
    for flag in ("--uniform-bucket-level-access", "--public-access-prevention", "--versioning", "--lifecycle-file="):
        assert flag in s, flag
    assert '"age": 31, "matchesPrefix": ["daily/"]' in s and '"age": 366, "matchesPrefix": ["monthly/"]' in s
    assert '"isLive": false' in s
    assert "--role=roles/storage.objectCreator" in s
    assert "remove-iam-policy-binding" in s  # anything more than objectCreator is taken away
    for role in ("objectAdmin", "objectViewer", "storage.admin", "legacyBucket"):
        assert f"--role=roles/storage.{role}" not in s
    assert "--tunnel-through-iap" in s and "backup/install.sh" in s


def test_backup_dry_run_skips_temp_and_key_files(tmp_path) -> None:
    if not (shutil.which("bash") and shutil.which("openssl") and shutil.which("tar")):
        pytest.skip("needs bash, tar and openssl")
    rabbit, mcp = tmp_path / "rabbit", tmp_path / "garmin-mcp"
    (rabbit / "users" / "u1").mkdir(parents=True)
    (mcp / "tokens").mkdir(parents=True)
    (rabbit / "sessions.fernet").write_text("x")
    (rabbit / "users" / "u1" / "profile.fernet").write_text("y")
    (rabbit / ".profile.fernet.ab12.tmp").write_text("partial")
    (rabbit / "fernet.key").write_text("never")
    (rabbit / ".healthz-abc.tmp").write_text("ok")
    (mcp / "tokens" / "holden.fernet").write_text("z")
    r = subprocess.run(["bash", str(BACKUP)], capture_output=True, text=True, timeout=60,
                       env={"PATH": "/usr/bin:/bin:/usr/local/bin", "BACKUP_BUCKET": "test-bucket",
                            "BACKUP_SOURCES": f"{rabbit} {mcp}", "DRY_RUN": "1", "TMPDIR": str(tmp_path)})
    if r.returncode != 0 and "/var/tmp" in r.stderr:
        pytest.skip("no writable /var/tmp here")
    assert r.returncode == 0, r.stdout + r.stderr
    names = r.stdout
    assert "sessions.fernet" in names and "profile.fernet" in names and "holden.fernet" in names
    assert ".tmp" not in names and "fernet.key" not in names and "healthz" not in names
    assert "nothing uploaded" in r.stdout + r.stderr


def test_audit_and_infra_scripts_parse() -> None:
    for p in [ROOT / "deploy.sh", INFRA / "cloudshell" / "9-audit.sh", SETUP, BACKUP,
              INFRA / "backup" / "install.sh", INFRA / "bootstrap-rabbit.sh"]:
        r = subprocess.run(["bash", "-n", str(p)], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, f"{p.name}: {r.stderr}"
    audit = (INFRA / "cloudshell" / "9-audit.sh").read_text()
    assert "rabbit-backup.timer" in audit and "/var/lib/rabbit-backup/last-success" in audit
    assert "B_AGE < 36" in audit and "age < 36" in audit and "AGE_H < 36" in audit
    assert '"data_writable":true' in audit
    restore = (INFRA / "restore-backup.md").read_text()
    assert "gcloud storage cp" in restore and "source-snapshot" in restore and "chown -R rabbit:rabbit" in restore


def test_deploy_workflow_still_checks_the_app_is_up() -> None:
    wf = (ROOT / ".github" / "workflows" / "deploy.yml").read_text()
    assert "Check it's up" in wf and "/app/privacy" in wf


# ------------------------------------------------------------------ healthz --
def test_writable_probe(tmp_path) -> None:
    assert writable(tmp_path) and list(tmp_path.iterdir()) == []  # probe file removed
    assert not writable(tmp_path / "missing")
    t = [0.0]
    probe = WritableProbe(tmp_path, clock=lambda: t[0])
    assert probe.check()
    shutil.rmtree(tmp_path)
    assert probe.check()            # cached
    t[0] += 11
    assert not probe.check()        # re-checked: gone


def test_healthz_reports_data_dir_writable(tmp_path) -> None:
    from garmin_mcp.server import build_web_only_app

    async def go() -> None:
        for path, code, ok in ((tmp_path, 200, True), (tmp_path / "gone", 503, False)):
            app = build_web_only_app([], None, path)
            async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE) as c:
                r = await c.get("/healthz")
                assert r.status_code == code and r.json() == {"ok": ok, "data_writable": ok}
    asyncio.run(go())


# -------------------------------------------------------------- idempotency --
def test_idempotency_store_ttl_inflight_mismatch_cap(tmp_path, fernet_key) -> None:
    t = [1000.0]
    idem = Idempotency(AppStore(tmp_path, fernet_key), clock=lambda: t[0])
    assert valid_key("abcd1234") and not valid_key("short") and not valid_key("bad key!!") and not valid_key("x" * 81)
    slot, cached = idem.begin("u1", "POST", "/app/api/checkins", "k" * 16, b'{"a":1}')
    assert cached is None
    with pytest.raises(InFlight):
        idem.begin("u1", "POST", "/app/api/checkins", "k" * 16, b'{"a":1}')
    idem.begin("u2", "POST", "/app/api/checkins", "k" * 16, b'{"a":1}')  # other user: own slot
    idem.finish("u1", slot, b'{"a":1}', 201, b'{"id":"c1"}', "application/json")
    _, cached = idem.begin("u1", "POST", "/app/api/checkins", "k" * 16, b'{"a":1}')
    assert cached and cached["status"] == 201 and Idempotency.replay_body(cached) == b'{"id":"c1"}'
    with pytest.raises(Mismatch):
        idem.begin("u1", "POST", "/app/api/checkins", "k" * 16, b'{"a":2}')
    s2, cached = idem.begin("u1", "POST", "/app/api/other", "k" * 16, b'{"a":1}')  # other route
    assert cached is None
    idem.abort("u1", s2)
    t[0] += TTL_S + 1                                                             # forgotten after 24 h
    s3, cached = idem.begin("u1", "POST", "/app/api/checkins", "k" * 16, b'{"a":1}')
    assert cached is None
    idem.finish("u1", s3, b"", 500, b"{}", None)                                  # errors aren't remembered
    _, cached = idem.begin("u1", "POST", "/app/api/checkins", "k" * 16, b"")
    assert cached is None
    for i in range(MAX_KEYS + 20):
        s, _ = idem.begin("u3", "PUT", "/p", f"key-{i:06d}", b"")
        idem.finish("u3", s, b"", 200, b"{}", None)
    assert len(AppStore(tmp_path, fernet_key).user_doc("u3", "idempotency").load()) == MAX_KEYS


def test_retried_checkin_with_the_same_key_is_saved_once(env, tmp_path) -> None:
    agent, app = _apps(env, tmp_path)
    a = app("friend")

    async def go() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=a), base_url=BASE) as c:
            k = {**H, "idempotency-key": "retry-0123456789"}
            r1 = await c.post("/app/api/checkins", headers=k, json={"text": "Felt strong, slept well"})
            r2 = await c.post("/app/api/checkins", headers=k, json={"text": "Felt strong, slept well"})
            assert r1.status_code == r2.status_code == 201
            assert r2.headers.get("idempotent-replayed") == "true" and "idempotent-replayed" not in r1.headers
            assert r1.json()["checkin"]["id"] == r2.json()["checkin"]["id"]
            assert len((await c.get("/app/api/checkins?days=30")).json()["checkins"]) == 1
            r = await c.post("/app/api/checkins", headers=k, json={"text": "something else"})
            assert r.status_code == 422
            r = await c.post("/app/api/checkins", headers={**H, "idempotency-key": "no"}, json={"text": "x"})
            assert r.status_code == 400
            # Without a key nothing changes: two posts, two check-ins.
            await c.post("/app/api/checkins", headers=H, json={"text": "again"})
            await c.post("/app/api/checkins", headers=H, json={"text": "again"})
            assert len((await c.get("/app/api/checkins?days=30")).json()["checkins"]) == 3
            # A key is only honoured on mutating calls with a valid Origin.
            assert (await c.post("/app/api/checkins", headers={"idempotency-key": "retry-0123456789"},
                                 json={"text": "x"})).status_code == 403
    asyncio.run(go())


def test_retried_post_and_comment_are_created_once(env, tmp_path) -> None:
    apps, _push, _agent = _setup(env, tmp_path)

    async def go() -> None:
        c = _clients(apps)
        ann, bob = c["ann"], c["bob"]
        await bob.post("/app/api/social/follow", headers=H, json={"email": "ann@x.com"})  # bob sees ann's posts
        eid = (await ann.get("/app/api/social")).json()["pending_in"][0]["edge_id"]
        await ann.post(f"/app/api/social/requests/{eid}/accept", headers=H, json={})
        k = {**H, "idempotency-key": "post-abcdef123456"}
        r1 = await ann.post("/app/api/community/posts", headers=k, json={"text": "Long run done", "category": "other"})
        r2 = await ann.post("/app/api/community/posts", headers=k, json={"text": "Long run done", "category": "other"})
        assert r1.status_code == 201 and r2.status_code == 201, r1.text
        pid = r1.json()["post"]["id"]
        assert r2.json()["post"]["id"] == pid
        mine = (await ann.get("/app/api/community/feed")).json()["items"]
        assert [p["id"] for p in mine].count(pid) == 1 and len(mine) == 1
        ck = {**H, "idempotency-key": "comment-0987654321"}
        for _ in range(3):
            r = await bob.post(f"/app/api/community/posts/{pid}/comments", headers=ck, json={"text": "Nice!"})
            assert r.status_code == 201
        full = (await ann.get(f"/app/api/community/posts/{pid}")).json()["post"]
        assert len(full["comments"]) == 1
        # Same key, other user: their own slot (keys are per user).
        r = await bob.post("/app/api/community/posts", headers=k, json={"text": "Mine", "category": "other"})
        assert r.status_code == 201 and r.json()["post"]["id"] != pid
        for cl in c.values():
            await cl.aclose()
    asyncio.run(go())


# --------------------------------------------------------- session restarts --
def _req(cookie: str, value: str) -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "query_string": b"",
                    "headers": [(b"cookie", f"{cookie}={value}".encode())]})


def test_sessions_survive_a_restart_for_the_configured_ttl(tmp_path, fernet_key) -> None:
    t = [1_000_000.0]
    settings = Settings(public_base_url="https://rabbit.example.com", data_dir=tmp_path, app_enabled=True,
                        mcp_enabled=False, allowed_google_users={"friend@example.com": "friend"},
                        app_session_ttl_seconds=30 * 86400)
    store = AppStore(tmp_path / "app", fernet_key)
    first = WebAuth(settings, store, "", clock=lambda: t[0])
    token = first.mint_session("friend")
    # New process (deploy/restart): a fresh WebAuth over the same data dir knows the session.
    again = WebAuth(settings, AppStore(tmp_path / "app", fernet_key), "", clock=lambda: t[0])
    assert again.user_for(_req(again.session_cookie, token)) == "friend"
    t[0] += 29 * 86400
    assert again.user_for(_req(again.session_cookie, token)) == "friend"  # within the TTL (sliding)
    t[0] += 31 * 86400 + 1
    assert WebAuth(settings, AppStore(tmp_path / "app", fernet_key), "", clock=lambda: t[0]).user_for(
        _req(again.session_cookie, token)) is None
