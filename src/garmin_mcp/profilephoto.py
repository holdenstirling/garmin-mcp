"""The athlete's profile photo: one small image, resized in the browser (256x256), stored
Fernet-encrypted in the user's ``photo`` doc and served only to the owner and their coaches.

Content is checked by magic bytes (JPEG, PNG, WebP only), never by name or content type.
"""

from __future__ import annotations

import base64
import time
from collections.abc import Callable
from typing import Any

from .appstore import AppStore

MAX_PHOTO = 300 * 1024


class PhotoError(ValueError):
    """Message is safe to show the user."""


def sniff_photo(data: bytes) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    raise PhotoError("Use a JPEG, PNG or WebP photo.")


class PhotoStore:
    def __init__(self, store: AppStore, *, clock: Callable[[], float] = time.time) -> None:
        self._s = store
        self._clock = clock

    def _doc(self, user_id: str):
        return self._s.user_doc(user_id, "photo")

    def save(self, user_id: str, data: bytes) -> int:
        """Store the photo; returns its version (a timestamp, for cache-busting URLs)."""
        if not data:
            raise PhotoError("That photo is empty.")
        if len(data) > MAX_PHOTO:
            raise PhotoError("That photo is too large (max 300 KB).")
        mime = sniff_photo(data)
        ver = int(self._clock() * 1000)
        self._doc(user_id).save({"mime": mime, "size": len(data), "v": ver,
                                 "data": base64.b64encode(data).decode("ascii")})
        self._s.user_doc(user_id, "photo-meta").save({"v": ver})
        return ver

    def load(self, user_id: str) -> tuple[str, bytes] | None:
        d = self._doc(user_id).load()
        if not d.get("data"):
            return None
        data = base64.b64decode(d["data"])
        try:
            mime = sniff_photo(data)
        except PhotoError:
            return None
        return mime, data

    def version(self, user_id: str) -> int | None:
        v: Any = self._s.user_doc(user_id, "photo-meta").load().get("v")
        return v if isinstance(v, int) else None

    def delete(self, user_id: str) -> None:
        self._s.user_doc(user_id, "photo-meta").delete()
        self._doc(user_id).delete()


__all__ = ["MAX_PHOTO", "PhotoError", "PhotoStore", "sniff_photo"]
