import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.canonical_resources import canonical_resource_records  # noqa: E402

np.random.seed(42)

WATER_L_PER_PERSON_PER_DAY = 15.0
FOOD_RATIONS_PER_PERSON_PER_DAY = 1.0
BUFFER_DAYS = 3
HOSPITAL_BEDS_PER_1000 = 1.0
ICU_BEDS_PER_1000 = 0.08
DOCTORS_PER_100K = 25.0
NURSES_PER_100K = 80.0
PARAMEDICS_PER_100K = 35.0
AMBULANCES_PER_100K = 10.0
SHELTER_KITS_PER_HH = 0.10
HYGIENE_KITS_PER_HH = 0.12
DIESEL_L_PER_PERSON = 2.0
PETROL_L_PER_PERSON = 1.2

STATE_MOBILIZATION_RATIO = 0.40
NATIONAL_MOBILIZATION_RATIO = 0.30

OUT_SCHEMA = PROJECT_ROOT / "core_engine" / "phase4" / "resources" / "schema"
OUT_DATA = PROJECT_ROOT / "core_engine" / "phase4" / "resources" / "synthetic_data"
OUT_VAL = PROJECT_ROOT / "core_engine" / "phase4" / "resources" / "validation"
for folder in (OUT_SCHEMA, OUT_DATA, OUT_VAL):
    folder.mkdir(parents=True, exist_ok=True)

pop_df = pd.read_csv(PROJECT_ROOT / "core_engine" / "data" / "processed" / "new_data" / "clean_district_population.csv")
pop_df = pop_df[pop_df["population"] > 0].copy()
pop_df["district_code"] = pop_df["district_code"].astype(str)
pop_df["state_code"] = pop_df["state_code"].astype(str)
pop_df["hh_ratio"] = (pop_df["households"] / pop_df["population"]).clip(0.15, 0.45)
pop_df["urban_factor"] = np.clip(0.45 + 0.5 * (pop_df["population"] / pop_df["population"].max()), 0.35, 0.95)

records = canonical_resource_records()
resource_catalog = pd.DataFrame(records)
resource_catalog.to_csv(OUT_SCHEMA / "resource_catalog.csv", index=False)

resource_names = set(resource_catalog["name"].tolist())


def qty_for(name: str, population: float, households: float, hh_ratio: float, urban_factor: float) -> int:
    if name == "food_packets":
        return int(round(FOOD_RATIONS_PER_PERSON_PER_DAY * population * BUFFER_DAYS))
    if name == "rice_kg":
        return int(round(population * 0.35 * BUFFER_DAYS))
    if name == "wheat_kg":
        return int(round(population * 0.30 * BUFFER_DAYS))
    if name == "baby_formula":
        return int(round(population * 0.08 * BUFFER_DAYS))
    if name == "bottled_water_liters":
        return int(round(population * 5.0 * BUFFER_DAYS))
    if name == "bulk_water_liters":
        return int(round(WATER_L_PER_PERSON_PER_DAY * population * BUFFER_DAYS))
    if name == "water_purification_tablets":
        return int(round(population * 2.0 * BUFFER_DAYS))

    if name == "tents":
        return int(round(households * 0.09))
    if name == "tarpaulins":
        return int(round(households * 0.12))
    if name == "blankets":
        return int(round(population * 1.15))
    if name == "sleeping_mats":
        return int(round(population * 0.95))
    if name == "plastic_sheets":
        return int(round(households * 0.20))
    if name == "family_shelter_kits":
        return int(round(households * SHELTER_KITS_PER_HH))

    if name == "medical_kits":
        return int(round(population / 1000.0))
    if name == "trauma_kits":
        return int(round(population / 8000.0))
    if name == "first_aid_kits":
        return int(round(population / 2500.0))
    if name == "antibiotics_courses":
        return int(round(population * 0.03))
    if name == "iv_fluids":
        return int(round(population * 0.04))
    if name == "syringes":
        return int(round(population * 0.25))
    if name == "ppe_kits":
        return int(round(population * 0.02))
    if name == "oxygen_cylinders":
        return int(round(population / 1500.0))

    if name == "doctors":
        return int(round(population * DOCTORS_PER_100K / 100000.0))
    if name == "nurses":
        return int(round(population * NURSES_PER_100K / 100000.0))
    if name == "paramedics":
        return int(round(population * PARAMEDICS_PER_100K / 100000.0))
    if name == "hospital_beds":
        return int(round(population * HOSPITAL_BEDS_PER_1000 / 1000.0))
    if name == "icu_beds":
        return int(round(population * ICU_BEDS_PER_1000 / 1000.0))
    if name == "field_hospital_units":
        return int(round(population / 250000.0))

    if name == "rescue_boats":
        return int(round(population / 500000.0))
    if name == "rescue_ropes":
        return int(round(population / 5000.0))
    if name == "stretchers":
        return int(round(population / 3000.0))
    if name == "hydraulic_cutters":
        return int(round(population / 120000.0))
    if name == "search_cameras":
        return int(round(population / 100000.0))
    if name == "sniffer_dogs":
        return int(round(population / 800000.0))

    if name == "ambulances":
        return int(round(population * AMBULANCES_PER_100K / 100000.0))
    if name == "buses":
        return int(round(population / 250000.0))
    if name == "trucks":
        return int(round(population / 180000.0))
    if name == "helicopters":
        return int(round(population / 2500000.0))
    if name == "boats":
        return int(round(population / 750000.0))

    if name == "diesel_liters":
        return int(round(population * DIESEL_L_PER_PERSON))
    if name == "petrol_liters":
        return int(round(population * PETROL_L_PER_PERSON))
    if name == "generators":
        return int(round(households * 0.01))
    if name == "solar_lanterns":
        return int(round(households * 0.30))
    if name == "battery_packs":
        return int(round(population * 0.75))

    if name == "satellite_phones":
        return int(round(population / 120000.0))
    if name == "handheld_radios":
        return int(round(population / 5000.0))
    if name == "mobile_base_stations":
        return int(round(population / 350000.0))
    if name == "loudspeakers":
        return int(round(population / 3000.0))

    if name == "toilets_portable":
        return int(round(population / 50.0))
    if name == "hygiene_kits":
        return int(round(households * HYGIENE_KITS_PER_HH))
    if name == "soap_bars":
        return int(round(population * 1.8))
    if name == "sanitary_pads":
        return int(round(population * 0.55))
    if name == "diapers":
        return int(round(population * 0.20))

    if name == "forklifts":
        return int(round(population / 180000.0))
    if name == "pallets":
        return int(round(population / 40.0))
    if name == "storage_containers":
        return int(round(population / 4500.0))
    if name == "cold_chain_boxes":
        return int(round(population / 2200.0))

    return 0


rows: list[tuple[str, str, int]] = []
for district in pop_df.itertuples(index=False):
    district_code = str(district.district_code)
    population = float(district.population)
    households = float(district.households)
    hh_ratio = float(district.hh_ratio)
    urban_factor = float(district.urban_factor)

    for resource in records:
        quantity = max(0, qty_for(resource["name"], population, households, hh_ratio, urban_factor))
        rows.append((district_code, resource["canonical_id"], int(quantity)))

district_stock = pd.DataFrame(rows, columns=["district_code", "resource_id", "quantity"])
expected_rows = int(len(pop_df) * len(records))
if len(district_stock) != expected_rows:
    raise RuntimeError(f"district_resource_stock row count mismatch: expected {expected_rows}, got {len(district_stock)}")

district_stock.to_csv(OUT_DATA / "district_resource_stock.csv", index=False)

state_stock = (
    district_stock.merge(pop_df[["district_code", "state_code"]], on="district_code", how="left")
    .groupby(["state_code", "resource_id"], as_index=False)["quantity"]
    .sum()
)
state_stock["quantity"] = (state_stock["quantity"] * STATE_MOBILIZATION_RATIO).round().astype(int)
state_stock.to_csv(OUT_DATA / "state_resource_stock.csv", index=False)

national_stock = state_stock.groupby("resource_id", as_index=False)["quantity"].sum()
national_stock["quantity"] = (national_stock["quantity"] * NATIONAL_MOBILIZATION_RATIO).round().astype(int)
national_stock.to_csv(OUT_DATA / "national_resource_stock.csv", index=False)

pd.DataFrame(
    [
        ("district", "district", 0),
        ("state", "district", 12),
        ("national", "district", 36),
    ],
    columns=["from_level", "to_level", "latency_hours"],
).to_csv(OUT_SCHEMA / "resource_dispatch_latency.csv", index=False)

now = datetime.now(UTC).isoformat()
with open(OUT_VAL / "resource_validation_report.txt", "w", encoding="utf-8") as output:
    output.write(f"Resource DB generated at {now}\n")
    output.write(f"Canonical resource count: {len(records)}\n")
    output.write(f"District rows: {len(district_stock)} (expected {expected_rows})\n")
    output.write("State mobilization ratio: 0.40\n")
    output.write("National mobilization ratio: 0.30\n")

print("Canonical multi-resource database generated successfully.")
