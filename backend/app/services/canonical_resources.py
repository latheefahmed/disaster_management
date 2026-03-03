from dataclasses import dataclass


@dataclass(frozen=True)
class CanonicalResource:
    canonical_id: str
    name: str
    unit: str
    category: str
    class_type: str
    count_type: str
    max_reasonable_quantity: float


def _normalize_class_name(class_type: str) -> str:
    return "consumable" if str(class_type) == "consumable" else "non_consumable"


CANONICAL_RESOURCES: list[CanonicalResource] = [
    CanonicalResource("R1", "food_packets", "person_day_rations", "FOOD_WATER", "consumable", "integer", 5_000_000),
    CanonicalResource("R2", "rice_kg", "kg", "FOOD_WATER", "consumable", "continuous", 10_000_000),
    CanonicalResource("R3", "wheat_kg", "kg", "FOOD_WATER", "consumable", "continuous", 10_000_000),
    CanonicalResource("R4", "baby_formula", "packets", "FOOD_WATER", "consumable", "integer", 2_000_000),
    CanonicalResource("R5", "bottled_water_liters", "liters", "FOOD_WATER", "consumable", "continuous", 20_000_000),
    CanonicalResource("R6", "bulk_water_liters", "liters", "FOOD_WATER", "consumable", "continuous", 50_000_000),
    CanonicalResource("R7", "water_purification_tablets", "tablets", "FOOD_WATER", "consumable", "integer", 30_000_000),
    CanonicalResource("R8", "tents", "units", "SHELTER_NFI", "stockable", "integer", 1_500_000),
    CanonicalResource("R9", "tarpaulins", "units", "SHELTER_NFI", "stockable", "integer", 2_000_000),
    CanonicalResource("R10", "blankets", "units", "SHELTER_NFI", "stockable", "integer", 5_000_000),
    CanonicalResource("R11", "sleeping_mats", "units", "SHELTER_NFI", "stockable", "integer", 5_000_000),
    CanonicalResource("R12", "plastic_sheets", "units", "SHELTER_NFI", "stockable", "integer", 3_000_000),
    CanonicalResource("R13", "family_shelter_kits", "kits", "SHELTER_NFI", "stockable", "integer", 1_200_000),
    CanonicalResource("R14", "medical_kits", "kits", "MEDICAL_CONSUMABLE", "consumable", "integer", 2_000_000),
    CanonicalResource("R15", "trauma_kits", "kits", "MEDICAL_CONSUMABLE", "consumable", "integer", 800_000),
    CanonicalResource("R16", "first_aid_kits", "kits", "MEDICAL_CONSUMABLE", "consumable", "integer", 3_000_000),
    CanonicalResource("R17", "antibiotics_courses", "courses", "MEDICAL_CONSUMABLE", "consumable", "integer", 3_500_000),
    CanonicalResource("R18", "iv_fluids", "liters", "MEDICAL_CONSUMABLE", "consumable", "continuous", 10_000_000),
    CanonicalResource("R19", "syringes", "units", "MEDICAL_CONSUMABLE", "consumable", "integer", 50_000_000),
    CanonicalResource("R20", "ppe_kits", "kits", "MEDICAL_CONSUMABLE", "consumable", "integer", 5_000_000),
    CanonicalResource("R21", "oxygen_cylinders", "cylinders", "MEDICAL_CONSUMABLE", "consumable", "integer", 2_000_000),
    CanonicalResource("R22", "doctors", "people", "PERSONNEL", "personnel", "integer", 500_000),
    CanonicalResource("R23", "nurses", "people", "PERSONNEL", "personnel", "integer", 2_000_000),
    CanonicalResource("R24", "paramedics", "people", "PERSONNEL", "personnel", "integer", 1_000_000),
    CanonicalResource("R25", "hospital_beds", "beds", "MEDICAL_CAPACITY", "capacity", "integer", 3_500_000),
    CanonicalResource("R26", "icu_beds", "beds", "MEDICAL_CAPACITY", "capacity", "integer", 500_000),
    CanonicalResource("R27", "field_hospital_units", "units", "MEDICAL_CAPACITY", "capacity", "integer", 50_000),
    CanonicalResource("R28", "rescue_boats", "units", "SEARCH_RESCUE", "stockable", "integer", 200_000),
    CanonicalResource("R29", "rescue_ropes", "units", "SEARCH_RESCUE", "stockable", "integer", 3_000_000),
    CanonicalResource("R30", "stretchers", "units", "SEARCH_RESCUE", "stockable", "integer", 1_500_000),
    CanonicalResource("R31", "hydraulic_cutters", "units", "SEARCH_RESCUE", "stockable", "integer", 120_000),
    CanonicalResource("R32", "search_cameras", "units", "SEARCH_RESCUE", "stockable", "integer", 120_000),
    CanonicalResource("R33", "sniffer_dogs", "animals", "SEARCH_RESCUE", "capacity", "integer", 40_000),
    CanonicalResource("R34", "ambulances", "vehicles", "TRANSPORT", "stockable", "integer", 150_000),
    CanonicalResource("R35", "buses", "vehicles", "TRANSPORT", "stockable", "integer", 200_000),
    CanonicalResource("R36", "trucks", "vehicles", "TRANSPORT", "stockable", "integer", 300_000),
    CanonicalResource("R37", "helicopters", "vehicles", "TRANSPORT", "stockable", "integer", 15_000),
    CanonicalResource("R38", "boats", "vehicles", "TRANSPORT", "stockable", "integer", 250_000),
    CanonicalResource("R39", "diesel_liters", "liters", "POWER_FUEL", "consumable", "continuous", 80_000_000),
    CanonicalResource("R40", "petrol_liters", "liters", "POWER_FUEL", "consumable", "continuous", 60_000_000),
    CanonicalResource("R41", "generators", "units", "POWER_FUEL", "stockable", "integer", 400_000),
    CanonicalResource("R42", "solar_lanterns", "units", "POWER_FUEL", "stockable", "integer", 5_000_000),
    CanonicalResource("R43", "battery_packs", "units", "POWER_FUEL", "consumable", "integer", 12_000_000),
    CanonicalResource("R44", "satellite_phones", "units", "COMMUNICATION", "stockable", "integer", 200_000),
    CanonicalResource("R45", "handheld_radios", "units", "COMMUNICATION", "stockable", "integer", 2_500_000),
    CanonicalResource("R46", "mobile_base_stations", "units", "COMMUNICATION", "stockable", "integer", 60_000),
    CanonicalResource("R47", "loudspeakers", "units", "COMMUNICATION", "stockable", "integer", 1_000_000),
    CanonicalResource("R48", "toilets_portable", "units", "SANITATION_HYGIENE", "stockable", "integer", 800_000),
    CanonicalResource("R49", "hygiene_kits", "kits", "SANITATION_HYGIENE", "consumable", "integer", 5_000_000),
    CanonicalResource("R50", "soap_bars", "units", "SANITATION_HYGIENE", "consumable", "integer", 50_000_000),
    CanonicalResource("R51", "sanitary_pads", "packs", "SANITATION_HYGIENE", "consumable", "integer", 15_000_000),
    CanonicalResource("R52", "diapers", "packs", "SANITATION_HYGIENE", "consumable", "integer", 15_000_000),
    CanonicalResource("R53", "forklifts", "units", "LOGISTICS", "stockable", "integer", 120_000),
    CanonicalResource("R54", "pallets", "units", "LOGISTICS", "stockable", "integer", 8_000_000),
    CanonicalResource("R55", "storage_containers", "units", "LOGISTICS", "stockable", "integer", 300_000),
    CanonicalResource("R56", "cold_chain_boxes", "units", "INFRASTRUCTURE", "stockable", "integer", 1_000_000),
]

CANONICAL_RESOURCE_ORDER = [r.canonical_id for r in CANONICAL_RESOURCES]
CANONICAL_RESOURCE_SET = set(CANONICAL_RESOURCE_ORDER)

CANONICAL_RESOURCE_NAME = {r.canonical_id: r.name for r in CANONICAL_RESOURCES}
CANONICAL_RESOURCE_UNIT = {r.canonical_id: r.unit for r in CANONICAL_RESOURCES}
CANONICAL_RESOURCE_CATEGORY = {r.canonical_id: r.category for r in CANONICAL_RESOURCES}
CANONICAL_RESOURCE_CLASS = {r.canonical_id: _normalize_class_name(r.class_type) for r in CANONICAL_RESOURCES}
CANONICAL_RESOURCE_COUNT_TYPE = {r.canonical_id: r.count_type for r in CANONICAL_RESOURCES}
CANONICAL_RESOURCE_CAN_CONSUME = {r.canonical_id: (_normalize_class_name(r.class_type) == "consumable") for r in CANONICAL_RESOURCES}
CANONICAL_RESOURCE_CAN_RETURN = {r.canonical_id: (_normalize_class_name(r.class_type) == "non_consumable") for r in CANONICAL_RESOURCES}

MAX_PER_RESOURCE = {r.canonical_id: float(r.max_reasonable_quantity) for r in CANONICAL_RESOURCES}

CONSUMABLE_CANONICAL = {
    r.canonical_id for r in CANONICAL_RESOURCES if _normalize_class_name(r.class_type) == "consumable"
}
COUNTABLE_RESOURCE_IDS = {
    r.canonical_id for r in CANONICAL_RESOURCES if r.count_type == "integer"
}

RESOURCE_ALIAS_TO_CANONICAL = {
    "food": "R1",
    "food_packets": "R1",
    "water": "R5",
    "water_liters": "R5",
    "bulk_water": "R6",
    "medical_kits": "R14",
    "essential_medicines": "R17",
    "rescue_teams": "R28",
    "medical_teams": "R24",
    "volunteers": "R24",
    "buses": "R35",
    "trucks": "R36",
    "boats": "R38",
    "helicopters": "R37",
    "r99": "",
    "t99": "",
}


def canonical_resource_records() -> list[dict]:
    return [
        {
            "canonical_id": r.canonical_id,
            "name": r.name,
            "unit": r.unit,
            "category": r.category,
            "class": _normalize_class_name(r.class_type),
            "can_consume": _normalize_class_name(r.class_type) == "consumable",
            "can_return": _normalize_class_name(r.class_type) == "non_consumable",
            "count_type": r.count_type,
            "max_reasonable_quantity": float(r.max_reasonable_quantity),
        }
        for r in CANONICAL_RESOURCES
    ]


def canonicalize_resource_id(resource_id: str | None) -> str:
    rid = str(resource_id or "").strip()
    if not rid:
        return ""
    if rid.isdigit():
        as_num = int(rid)
        if 1 <= as_num <= 999:
            candidate = f"R{as_num}"
            if candidate in CANONICAL_RESOURCE_SET:
                return candidate
    upper = rid.upper()
    if upper in CANONICAL_RESOURCE_SET:
        return upper

    alias = RESOURCE_ALIAS_TO_CANONICAL.get(rid.lower())
    if alias is not None:
        return alias
    return rid


def is_canonical_resource_id(resource_id: str | None) -> bool:
    return canonicalize_resource_id(resource_id) in CANONICAL_RESOURCE_SET


def max_quantity_for(resource_id: str | None) -> float:
    rid = canonicalize_resource_id(resource_id)
    return float(MAX_PER_RESOURCE.get(rid, 100_000.0))


def requires_integer_quantity(resource_id: str | None) -> bool:
    rid = canonicalize_resource_id(resource_id)
    return rid in COUNTABLE_RESOURCE_IDS


def is_returnable_resource(resource_id: str | None) -> bool:
    rid = canonicalize_resource_id(resource_id)
    if rid not in CANONICAL_RESOURCE_SET:
        return False
    return bool(CANONICAL_RESOURCE_CAN_RETURN.get(rid, False))


def can_consume_resource(resource_id: str | None) -> bool:
    rid = canonicalize_resource_id(resource_id)
    return bool(CANONICAL_RESOURCE_CAN_CONSUME.get(rid, False))


def can_return_resource(resource_id: str | None) -> bool:
    rid = canonicalize_resource_id(resource_id)
    return bool(CANONICAL_RESOURCE_CAN_RETURN.get(rid, False))
