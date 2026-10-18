"""@mentions in feed posts and comments (pure helpers; rules live in ``community.py``).

Stored text carries a token per mention, ``@[Name](uid)``: the app inserts it when someone
picks a person from the @ list. Only tokens whose uid is in the item's own ``mentions`` list
are links; any other token (typed or forged by hand) is shown as plain ``@Name``, so nobody
can make a link to a person they weren't allowed to mention. The name shown is the person's
current name, filled in by the view.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

MAX_MENTIONS = 10
# The extra room tokens take in stored text (the display text keeps the normal limit).
TOKEN_ROOM = 140 * MAX_MENTIONS
TOKEN = re.compile(r"@\[([^\[\]\n]{1,60})\]\(([^\s()\[\]]{1,120})\)")


def ids(text: str) -> list[str]:
    """Mentioned uids in order of first appearance."""
    return list(dict.fromkeys(m.group(2) for m in TOKEN.finditer(text or "")))


def display(text: str) -> str:
    """The text as people read it: every token as ``@Name``."""
    return TOKEN.sub(lambda m: "@" + m.group(1).strip(), text or "")


def keep(text: str, allowed: Iterable[str]) -> str:
    """Tokens for ``allowed`` uids stay; every other token becomes plain ``@Name``."""
    ok = set(allowed)
    return TOKEN.sub(lambda m: m.group(0) if m.group(2) in ok else "@" + m.group(1).strip(), text or "")


__all__ = ["MAX_MENTIONS", "TOKEN", "TOKEN_ROOM", "display", "ids", "keep"]
