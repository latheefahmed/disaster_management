from __future__ import annotations

from dataclasses import dataclass
from sqlalchemy.orm import Session

from app.models.resource import Resource
from app.services.canonical_resources import (
    CANONICAL_RESOURCE_SET,
    canonicalize_resource_id,
)


@dataclass(frozen=True)
class ResourceDictionary:
    by_id_exact: dict[str, str]
    by_id_lower: dict[str, str]
    by_canonical_lower: dict[str, list[str]]


def load_resource_dictionary(db: Session) -> ResourceDictionary:
    rows = db.query(Resource).all()
    by_id_exact: dict[str, str] = {}
    by_id_lower: dict[str, str] = {}
    by_canonical_lower: dict[str, list[str]] = {}

    for row in rows:
        rid = str(row.resource_id or "").strip()
        if not rid:
            continue
        by_id_exact[rid] = rid
        by_id_lower[rid.lower()] = rid

        canonical = str(row.canonical_name or "").strip().lower()
        if canonical:
            by_canonical_lower.setdefault(canonical, []).append(rid)

    return ResourceDictionary(
        by_id_exact=by_id_exact,
        by_id_lower=by_id_lower,
        by_canonical_lower=by_canonical_lower,
    )


def resolve_resource_id(db: Session, resource_id, strict: bool = True) -> str:
    raw = str(resource_id or "").strip()
    if not raw:
        if strict:
            raise ValueError("Resource ID is required")
        return raw

    normalized = canonicalize_resource_id(raw)
    if normalized in CANONICAL_RESOURCE_SET:
        return normalized

    dictionary = load_resource_dictionary(db)
    if not dictionary.by_id_lower:
        if strict:
            raise ValueError("Unknown resource. Unknown resource_id. Use exact canonical resource_id from catalog.")
        return raw

    exact = dictionary.by_id_exact.get(raw)
    if exact:
        exact_normalized = canonicalize_resource_id(exact)
        if exact_normalized in CANONICAL_RESOURCE_SET:
            return exact_normalized
        if strict:
            raise ValueError("Unknown resource. Unknown resource_id. Use exact canonical resource_id from catalog.")
        return exact

    if strict:
        raise ValueError("Unknown resource. Unknown resource_id. Use exact canonical resource_id from catalog.")

    return raw
