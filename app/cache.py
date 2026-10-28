"""Tiny JSON file cache with per-key TTLs."""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Callable

from .config import CACHE_DIR


def _path(key: str):
    safe = hashlib.sha1(key.encode()).hexdigest()[:16]
    return CACHE_DIR / f"{safe}.json"


def cached(key: str, ttl_seconds: float | None, fetch: Callable[[], Any], force: bool = False) -> Any:
    """Return the cached value for key, calling fetch() when missing or expired.

    ttl_seconds=None means the entry never expires (used for completed seasons).
    If fetch() fails and a stale copy exists, the stale copy is returned.
    """
    p = _path(key)
    if p.exists() and not force:
        entry = json.loads(p.read_text(encoding="utf-8"))
        if ttl_seconds is None or time.time() - entry["ts"] < ttl_seconds:
            return entry["data"]
    try:
        data = fetch()
    except Exception:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))["data"]
        raise
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"key": key, "ts": time.time(), "data": data}), encoding="utf-8")
    return data


def cache_time(key: str) -> float | None:
    p = _path(key)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))["ts"]
