"""Small encrypted JSON documents for the Rabbit web app.

Each document is one Fernet-encrypted file written by ``EncryptedFileTokenStore``
(atomic temp file + fsync + rename, 0600 files, 0700 dirs). Layout:

    <app_dir>/<name>.fernet                     global docs (sessions, identities)
    <app_dir>/users/<user_id>/<name>.fernet     per-user docs (push, profile, ...)

Per-user paths are derived only from a validated ``user_id``, so one user's
document can never resolve to another user's file.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .tokens import EncryptedFileTokenStore, validate_user_id


class Doc:
    def __init__(self, store: EncryptedFileTokenStore, name: str, lock: threading.Lock,
                 notify: Callable[[], None] | None = None) -> None:
        self._store = store
        self._name = name
        self._lock = lock
        self._notify = notify

    def _written(self) -> None:
        if self._notify is not None:
            self._notify()

    def load(self) -> dict[str, Any]:
        raw = self._store.load(self._name)
        return json.loads(raw) if raw else {}

    def save(self, data: dict[str, Any]) -> None:
        with self._lock:
            self._store.save(self._name, json.dumps(data, separators=(",", ":")))
        self._written()

    def update(self, fn: Callable[[dict[str, Any]], Any]) -> Any:
        """Load, mutate in place with ``fn``, save; returns ``fn``'s result."""
        with self._lock:
            raw = self._store.load(self._name)
            data = json.loads(raw) if raw else {}
            result = fn(data)
            self._store.save(self._name, json.dumps(data, separators=(",", ":")))
        self._written()
        return result

    def delete(self) -> None:
        with self._lock:
            self._store.delete(self._name)
        self._written()


class AppStore:
    def __init__(self, root: Path, key: bytes | str) -> None:
        self._root = Path(root)
        self._key = key
        self._guard = threading.Lock()
        self._stores: dict[Path, EncryptedFileTokenStore] = {}
        self._locks: dict[tuple[Path, str], threading.Lock] = {}
        self._listeners: list[Callable[[str, str], None]] = []
        for d in (self._root, self._root / "users"):
            d.mkdir(mode=0o700, parents=True, exist_ok=True)
            d.chmod(0o700)

    def on_user_write(self, fn: Callable[[str, str], None]) -> None:
        """Call ``fn(user_id, doc_name)`` after every write to a per-user doc (cache
        invalidation hooks: readiness, predictions). Listener errors are swallowed."""
        self._listeners.append(fn)

    def _fire(self, user_id: str, name: str) -> None:
        for fn in list(self._listeners):
            try:
                fn(user_id, name)
            except Exception:
                pass

    def _doc(self, directory: Path, name: str, notify: Callable[[], None] | None = None) -> Doc:
        validate_user_id(name)  # same charset rule: no path separators
        with self._guard:
            store = self._stores.get(directory)
            if store is None:
                store = self._stores[directory] = EncryptedFileTokenStore(directory, self._key)
            lock = self._locks.setdefault((directory, name), threading.Lock())
        return Doc(store, name, lock, notify)

    def global_doc(self, name: str) -> Doc:
        return self._doc(self._root, name)

    def user_doc(self, user_id: str, name: str) -> Doc:
        notify = (lambda: self._fire(user_id, name)) if self._listeners else None
        return self._doc(self._root / "users" / validate_user_id(user_id), name, notify)
