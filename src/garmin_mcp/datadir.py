"""Health probe for the data directory: can the service still save people's information?

``/healthz`` (MCP server and Rabbit) answers ``{"ok": true, "data_writable": true}`` only when
a small probe file can be created, written, fsynced and removed in ``DATA_DIR`` (a full disk,
a read-only remount or wrong ownership all make saves fail, and should fail the deploy's
health check and the uptime check instead of losing writes silently). The probe file is a
dot-file with a random name, never a user document. The result is cached for a few seconds
so a busy uptime checker doesn't touch the disk on every request.
"""

from __future__ import annotations

import contextlib
import os
import secrets
import threading
import time
from pathlib import Path

CACHE_S = 10.0


class WritableProbe:
    def __init__(self, path: Path | None, clock=time.monotonic) -> None:
        self._path = Path(path) if path is not None else None
        self._clock = clock
        self._lock = threading.Lock()
        self._last: tuple[float, bool] | None = None

    def check(self) -> bool:
        if self._path is None:
            return True
        with self._lock:
            now = self._clock()
            if self._last is not None and now - self._last[0] < CACHE_S:
                return self._last[1]
            ok = writable(self._path)
            self._last = (now, ok)
            return ok


def writable(path: Path) -> bool:
    probe = Path(path) / f".healthz-{secrets.token_hex(6)}.tmp"
    try:
        fd = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            os.write(fd, b"ok")
            os.fsync(fd)
        finally:
            os.close(fd)
        return True
    except OSError:
        return False
    finally:
        with contextlib.suppress(OSError):
            probe.unlink()
