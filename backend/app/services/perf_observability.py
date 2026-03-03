from __future__ import annotations

import json
import time
from typing import Any


def _now_ms() -> float:
    return time.perf_counter() * 1000.0


def latency_bucket(ms: float) -> str:
    if ms >= 20000:
        return ">=20s"
    if ms >= 5000:
        return ">=5s"
    if ms >= 1000:
        return ">=1s"
    return "<1s"


def log_perf_event(
    *,
    endpoint: str,
    total_ms: float,
    db_ms: float = 0.0,
    rows_scanned: int | None = None,
    rows_returned: int | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "event": "PERF_ENDPOINT",
        "endpoint": endpoint,
        "total_ms": round(float(total_ms), 3),
        "db_ms": round(float(db_ms), 3),
        "latency_bucket": latency_bucket(float(total_ms)),
    }
    if rows_scanned is not None:
        payload["rows_scanned"] = int(rows_scanned)
    if rows_returned is not None:
        payload["rows_returned"] = int(rows_returned)
    if extra:
        payload.update(extra)
    print(json.dumps(payload, default=str))


def timed_call(fn, *args, **kwargs):
    started = _now_ms()
    out = fn(*args, **kwargs)
    elapsed_ms = _now_ms() - started
    return out, elapsed_ms
