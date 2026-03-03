from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

from fastapi.encoders import jsonable_encoder

from app.services.cache_service import get_or_set_cached


def _json_event(payload: dict[str, Any], event: str = "delta") -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


async def stream_allocations_delta(
    *,
    role: str,
    role_code: str | None,
    fetcher,
    interval_seconds: float = 1.5,
) -> AsyncIterator[str]:
    last_run_id = 0
    last_allocation_id = 0

    yield _json_event({"role": role, "status": "connected"}, event="connected")

    while True:
        cache_key = f"stream:{role}:{role_code or 'global'}:{last_run_id}:{last_allocation_id}"

        payload = get_or_set_cached(
            cache_key,
            lambda: fetcher(last_run_id, last_allocation_id),
            ttl_seconds=1.5,
        )

        rows = payload.get("rows", []) if isinstance(payload, dict) else []
        latest_run_id = int((payload or {}).get("latest_run_id", last_run_id) or last_run_id)
        latest_allocation_id = int((payload or {}).get("latest_allocation_id", last_allocation_id) or last_allocation_id)

        if rows:
            serializable_rows = jsonable_encoder(rows)
            yield _json_event(
                {
                    "rows": serializable_rows,
                    "latest_run_id": latest_run_id,
                    "latest_allocation_id": latest_allocation_id,
                }
            )
            last_run_id = max(last_run_id, latest_run_id)
            last_allocation_id = max(last_allocation_id, latest_allocation_id)
        else:
            yield _json_event({"heartbeat": True, "latest_run_id": last_run_id, "latest_allocation_id": last_allocation_id}, event="heartbeat")

        await asyncio.sleep(max(0.5, float(interval_seconds)))
