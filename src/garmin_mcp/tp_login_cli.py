"""garmin-mcp-trainingpeaks-login: store a TrainingPeaks session cookie, encrypted.

TrainingPeaks has no personal API, so this uses your browser session:
  1. Sign in at https://app.trainingpeaks.com
  2. Open developer tools -> Application (Chrome) or Storage (Firefox) -> Cookies
     -> https://app.trainingpeaks.com, and copy the value of Production_tpAuth.
  3. On the server, as the service user:
         sudo garmin-mcp-trainingpeaks-login --user holden
     and paste the value when prompted (input is hidden, nothing is echoed or logged).

The cookie is verified once against TrainingPeaks, then written Fernet-encrypted to
$DATA_DIR/trainingpeaks/<user>.fernet. It usually lasts a few weeks; re-run this when
the tools say the TrainingPeaks session expired.
"""

from __future__ import annotations

import argparse
import getpass
import logging
import os
import sys

from .config import Settings
from .logs import redact, setup_logging
from .providers import GarminError
from .secrets import get_secret
from .tokens import EncryptedFileTokenStore, TokenStore, validate_user_id
from .trainingpeaks import COOKIE_NAME, TrainingPeaksClient


class _OneShotStore(TokenStore):
    """Holds the pasted cookie in memory so it can be verified before it's saved."""

    def __init__(self, cookie: str) -> None:
        self.cookie = cookie

    def load(self, user_id: str) -> str | None:
        return self.cookie

    def save(self, user_id: str, blob: str) -> None:  # pragma: no cover - never called
        raise NotImplementedError

    def delete(self, user_id: str) -> None:  # pragma: no cover - never called
        raise NotImplementedError


def clean_cookie(raw: str) -> str:
    """Accept the bare value, ``Production_tpAuth=<value>`` or a whole Cookie header."""
    raw = raw.strip().strip('"').strip("'")
    for part in raw.split(";"):
        part = part.strip()
        if part.startswith(f"{COOKIE_NAME}="):
            return part.split("=", 1)[1].strip()
    return raw


def main(argv: list[str] | None = None, *, client_factory=TrainingPeaksClient) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--user", required=True, help="internal user id (e.g. holden)")
    ap.add_argument("--delete", action="store_true", help="delete the stored cookie and exit")
    args = ap.parse_args(argv)

    os.umask(0o077)
    os.environ.setdefault("PUBLIC_BASE_URL", "http://localhost")
    settings = Settings.from_env()
    setup_logging("WARNING")
    logging.getLogger("garmin_mcp").setLevel(logging.INFO)

    user_id = validate_user_id(args.user)
    key = get_secret(settings.fernet_key_secret_name, "GARMIN_MCP_FERNET_KEY", settings.gcp_project)
    store = EncryptedFileTokenStore(settings.trainingpeaks_dir, key)

    if args.delete:
        store.delete(user_id)
        print(f"Deleted the TrainingPeaks cookie for {user_id}.")
        return 0

    cookie = clean_cookie(getpass.getpass(f"{COOKIE_NAME} cookie value (hidden): "))
    if len(cookie) < 20 or any(c.isspace() for c in cookie):
        print("That doesn't look like a Production_tpAuth value.", file=sys.stderr)
        return 2

    print("Checking the cookie with TrainingPeaks...")
    client = client_factory(_OneShotStore(cookie))
    try:
        user = client.user(user_id)
        athlete = client.athlete_id(user_id)
    except GarminError as e:
        print(f"TrainingPeaks rejected it: {redact(str(e))[:300]}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Check failed ({type(e).__name__}).", file=sys.stderr)
        return 1

    store.save(user_id, cookie)
    name = " ".join(x for x in (user.get("firstName"), user.get("lastName")) if x) or "your account"
    print(f"Verified {name} (athlete {athlete}). Saved, encrypted, to "
          f"{settings.trainingpeaks_dir}/{user_id}.fernet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
