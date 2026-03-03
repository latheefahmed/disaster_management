from app.services.canonical_resources import (
    CANONICAL_RESOURCE_UNIT,
    CANONICAL_RESOURCE_SET,
    CONSUMABLE_CANONICAL,
    canonicalize_resource_id,
    max_quantity_for,
    requires_integer_quantity,
)


def _rid(resource_id: str | None) -> str:
    return canonicalize_resource_id(resource_id)


def is_resource_consumable(resource_id: str | None) -> bool:
    rid = _rid(resource_id)
    if not rid:
        return False
    if rid not in CANONICAL_RESOURCE_SET:
        return False
    return rid in CONSUMABLE_CANONICAL


def is_resource_returnable(resource_id: str | None) -> bool:
    rid = _rid(resource_id)
    if not rid:
        return False
    if rid not in CANONICAL_RESOURCE_SET:
        return True
    return not is_resource_consumable(rid)


def must_return_if_claimed(resource_id: str | None) -> bool:
    rid = _rid(resource_id)
    if not rid:
        return False
    return is_resource_returnable(rid) and not is_resource_consumable(rid)


def get_resource_policy(resource_id: str | None) -> dict:
    rid = _rid(resource_id)
    can_consume = is_resource_consumable(rid)
    can_return = is_resource_returnable(rid)
    return {
        "resource_id": rid,
        "is_consumable": can_consume,
        "is_returnable": can_return,
        "can_consume": can_consume,
        "can_return": can_return,
        "must_return_if_claimed": must_return_if_claimed(rid),
        "max_per_resource": max_quantity_for(rid),
        "requires_integer_quantity": requires_integer_quantity(rid),
    }


def get_resource_unit(resource_id: str | None) -> str:
    rid = _rid(resource_id)
    if not rid:
        return "units"
    if rid in CANONICAL_RESOURCE_UNIT:
        return CANONICAL_RESOURCE_UNIT[rid]
    return "units"
