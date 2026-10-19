"""Google Sheets / Docs links pasted into "Add a plan": fetched server-side, but only from
Google's own document host and only in its export / publish-to-web shapes, so a pasted link
can never make Rabbit reach anything else (SSRF-safe by allowlist, not by blocklist):

* ``https://docs.google.com/spreadsheets/d/e/<pub id>/pub?output=csv`` (File -> Share ->
  Publish to web -> CSV) and ``.../pubhtml`` (rewritten to ``pub?output=csv``);
* ``https://docs.google.com/spreadsheets/d/<id>/export?format=csv`` and an ordinary
  ``.../edit#gid=N`` sharing link (rewritten to that export; works when the sheet is shared
  with "anyone with the link");
* ``https://docs.google.com/document/d/<id>/export?format=txt`` (and ``/edit`` links
  rewritten to it) and published docs ``.../document/d/e/<pub id>/pub``.

Only https, no user info, no port, host exactly ``docs.google.com``. Redirects are followed
by hand (at most 4) and only to ``docs.google.com`` or ``*.googleusercontent.com`` (where
Google serves the export); a redirect to the sign-in page means the document is private.
Bodies are capped at 2 MB while streaming. ``fetch_google`` takes a transport for tests.
"""

from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx2

from .planbuilder import PlanError

MAX_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 4
TIMEOUT = 10.0
HOST = "docs.google.com"
_ID = r"[A-Za-z0-9_-]{10,200}"
_REDIRECT_HOST = re.compile(r"^(docs\.google\.com|[a-z0-9-]{1,80}\.googleusercontent\.com)$")
PRIVATE = ("That document isn't public, so rabbt can't open it. In Google {kind} choose File → "
           "Share → Publish to web ({fmt}) and paste that link, or download it and drop the file here.")


class LinkError(PlanError):
    """Shown to the user as-is."""


def google_export_url(url: str) -> tuple[str, str] | None:
    """(URL to fetch, 'csv' | 'text' | 'html') for an allowed Google Sheets/Docs link, else
    None (the caller explains what to do instead)."""
    s = (url or "").strip()
    if len(s) > 2000 or any(c.isspace() for c in s):
        return None
    try:
        u = urlsplit(s)
    except ValueError:
        return None
    if u.scheme != "https" or u.hostname != HOST or u.port is not None or u.username or u.password \
            or (u.netloc.lower() != HOST):
        return None
    path, q = u.path, parse_qs(u.query)
    gid = (q.get("gid") or [None])[0]
    if gid is None:
        m = re.search(r"(?:^|&)gid=(\d{1,12})", u.fragment)
        gid = m[1] if m else None
    if gid is not None and not re.fullmatch(r"\d{1,12}", gid):
        gid = None
    base = f"https://{HOST}"
    m = re.fullmatch(rf"/spreadsheets/d/e/({_ID})/(pub|pubhtml)", path)
    if m:
        args = {"output": "csv"}
        if gid:
            args |= {"gid": gid, "single": "true"}
        return f"{base}/spreadsheets/d/e/{m[1]}/pub?{urlencode(args)}", "csv"
    m = re.fullmatch(rf"/spreadsheets/d/({_ID})(?:/(?:edit|view|export|htmlview|preview)?)?/?", path)
    if m:
        args = {"format": "csv"}
        if gid:
            args["gid"] = gid
        return f"{base}/spreadsheets/d/{m[1]}/export?{urlencode(args)}", "csv"
    m = re.fullmatch(rf"/document/d/e/({_ID})/pub", path)
    if m:
        return f"{base}/document/d/e/{m[1]}/pub", "html"
    m = re.fullmatch(rf"/document/d/({_ID})(?:/(?:edit|view|export|preview|mobilebasic)?)?/?", path)
    if m:
        return f"{base}/document/d/{m[1]}/export?format=txt", "text"
    return None


def redirect_ok(location: str) -> bool:
    try:
        u = urlsplit(location)
    except ValueError:
        return False
    return u.scheme == "https" and u.port is None and not u.username and not u.password \
        and bool(_REDIRECT_HOST.match((u.hostname or "").lower())) and (u.netloc.lower() == (u.hostname or "").lower())


def html_text(raw: str) -> str:
    """Readable text of a published Google Doc page (scripts and styles dropped)."""
    s = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", " ", raw)
    s = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr|h[1-6])>", "\n", s)
    s = re.sub(r"(?i)</t[dh]>", "\t", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    lines = [" ".join(x.split()) if "\t" not in x else "\t".join(c.strip() for c in x.split("\t")) for x in s.splitlines()]
    return "\n".join(x for x in lines if x.strip()).strip()


async def fetch_google(url: str, *, transport: Any = None) -> tuple[str, bytes, str]:
    """(kind 'csv' | 'text', body, file name) for an allowed Google link. Raises LinkError
    with a plain message otherwise."""
    got = google_export_url(url)
    if got is None:
        raise LinkError("rabbt only opens Google Sheets and Docs links. Download the file and drop it here, "
                        "or paste the plan's text.")
    target, kind = got
    sheet = "/spreadsheets/" in target
    private = PRIVATE.format(kind="Sheets" if sheet else "Docs", fmt="CSV" if sheet else "web page")
    client = httpx2.AsyncClient(timeout=TIMEOUT, transport=transport, follow_redirects=False) if transport is not None \
        else httpx2.AsyncClient(timeout=TIMEOUT, follow_redirects=False)
    async with client:
        for _ in range(MAX_REDIRECTS + 1):
            async with client.stream("GET", target, headers={"accept": "text/csv,text/plain,text/html;q=0.5"}) as r:
                if r.status_code in (301, 302, 303, 307, 308):
                    loc = r.headers.get("location", "")
                    if loc.startswith("/"):
                        loc = f"https://{urlsplit(target).hostname}{loc}"
                    if "accounts.google.com" in loc or "ServiceLogin" in loc:
                        raise LinkError(private)
                    if not redirect_ok(loc):
                        raise LinkError("That link went somewhere rabbt doesn't open. Download the file and drop it here.")
                    target = loc
                    continue
                if r.status_code in (401, 403, 404):
                    raise LinkError(private)
                if r.status_code != 200:
                    raise LinkError("Google didn't send the document just now. Try again in a minute.")
                declared = r.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > MAX_BYTES:
                    raise LinkError("That document is too large (max 2 MB).")
                buf = bytearray()
                async for chunk in r.aiter_bytes():
                    buf += chunk
                    if len(buf) > MAX_BYTES:
                        raise LinkError("That document is too large (max 2 MB).")
                ctype = r.headers.get("content-type", "").lower()
                break
        else:
            raise LinkError("That link redirected too many times.")
    body = bytes(buf)
    if not body.strip():
        raise LinkError("That document is empty.")
    if kind == "csv":
        if "text/html" in ctype:
            raise LinkError(private)
        return "csv", body, "Google Sheet.csv"
    if kind == "html" or "text/html" in ctype:
        text = html_text(body.decode("utf-8", errors="replace"))
        if not text:
            raise LinkError(private)
        return "text", text.encode(), "Google Doc.txt"
    return "text", body, "Google Doc.txt"


__all__ = ["google_export_url", "redirect_ok", "fetch_google", "html_text", "LinkError", "MAX_BYTES"]
