import json
import sqlite3
import sys
from pathlib import Path
from collections import defaultdict


BACKEND_DIR = Path(__file__).resolve().parents[1]
DB_PATH = str(BACKEND_DIR / "backend.db")
DISTRICT_CODE = "603"
TIME_SLOT = 0


def get_returnable_non_consumable_resources(cur) -> set[str]:
	# Prefer policy module when available to avoid schema assumptions.
	try:
		sys.path.insert(0, str(BACKEND_DIR))
		from app.services.canonical_resources import CANONICAL_RESOURCE_ORDER
		from app.services.resource_policy import is_resource_returnable, is_resource_consumable

		out = set()
		for rid in CANONICAL_RESOURCE_ORDER:
			if is_resource_returnable(rid) and (not is_resource_consumable(rid)):
				out.add(str(rid))
		if out:
			return out
	except Exception:
		pass

	out = set()
	candidates = [
		"SELECT resource_id, is_returnable, is_consumable FROM resources",
		"SELECT resource_id, returnable AS is_returnable, consumable AS is_consumable FROM resources",
	]
	for q in candidates:
		try:
			cur.execute(q)
			for r in cur.fetchall():
				rid = str(r["resource_id"])
				ret = bool(r["is_returnable"]) if r["is_returnable"] is not None else False
				cons = bool(r["is_consumable"]) if r["is_consumable"] is not None else False
				if ret and (not cons):
					out.add(rid)
			if out:
				return out
		except Exception:
			continue
	return out


def main() -> None:
	conn = sqlite3.connect(DB_PATH)
	conn.row_factory = sqlite3.Row
	cur = conn.cursor()

	ret_noncons = get_returnable_non_consumable_resources(cur)

	cur.execute(
		"""
		SELECT
			rr.id AS request_id,
			rr.resource_id,
			rr.quantity,
			rr.time,
			rr.status,
			rr.created_at,
			a.allocation_source_scope AS scope,
			a.allocated_quantity AS allocated_quantity,
			a.is_unmet AS is_unmet,
			a.origin_state_code AS origin_state_code
		FROM requests rr
		LEFT JOIN allocations a ON a.request_id = rr.id
		WHERE rr.district_code = ? AND rr.time = ?
		ORDER BY rr.id DESC
		LIMIT 4000
		""",
		(DISTRICT_CODE, TIME_SLOT),
	)
	rows = cur.fetchall()

	agg = {}
	for r in rows:
		req_id = int(r["request_id"])
		if req_id not in agg:
			agg[req_id] = {
				"request_id": req_id,
				"resource_id": str(r["resource_id"]),
				"quantity": float(r["quantity"] or 0.0),
				"status": str(r["status"] or ""),
				"created_at": str(r["created_at"] or ""),
				"scopes": defaultdict(float),
				"neighbor_states": set(),
				"unmet": 0.0,
			}

		unmet = r["is_unmet"]
		scope = r["scope"]
		qty = float(r["allocated_quantity"] or 0.0)

		if unmet in (1, True):
			agg[req_id]["unmet"] += qty
			continue

		if scope is None or qty <= 0:
			continue

		scope_key = str(scope).strip().lower()
		agg[req_id]["scopes"][scope_key] += qty

		if scope_key == "neighbor_state":
			st = str(r["origin_state_code"] or "").strip()
			if st:
				agg[req_id]["neighbor_states"].add(st)

	normalized = []
	for v in agg.values():
		scopes = {k: float(x) for k, x in v["scopes"].items() if float(x) > 1e-6}
		if not scopes:
			continue
		normalized.append(
			{
				"request_id": v["request_id"],
				"resource_id": v["resource_id"],
				"quantity": v["quantity"],
				"status": v["status"],
				"created_at": v["created_at"],
				"scopes": scopes,
				"neighbor_states": sorted(v["neighbor_states"]),
				"neighbor_state_count": len(v["neighbor_states"]),
				"unmet": float(v["unmet"]),
				"is_returnable_non_consumable": (
					(v["resource_id"] in ret_noncons) if ret_noncons else None
				),
			}
		)

	patterns = [
		(
			"district_only",
			lambda x: set(x["scopes"].keys()) == {"district"},
		),
		(
			"district_state",
			lambda x: set(x["scopes"].keys()) == {"district", "state"},
		),
		(
			"district_state_interstate",
			lambda x: set(x["scopes"].keys()) == {"district", "state", "neighbor_state"},
		),
		(
			"district_state_interstate_national",
			lambda x: set(x["scopes"].keys())
			== {"district", "state", "neighbor_state", "national"},
		),
	]

	pick = {}
	ordered = sorted(normalized, key=lambda x: int(x["request_id"]), reverse=True)

	for name, matcher in patterns:
		for row in ordered:
			if not matcher(row):
				continue
			if row["is_returnable_non_consumable"] is False:
				continue
			pick[name] = row
			break

	# Ensure we return exactly 3 minimum: prefer first three policy steps.
	preferred = ["district_only", "district_state", "district_state_interstate"]
	final = {k: pick[k] for k in preferred if k in pick}

	if len(final) < 3:
		for k in ["district_state_interstate_national"]:
			if k in pick and k not in final:
				final[k] = pick[k]
			if len(final) >= 3:
				break

	result = {
		"district_code": DISTRICT_CODE,
		"time_slot": TIME_SLOT,
		"total_requests_scanned": len(normalized),
		"returnable_non_consumable_resources_detected": len(ret_noncons),
		"selected": final,
		"selected_count": len(final),
	}

	print(json.dumps(result, indent=2))
	conn.close()


if __name__ == "__main__":
	main()
