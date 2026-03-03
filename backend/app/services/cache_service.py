from __future__ import annotations

import time
from threading import Lock
from typing import Any, Callable

_CACHE: dict[str, tuple[float, Any]] = {}
_LOCK = Lock()


def _now() -> float:
    return float(time.time())


def get_cached(key: str) -> Any | None:
    with _LOCK:
        payload = _CACHE.get(str(key))
        if payload is None:
            return None
        expires_at, value = payload
        if expires_at <= _now():
            _CACHE.pop(str(key), None)
            return None
        return value


def set_cached(key: str, value: Any, ttl_seconds: float = 3.0) -> Any:
    ttl = max(0.1, float(ttl_seconds))
    with _LOCK:
        _CACHE[str(key)] = (_now() + ttl, value)
    return value


def get_or_set_cached(key: str, producer: Callable[[], Any], ttl_seconds: float = 3.0) -> Any:
    cached = get_cached(key)
    if cached is not None:
        return cached
    value = producer()
    return set_cached(key, value, ttl_seconds=ttl_seconds)


def invalidate_cache(prefix: str | None = None):
    with _LOCK:
        if prefix is None:
            _CACHE.clear()
            return
        pref = str(prefix)
        keys = [k for k in _CACHE.keys() if k.startswith(pref)]
        for key in keys:
            _CACHE.pop(key, None)
