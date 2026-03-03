from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import DATABASE_URL


engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 60},
    pool_size=20,
    max_overflow=40,
    pool_pre_ping=True,
    pool_recycle=1800,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()


def _sqlite_column_exists(conn, table_name: str, column_name: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    return any(str(r[1]) == column_name for r in rows)


def _sqlite_table_exists(conn, table_name: str) -> bool:
    row = conn.execute(
        text(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name = :name"
        ),
        {"name": table_name}
    ).fetchone()
    return row is not None


def _print_query_plan(conn, sql: str, params: dict | None = None):
    try:
        rows = conn.execute(text(f"EXPLAIN QUERY PLAN {sql}"), params or {}).fetchall()
        print("QUERY_PLAN", {"sql": sql, "plan": [tuple(r) for r in rows]})
    except Exception as exc:
        print("QUERY_PLAN_FAILED", {"sql": sql, "error": str(exc)})


def apply_runtime_migrations():
    if engine.dialect.name != "sqlite":
        with engine.begin() as conn:
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_allocations_solver_created_id ON allocations(solver_run_id, created_at, id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_allocations_request_created ON allocations(request_id, created_at)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_requests_run_created ON requests(run_id, created_at)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_allocations_district_code ON allocations(district_code)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_allocations_state_code ON allocations(state_code)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_allocations_time ON allocations(time)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_allocations_resource_id ON allocations(resource_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_allocations_supply_level ON allocations(supply_level)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_allocations_run_id ON allocations(solver_run_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_allocations_district_run ON allocations(district_code, solver_run_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_allocations_state_run ON allocations(state_code, solver_run_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_allocations_run_time ON allocations(solver_run_id, time)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_allocations_run_district ON allocations(solver_run_id, district_code)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_allocations_run_state ON allocations(solver_run_id, state_code)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_allocations_created_at_desc ON allocations(created_at DESC)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_requests_district_status ON requests(district_code, status)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_requests_created_at_desc ON requests(created_at DESC)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_solver_runs_id_desc ON solver_runs(id DESC)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_solver_runs_status ON solver_runs(status)"))
            conn.execute(text("DROP VIEW IF EXISTS latest_allocations_view"))
            conn.execute(text(
                "CREATE VIEW latest_allocations_view AS "
                "SELECT * FROM allocations "
                "WHERE solver_run_id = (SELECT MAX(id) FROM solver_runs WHERE status='completed' AND mode='live')"
            ))
        return

    from app.services.canonical_resources import (
        CANONICAL_RESOURCE_ORDER,
        CANONICAL_RESOURCE_NAME,
        CANONICAL_RESOURCE_UNIT,
        CANONICAL_RESOURCE_CATEGORY,
        CANONICAL_RESOURCE_CLASS,
        CANONICAL_RESOURCE_CAN_CONSUME,
        CANONICAL_RESOURCE_CAN_RETURN,
        CANONICAL_RESOURCE_COUNT_TYPE,
        MAX_PER_RESOURCE,
        RESOURCE_ALIAS_TO_CANONICAL,
    )

    canonical_records = [
        {
            "canonical_id": rid,
            "name": CANONICAL_RESOURCE_NAME[rid],
            "unit": CANONICAL_RESOURCE_UNIT[rid],
            "category": CANONICAL_RESOURCE_CATEGORY[rid],
            "class_type": CANONICAL_RESOURCE_CLASS[rid],
            "can_consume": bool(CANONICAL_RESOURCE_CAN_CONSUME[rid]),
            "can_return": bool(CANONICAL_RESOURCE_CAN_RETURN[rid]),
            "count_type": CANONICAL_RESOURCE_COUNT_TYPE[rid],
            "max_reasonable_quantity": float(MAX_PER_RESOURCE[rid]),
        }
        for rid in CANONICAL_RESOURCE_ORDER
    ]

    with engine.begin() as conn:
        try:
            conn.execute(text("PRAGMA journal_mode=WAL"))
            conn.execute(text("PRAGMA synchronous=NORMAL"))
            conn.execute(text("PRAGMA temp_store=MEMORY"))
            conn.execute(text("PRAGMA busy_timeout=60000"))
        except Exception:
            pass

        def _remap_resource_ids(table_name: str):
            if _sqlite_table_exists(conn, table_name) and _sqlite_column_exists(conn, table_name, "resource_id"):
                alias_keys = [str(alias).lower() for alias in RESOURCE_ALIAS_TO_CANONICAL.keys()]
                canonical_sql = ",".join([f"'{rid}'" for rid in CANONICAL_RESOURCE_ORDER])
                alias_sql = ",".join([f"'{a}'" for a in alias_keys]) if alias_keys else "''"
                needs_work = conn.execute(
                    text(
                        f"SELECT COUNT(1) FROM {table_name} "
                        f"WHERE LOWER(TRIM(resource_id)) IN ({alias_sql}) "
                        f"OR resource_id NOT IN ({canonical_sql})"
                    )
                ).scalar() or 0
                if int(needs_work) <= 0:
                    return

                for alias, canonical in RESOURCE_ALIAS_TO_CANONICAL.items():
                    if not canonical:
                        conn.execute(text(f"DELETE FROM {table_name} WHERE LOWER(TRIM(resource_id)) = :alias"), {"alias": str(alias).lower()})
                    else:
                        conn.execute(
                            text(f"UPDATE {table_name} SET resource_id = :canonical WHERE LOWER(TRIM(resource_id)) = :alias"),
                            {"canonical": canonical, "alias": str(alias).lower()},
                        )
                conn.execute(
                    text(
                        f"DELETE FROM {table_name} "
                        f"WHERE resource_id NOT IN ({','.join([f'''\'{rid}\'''' for rid in CANONICAL_RESOURCE_ORDER])})"
                    )
                )

        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS canonical_resources ("
                "canonical_id TEXT PRIMARY KEY,"
                "name TEXT NOT NULL UNIQUE,"
                "unit TEXT NOT NULL,"
                "category TEXT NOT NULL,"
                "class_type TEXT NOT NULL,"
                "can_consume INTEGER NOT NULL DEFAULT 0,"
                "can_return INTEGER NOT NULL DEFAULT 1,"
                "count_type TEXT NOT NULL,"
                "max_reasonable_quantity REAL NOT NULL"
                ")"
            )
        )

        if _sqlite_table_exists(conn, "canonical_resources"):
            if not _sqlite_column_exists(conn, "canonical_resources", "can_consume"):
                conn.execute(text("ALTER TABLE canonical_resources ADD COLUMN can_consume INTEGER NOT NULL DEFAULT 0"))
            if not _sqlite_column_exists(conn, "canonical_resources", "can_return"):
                conn.execute(text("ALTER TABLE canonical_resources ADD COLUMN can_return INTEGER NOT NULL DEFAULT 1"))

        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS stock_refill_transactions ("
                "id INTEGER PRIMARY KEY,"
                "scope TEXT NOT NULL,"
                "district_code TEXT NULL,"
                "state_code TEXT NULL,"
                "resource_id TEXT NOT NULL,"
                "quantity_delta REAL NOT NULL,"
                "reason TEXT NOT NULL,"
                "actor_role TEXT NOT NULL,"
                "actor_id TEXT NOT NULL,"
                "source TEXT NOT NULL DEFAULT 'manual_refill',"
                "solver_run_id INTEGER NULL,"
                "created_at DATETIME"
                ")"
            )
        )

        existing_rows = conn.execute(
            text("SELECT canonical_id, name, unit, category, class_type, can_consume, can_return, count_type, max_reasonable_quantity FROM canonical_resources")
        ).fetchall()
        expected_by_id = {str(r["canonical_id"]): r for r in canonical_records}
        needs_reseed = False
        if len(existing_rows) != len(canonical_records):
            needs_reseed = True
        else:
            for row in existing_rows:
                cid = str(row[0])
                expected = expected_by_id.get(cid)
                if expected is None:
                    needs_reseed = True
                    break
                if (
                    str(row[1]) != str(expected["name"]) or
                    str(row[2]) != str(expected["unit"]) or
                    str(row[3]) != str(expected["category"]) or
                    str(row[4]) != str(expected["class_type"]) or
                    int(row[5] or 0) != int(1 if expected["can_consume"] else 0) or
                    int(row[6] or 0) != int(1 if expected["can_return"] else 0) or
                    str(row[7]) != str(expected["count_type"]) or
                    float(row[8] or 0.0) != float(expected["max_reasonable_quantity"]) 
                ):
                    needs_reseed = True
                    break

        if needs_reseed:
            conn.execute(text("DELETE FROM canonical_resources"))
            for record in canonical_records:
                conn.execute(
                    text(
                        "INSERT INTO canonical_resources(canonical_id, name, unit, category, class_type, can_consume, can_return, count_type, max_reasonable_quantity) "
                        "VALUES (:canonical_id, :name, :unit, :category, :class_type, :can_consume, :can_return, :count_type, :max_reasonable_quantity)"
                    ),
                    record,
                )

        if _sqlite_table_exists(conn, "districts") and not _sqlite_column_exists(conn, "districts", "demand_mode"):
            conn.execute(
                text(
                    "ALTER TABLE districts "
                    "ADD COLUMN demand_mode TEXT NOT NULL DEFAULT 'baseline_plus_human'"
                )
            )

        if _sqlite_table_exists(conn, "requests"):
            if not _sqlite_column_exists(conn, "requests", "priority"):
                conn.execute(text("ALTER TABLE requests ADD COLUMN priority INTEGER DEFAULT 1"))
            if not _sqlite_column_exists(conn, "requests", "urgency"):
                conn.execute(text("ALTER TABLE requests ADD COLUMN urgency INTEGER DEFAULT 1"))
            if not _sqlite_column_exists(conn, "requests", "confidence"):
                conn.execute(text("ALTER TABLE requests ADD COLUMN confidence REAL DEFAULT 1.0"))
            if not _sqlite_column_exists(conn, "requests", "source"):
                conn.execute(text("ALTER TABLE requests ADD COLUMN source TEXT DEFAULT 'human'"))
            if not _sqlite_column_exists(conn, "requests", "included_in_run"):
                conn.execute(text("ALTER TABLE requests ADD COLUMN included_in_run INTEGER DEFAULT 0"))
            if not _sqlite_column_exists(conn, "requests", "queued"):
                conn.execute(text("ALTER TABLE requests ADD COLUMN queued INTEGER DEFAULT 1"))
            if not _sqlite_column_exists(conn, "requests", "lifecycle_state"):
                conn.execute(text("ALTER TABLE requests ADD COLUMN lifecycle_state TEXT NOT NULL DEFAULT 'CREATED'"))
            if not _sqlite_column_exists(conn, "requests", "run_id"):
                conn.execute(text("ALTER TABLE requests ADD COLUMN run_id INTEGER NOT NULL DEFAULT 0"))
            if not _sqlite_column_exists(conn, "requests", "allocated_quantity"):
                conn.execute(text("ALTER TABLE requests ADD COLUMN allocated_quantity REAL NOT NULL DEFAULT 0.0"))
            if not _sqlite_column_exists(conn, "requests", "unmet_quantity"):
                conn.execute(text("ALTER TABLE requests ADD COLUMN unmet_quantity REAL NOT NULL DEFAULT 0.0"))
            if not _sqlite_column_exists(conn, "requests", "final_demand_quantity"):
                conn.execute(text("ALTER TABLE requests ADD COLUMN final_demand_quantity REAL NOT NULL DEFAULT 0.0"))

            conn.execute(text("UPDATE requests SET lifecycle_state = 'CREATED' WHERE status = 'pending'"))
            conn.execute(text("UPDATE requests SET lifecycle_state = 'SENT_TO_SOLVER' WHERE status = 'solving'"))
            conn.execute(text("UPDATE requests SET lifecycle_state = 'ALLOCATED' WHERE status = 'allocated'"))
            conn.execute(text("UPDATE requests SET lifecycle_state = 'PARTIAL' WHERE status = 'partial'"))
            conn.execute(text("UPDATE requests SET lifecycle_state = 'UNMET' WHERE status = 'unmet'"))
            conn.execute(text("UPDATE requests SET lifecycle_state = 'ESCALATED' WHERE status IN ('escalated_state','escalated_national')"))
            conn.execute(text("UPDATE requests SET lifecycle_state = 'FAILED' WHERE status = 'failed'"))

            conn.execute(text("DROP INDEX IF EXISTS uq_requests_slot_run"))

        if _sqlite_table_exists(conn, "allocations"):
            if not _sqlite_column_exists(conn, "allocations", "supply_level"):
                conn.execute(text("ALTER TABLE allocations ADD COLUMN supply_level TEXT NOT NULL DEFAULT 'district'"))
            if not _sqlite_column_exists(conn, "allocations", "source_request_id"):
                conn.execute(text("ALTER TABLE allocations ADD COLUMN source_request_id INTEGER"))
            if not _sqlite_column_exists(conn, "allocations", "source_request_created_at"):
                conn.execute(text("ALTER TABLE allocations ADD COLUMN source_request_created_at DATETIME"))
            if not _sqlite_column_exists(conn, "allocations", "source_batch_id"):
                conn.execute(text("ALTER TABLE allocations ADD COLUMN source_batch_id INTEGER"))
            if not _sqlite_column_exists(conn, "allocations", "allocation_source_scope"):
                conn.execute(text("ALTER TABLE allocations ADD COLUMN allocation_source_scope TEXT"))
            if not _sqlite_column_exists(conn, "allocations", "allocation_source_code"):
                conn.execute(text("ALTER TABLE allocations ADD COLUMN allocation_source_code TEXT"))
            if not _sqlite_column_exists(conn, "allocations", "claimed_quantity"):
                conn.execute(text("ALTER TABLE allocations ADD COLUMN claimed_quantity REAL NOT NULL DEFAULT 0.0"))
            if not _sqlite_column_exists(conn, "allocations", "consumed_quantity"):
                conn.execute(text("ALTER TABLE allocations ADD COLUMN consumed_quantity REAL NOT NULL DEFAULT 0.0"))
            if not _sqlite_column_exists(conn, "allocations", "returned_quantity"):
                conn.execute(text("ALTER TABLE allocations ADD COLUMN returned_quantity REAL NOT NULL DEFAULT 0.0"))
            if not _sqlite_column_exists(conn, "allocations", "status"):
                conn.execute(text("ALTER TABLE allocations ADD COLUMN status TEXT NOT NULL DEFAULT 'allocated'"))
            if not _sqlite_column_exists(conn, "allocations", "origin_state"):
                conn.execute(text("ALTER TABLE allocations ADD COLUMN origin_state TEXT"))
            if not _sqlite_column_exists(conn, "allocations", "origin_state_code"):
                conn.execute(text("ALTER TABLE allocations ADD COLUMN origin_state_code TEXT"))
            if not _sqlite_column_exists(conn, "allocations", "origin_district_code"):
                conn.execute(text("ALTER TABLE allocations ADD COLUMN origin_district_code TEXT"))
            if not _sqlite_column_exists(conn, "allocations", "implied_delay_hours"):
                conn.execute(text("ALTER TABLE allocations ADD COLUMN implied_delay_hours REAL"))
            if not _sqlite_column_exists(conn, "allocations", "receipt_confirmed"):
                conn.execute(text("ALTER TABLE allocations ADD COLUMN receipt_confirmed INTEGER NOT NULL DEFAULT 0"))
            if not _sqlite_column_exists(conn, "allocations", "receipt_time"):
                conn.execute(text("ALTER TABLE allocations ADD COLUMN receipt_time DATETIME"))
            if not _sqlite_column_exists(conn, "allocations", "created_at"):
                conn.execute(text("ALTER TABLE allocations ADD COLUMN created_at DATETIME"))
            if not _sqlite_column_exists(conn, "allocations", "overflow_reconciled_at"):
                conn.execute(text("ALTER TABLE allocations ADD COLUMN overflow_reconciled_at DATETIME"))
            if not _sqlite_column_exists(conn, "allocations", "overflow_reconcile_mode"):
                conn.execute(text("ALTER TABLE allocations ADD COLUMN overflow_reconcile_mode TEXT"))
            if not _sqlite_column_exists(conn, "allocations", "overflow_reconcile_run_id"):
                conn.execute(text("ALTER TABLE allocations ADD COLUMN overflow_reconcile_run_id TEXT"))
            if not _sqlite_column_exists(conn, "allocations", "overflow_reconciled_quantity"):
                conn.execute(text("ALTER TABLE allocations ADD COLUMN overflow_reconciled_quantity REAL NOT NULL DEFAULT 0.0"))
            conn.execute(
                text(
                    "UPDATE allocations "
                    "SET origin_state_code = COALESCE(NULLIF(origin_state_code, ''), origin_state, state_code)"
                )
            )
            conn.execute(
                text(
                    "UPDATE allocations "
                    "SET allocation_source_scope = CASE "
                    "WHEN COALESCE(is_unmet, 0) = 1 OR LOWER(COALESCE(supply_level, '')) = 'unmet' THEN 'unmet' "
                    "WHEN LOWER(COALESCE(supply_level, 'district')) = 'national' THEN 'national' "
                    "WHEN LOWER(COALESCE(supply_level, 'district')) = 'state' AND COALESCE(origin_state_code, state_code) <> state_code THEN 'neighbor_state' "
                    "WHEN LOWER(COALESCE(supply_level, 'district')) = 'state' THEN 'state' "
                    "ELSE 'district' END"
                )
            )
            conn.execute(
                text(
                    "UPDATE allocations "
                    "SET allocation_source_code = CASE "
                    "WHEN COALESCE(allocation_source_scope, '') = 'national' THEN 'NATIONAL' "
                    "WHEN COALESCE(allocation_source_scope, '') IN ('state','neighbor_state') THEN COALESCE(origin_state_code, state_code) "
                    "WHEN COALESCE(allocation_source_scope, '') = 'district' THEN district_code "
                    "ELSE COALESCE(origin_state_code, state_code, district_code, 'UNKNOWN') END"
                )
            )
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_allocations_solver_run ON allocations(solver_run_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_allocations_district_run_time ON allocations(district_code, solver_run_id, time)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_allocations_overflow_reconciled_at ON allocations(overflow_reconciled_at)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_allocations_request_id ON allocations(request_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_allocations_source_request_id ON allocations(source_request_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_allocations_source_batch_id ON allocations(source_batch_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_allocations_district_code ON allocations(district_code)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_allocations_state_code ON allocations(state_code)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_allocations_time ON allocations(time)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_allocations_resource_id ON allocations(resource_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_allocations_supply_level ON allocations(supply_level)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_allocations_run_id ON allocations(solver_run_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_allocations_district_run ON allocations(district_code, solver_run_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_allocations_state_run ON allocations(state_code, solver_run_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_allocations_run_time ON allocations(solver_run_id, time)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_allocations_run_district ON allocations(solver_run_id, district_code)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_allocations_run_state ON allocations(solver_run_id, state_code)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_allocations_created_at_desc ON allocations(created_at DESC)"))

            conn.execute(
                text(
                    "UPDATE allocations "
                    "SET source_request_id = request_id "
                    "WHERE COALESCE(source_request_id, 0) = 0 AND COALESCE(request_id, 0) > 0"
                )
            )
            conn.execute(
                text(
                    "UPDATE allocations "
                    "SET source_request_created_at = ("
                    "  SELECT r.created_at FROM requests r WHERE r.id = allocations.source_request_id"
                    ") "
                    "WHERE source_request_id IS NOT NULL AND source_request_created_at IS NULL"
                )
            )
            conn.execute(
                text(
                    "UPDATE allocations "
                    "SET source_batch_id = ("
                    "  SELECT r.run_id FROM requests r WHERE r.id = allocations.source_request_id"
                    ") "
                    "WHERE source_request_id IS NOT NULL AND source_batch_id IS NULL"
                )
            )
            conn.execute(
                text(
                    "UPDATE allocations "
                    "SET source_request_id = ("
                    "  SELECT r.id FROM requests r "
                    "  WHERE r.run_id = allocations.solver_run_id "
                    "    AND r.district_code = allocations.district_code "
                    "    AND r.resource_id = allocations.resource_id "
                    "    AND r.time = allocations.time "
                    "  ORDER BY r.created_at DESC, r.id DESC LIMIT 1"
                    ") "
                    "WHERE COALESCE(source_request_id, 0) = 0"
                )
            )
            conn.execute(
                text(
                    "UPDATE allocations "
                    "SET source_request_created_at = ("
                    "  SELECT r.created_at FROM requests r WHERE r.id = allocations.source_request_id"
                    ") "
                    "WHERE source_request_id IS NOT NULL AND source_request_created_at IS NULL"
                )
            )
            conn.execute(
                text(
                    "UPDATE allocations "
                    "SET source_batch_id = ("
                    "  SELECT r.run_id FROM requests r WHERE r.id = allocations.source_request_id"
                    ") "
                    "WHERE source_request_id IS NOT NULL AND source_batch_id IS NULL"
                )
            )

        if _sqlite_table_exists(conn, "solver_runs"):
            if not _sqlite_column_exists(conn, "solver_runs", "weight_model_id"):
                conn.execute(text("ALTER TABLE solver_runs ADD COLUMN weight_model_id INTEGER"))
            if not _sqlite_column_exists(conn, "solver_runs", "priority_model_id"):
                conn.execute(text("ALTER TABLE solver_runs ADD COLUMN priority_model_id INTEGER"))
            if not _sqlite_column_exists(conn, "solver_runs", "urgency_model_id"):
                conn.execute(text("ALTER TABLE solver_runs ADD COLUMN urgency_model_id INTEGER"))
            if not _sqlite_column_exists(conn, "solver_runs", "summary_snapshot_json"):
                conn.execute(text("ALTER TABLE solver_runs ADD COLUMN summary_snapshot_json TEXT"))

            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_solver_runs_status_mode ON solver_runs(status, mode, id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_solver_runs_id_desc ON solver_runs(id DESC)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_solver_runs_status ON solver_runs(status)"))

        if _sqlite_table_exists(conn, "requests"):
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_requests_district_status ON requests(district_code, status)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_requests_created_at_desc ON requests(created_at DESC)"))

        if _sqlite_table_exists(conn, "allocations") and _sqlite_table_exists(conn, "solver_runs"):
            conn.execute(text("DROP VIEW IF EXISTS latest_allocations_view"))
            conn.execute(text(
                "CREATE VIEW latest_allocations_view AS "
                "SELECT * FROM allocations "
                "WHERE solver_run_id = (SELECT MAX(id) FROM solver_runs WHERE status='completed' AND mode='live')"
            ))

        if _sqlite_table_exists(conn, "states"):
            if not _sqlite_column_exists(conn, "states", "latitude"):
                conn.execute(text("ALTER TABLE states ADD COLUMN latitude REAL"))
            if not _sqlite_column_exists(conn, "states", "longitude"):
                conn.execute(text("ALTER TABLE states ADD COLUMN longitude REAL"))

        if _sqlite_table_exists(conn, "resources"):
            if not _sqlite_column_exists(conn, "resources", "canonical_name"):
                conn.execute(text("ALTER TABLE resources ADD COLUMN canonical_name TEXT"))
            if not _sqlite_column_exists(conn, "resources", "unit"):
                conn.execute(text("ALTER TABLE resources ADD COLUMN unit TEXT"))
            conn.execute(text("DELETE FROM resources"))
            for idx, record in enumerate(canonical_records, start=1):
                conn.execute(
                    text(
                        "INSERT INTO resources(resource_id, resource_name, unit, ethical_priority, canonical_name) "
                        "VALUES (:rid, :rname, :unit, :priority, :cname)"
                    ),
                    {
                        "rid": record["canonical_id"],
                        "rname": record["name"],
                        "unit": record["unit"],
                        "priority": float(max(0.1, 2.0 - (idx / 40.0))),
                        "cname": record["name"],
                    },
                )

        for table_name in [
            "requests",
            "allocations",
            "claims",
            "consumptions",
            "returns",
            "inventory_snapshots",
            "scenario_requests",
            "scenario_state_stock",
            "scenario_national_stock",
            "pool_transactions",
            "mutual_aid_requests",
            "mutual_aid_offers",
            "shipment_plans",
            "final_demands",
            "request_predictions",
        ]:
            _remap_resource_ids(table_name)

        for table_name in ["inventory_snapshots", "requests", "allocations"]:
            if _sqlite_table_exists(conn, table_name):
                conn.execute(text(f"DROP TRIGGER IF EXISTS trg_{table_name}_resource_insert"))
                conn.execute(text(f"DROP TRIGGER IF EXISTS trg_{table_name}_resource_update"))
                conn.execute(
                    text(
                        f"CREATE TRIGGER trg_{table_name}_resource_insert "
                        f"BEFORE INSERT ON {table_name} "
                        "FOR EACH ROW "
                        "BEGIN "
                        "SELECT CASE WHEN ((SELECT COUNT(1) FROM canonical_resources WHERE canonical_id = NEW.resource_id) = 0) "
                        "THEN RAISE(ABORT, 'non-canonical resource_id rejected') END; "
                        "END;"
                    )
                )
                conn.execute(
                    text(
                        f"CREATE TRIGGER trg_{table_name}_resource_update "
                        f"BEFORE UPDATE OF resource_id ON {table_name} "
                        "FOR EACH ROW "
                        "BEGIN "
                        "SELECT CASE WHEN ((SELECT COUNT(1) FROM canonical_resources WHERE canonical_id = NEW.resource_id) = 0) "
                        "THEN RAISE(ABORT, 'non-canonical resource_id rejected') END; "
                        "END;"
                    )
                )

        if _sqlite_table_exists(conn, "claims"):
            if not _sqlite_column_exists(conn, "claims", "solver_run_id"):
                conn.execute(text("ALTER TABLE claims ADD COLUMN solver_run_id INTEGER NOT NULL DEFAULT 0"))
            if not _sqlite_column_exists(conn, "claims", "claimed_by"):
                conn.execute(text("ALTER TABLE claims ADD COLUMN claimed_by TEXT NOT NULL DEFAULT 'district_manager'"))
            if not _sqlite_column_exists(conn, "claims", "created_at"):
                conn.execute(text("ALTER TABLE claims ADD COLUMN created_at DATETIME"))

        if _sqlite_table_exists(conn, "consumptions"):
            if not _sqlite_column_exists(conn, "consumptions", "solver_run_id"):
                conn.execute(text("ALTER TABLE consumptions ADD COLUMN solver_run_id INTEGER NOT NULL DEFAULT 0"))
            if not _sqlite_column_exists(conn, "consumptions", "created_at"):
                conn.execute(text("ALTER TABLE consumptions ADD COLUMN created_at DATETIME"))

        if _sqlite_table_exists(conn, "returns"):
            if not _sqlite_column_exists(conn, "returns", "solver_run_id"):
                conn.execute(text("ALTER TABLE returns ADD COLUMN solver_run_id INTEGER NOT NULL DEFAULT 0"))
            if not _sqlite_column_exists(conn, "returns", "reason"):
                conn.execute(text("ALTER TABLE returns ADD COLUMN reason TEXT NOT NULL DEFAULT 'manual'"))
            if not _sqlite_column_exists(conn, "returns", "created_at"):
                conn.execute(text("ALTER TABLE returns ADD COLUMN created_at DATETIME"))

        if _sqlite_table_exists(conn, "audit_logs"):
            if not _sqlite_column_exists(conn, "audit_logs", "user_id"):
                conn.execute(text("ALTER TABLE audit_logs ADD COLUMN user_id TEXT"))
            if not _sqlite_column_exists(conn, "audit_logs", "action"):
                conn.execute(text("ALTER TABLE audit_logs ADD COLUMN action TEXT"))
            if not _sqlite_column_exists(conn, "audit_logs", "entity_type"):
                conn.execute(text("ALTER TABLE audit_logs ADD COLUMN entity_type TEXT"))
            if not _sqlite_column_exists(conn, "audit_logs", "entity_id"):
                conn.execute(text("ALTER TABLE audit_logs ADD COLUMN entity_id TEXT"))
            if not _sqlite_column_exists(conn, "audit_logs", "before"):
                conn.execute(text("ALTER TABLE audit_logs ADD COLUMN [before] JSON"))
            if not _sqlite_column_exists(conn, "audit_logs", "after"):
                conn.execute(text("ALTER TABLE audit_logs ADD COLUMN [after] JSON"))

        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS scenario_explanations ("
                "id INTEGER PRIMARY KEY,"
                "scenario_id INTEGER,"
                "solver_run_id INTEGER,"
                "summary TEXT NOT NULL,"
                "details JSON,"
                "created_at DATETIME"
                ")"
            )
        )

        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS agent_recommendations ("
                "id INTEGER PRIMARY KEY,"
                "finding_id INTEGER,"
                "scenario_id INTEGER,"
                "solver_run_id INTEGER,"
                "district_code TEXT,"
                "resource_id TEXT,"
                "recommendation_type TEXT,"
                "payload_json JSON,"
                "action_type TEXT NOT NULL,"
                "message TEXT NOT NULL,"
                "requires_confirmation BOOLEAN DEFAULT 1,"
                "status TEXT DEFAULT 'pending',"
                "created_at DATETIME"
                ")"
            )
        )

        if _sqlite_table_exists(conn, "agent_recommendations"):
            if not _sqlite_column_exists(conn, "agent_recommendations", "finding_id"):
                conn.execute(text("ALTER TABLE agent_recommendations ADD COLUMN finding_id INTEGER"))
            if not _sqlite_column_exists(conn, "agent_recommendations", "recommendation_type"):
                conn.execute(text("ALTER TABLE agent_recommendations ADD COLUMN recommendation_type TEXT"))
            if not _sqlite_column_exists(conn, "agent_recommendations", "payload_json"):
                conn.execute(text("ALTER TABLE agent_recommendations ADD COLUMN payload_json JSON"))

        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS agent_findings ("
                "id INTEGER PRIMARY KEY,"
                "entity_type TEXT NOT NULL,"
                "entity_id TEXT NOT NULL,"
                "finding_type TEXT NOT NULL,"
                "severity TEXT NOT NULL DEFAULT 'low',"
                "evidence_json JSON,"
                "created_at DATETIME"
                ")"
            )
        )

        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS agent_action_log ("
                "id INTEGER PRIMARY KEY,"
                "recommendation_id INTEGER NOT NULL,"
                "action_taken TEXT NOT NULL,"
                "actor_user_id TEXT NOT NULL,"
                "timestamp DATETIME"
                ")"
            )
        )

        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS nn_models ("
                "id INTEGER PRIMARY KEY,"
                "model_name TEXT NOT NULL DEFAULT 'ls_nmc',"
                "version INTEGER NOT NULL DEFAULT 1,"
                "status TEXT NOT NULL DEFAULT 'staging',"
                "artifact_uri TEXT,"
                "feature_spec_json JSON,"
                "weights_json JSON,"
                "created_at DATETIME,"
                "promoted_at DATETIME"
                ")"
            )
        )

        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS nn_predictions ("
                "id INTEGER PRIMARY KEY,"
                "solver_run_id INTEGER,"
                "model_version INTEGER,"
                "alpha REAL,"
                "beta REAL,"
                "gamma REAL,"
                "p_mult REAL,"
                "u_mult REAL,"
                "created_at DATETIME"
                ")"
            )
        )

        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS adaptive_parameters ("
                "id INTEGER PRIMARY KEY,"
                "solver_run_id INTEGER,"
                "source TEXT NOT NULL DEFAULT 'fallback',"
                "mode TEXT NOT NULL DEFAULT 'fallback',"
                "influence_pct REAL NOT NULL DEFAULT 0.0,"
                "alpha REAL NOT NULL,"
                "beta REAL NOT NULL,"
                "gamma REAL NOT NULL,"
                "p_mult REAL NOT NULL,"
                "u_mult REAL NOT NULL,"
                "guardrail_passed INTEGER NOT NULL DEFAULT 1,"
                "fallback_used INTEGER NOT NULL DEFAULT 0,"
                "reason TEXT,"
                "guardrail_result TEXT,"
                "deterministic_params_json JSON,"
                "nn_params_json JSON,"
                "applied_params_json JSON,"
                "created_at DATETIME"
                ")"
            )
        )

        if _sqlite_table_exists(conn, "adaptive_parameters"):
            if not _sqlite_column_exists(conn, "adaptive_parameters", "mode"):
                conn.execute(text("ALTER TABLE adaptive_parameters ADD COLUMN mode TEXT NOT NULL DEFAULT 'fallback'"))
            if not _sqlite_column_exists(conn, "adaptive_parameters", "influence_pct"):
                conn.execute(text("ALTER TABLE adaptive_parameters ADD COLUMN influence_pct REAL NOT NULL DEFAULT 0.0"))
            if not _sqlite_column_exists(conn, "adaptive_parameters", "guardrail_result"):
                conn.execute(text("ALTER TABLE adaptive_parameters ADD COLUMN guardrail_result TEXT"))
            if not _sqlite_column_exists(conn, "adaptive_parameters", "deterministic_params_json"):
                conn.execute(text("ALTER TABLE adaptive_parameters ADD COLUMN deterministic_params_json JSON"))
            if not _sqlite_column_exists(conn, "adaptive_parameters", "nn_params_json"):
                conn.execute(text("ALTER TABLE adaptive_parameters ADD COLUMN nn_params_json JSON"))
            if not _sqlite_column_exists(conn, "adaptive_parameters", "applied_params_json"):
                conn.execute(text("ALTER TABLE adaptive_parameters ADD COLUMN applied_params_json JSON"))

        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS adaptive_metrics ("
                "id INTEGER PRIMARY KEY,"
                "solver_run_id INTEGER,"
                "model_version INTEGER,"
                "unmet_ratio REAL,"
                "avg_delay_hours REAL,"
                "volatility REAL,"
                "stability_score REAL,"
                "created_at DATETIME"
                ")"
            )
        )

        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS neural_incident_log ("
                "id INTEGER PRIMARY KEY,"
                "solver_run_id INTEGER,"
                "incident_type TEXT NOT NULL,"
                "severity TEXT NOT NULL DEFAULT 'medium',"
                "details_json JSON,"
                "created_at DATETIME"
                ")"
            )
        )

        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS meta_controller_settings ("
                "id INTEGER PRIMARY KEY,"
                "mode TEXT NOT NULL DEFAULT 'shadow',"
                "influence_pct REAL NOT NULL DEFAULT 0.2,"
                "nn_enabled INTEGER NOT NULL DEFAULT 1,"
                "updated_at DATETIME"
                ")"
            )
        )

        conn.execute(
            text(
                "INSERT OR IGNORE INTO meta_controller_settings(id, mode, influence_pct, nn_enabled) "
                "VALUES (1, 'shadow', 0.2, 1)"
            )
        )

        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS nn_feature_cache ("
                "id INTEGER PRIMARY KEY,"
                "solver_run_id INTEGER,"
                "district_code TEXT NOT NULL,"
                "resource_id TEXT NOT NULL,"
                "time INTEGER NOT NULL,"
                "raw_features_json JSON NOT NULL,"
                "norm_features_json JSON NOT NULL,"
                "created_at DATETIME"
                ")"
            )
        )

        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS final_demands ("
                "id INTEGER PRIMARY KEY,"
                "solver_run_id INTEGER NOT NULL,"
                "district_code TEXT NOT NULL,"
                "state_code TEXT,"
                "resource_id TEXT NOT NULL,"
                "time INTEGER NOT NULL,"
                "demand_quantity REAL NOT NULL,"
                "demand_mode TEXT NOT NULL DEFAULT 'baseline_plus_human',"
                "source_mix TEXT NOT NULL DEFAULT 'merged',"
                "created_at DATETIME"
                ")"
            )
        )

        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS demand_weight_models ("
                "id INTEGER PRIMARY KEY,"
                "district_code TEXT,"
                "resource_id TEXT,"
                "time_slot INTEGER,"
                "w_baseline REAL NOT NULL,"
                "w_human REAL NOT NULL,"
                "confidence REAL NOT NULL DEFAULT 0.0,"
                "trained_on_start DATETIME,"
                "trained_on_end DATETIME,"
                "created_at DATETIME"
                ")"
            )
        )

        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS demand_learning_events ("
                "id INTEGER PRIMARY KEY,"
                "solver_run_id INTEGER NOT NULL,"
                "district_code TEXT NOT NULL,"
                "resource_id TEXT NOT NULL,"
                "time INTEGER NOT NULL,"
                "baseline_demand REAL NOT NULL,"
                "human_demand REAL NOT NULL,"
                "final_demand REAL NOT NULL,"
                "allocated REAL NOT NULL,"
                "unmet REAL NOT NULL,"
                "priority REAL NOT NULL DEFAULT 1.0,"
                "urgency REAL NOT NULL DEFAULT 1.0,"
                "created_at DATETIME"
                ")"
            )
        )

        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS priority_urgency_models ("
                "id INTEGER PRIMARY KEY,"
                "resource_id TEXT,"
                "district_code TEXT,"
                "model_type TEXT NOT NULL,"
                "version INTEGER NOT NULL DEFAULT 1,"
                "trained_on_start DATETIME,"
                "trained_on_end DATETIME,"
                "metrics_json JSON,"
                "created_at DATETIME"
                ")"
            )
        )

        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS priority_urgency_events ("
                "id INTEGER PRIMARY KEY,"
                "solver_run_id INTEGER NOT NULL,"
                "district_code TEXT NOT NULL,"
                "resource_id TEXT NOT NULL,"
                "time INTEGER NOT NULL,"
                "baseline_demand REAL NOT NULL DEFAULT 0.0,"
                "human_quantity REAL NOT NULL DEFAULT 0.0,"
                "final_demand REAL NOT NULL DEFAULT 0.0,"
                "allocated REAL NOT NULL DEFAULT 0.0,"
                "unmet REAL NOT NULL DEFAULT 0.0,"
                "human_priority REAL,"
                "human_urgency REAL,"
                "severity_index REAL NOT NULL DEFAULT 0.0,"
                "infrastructure_damage_index REAL NOT NULL DEFAULT 0.0,"
                "population_exposed REAL NOT NULL DEFAULT 0.0,"
                "created_at DATETIME"
                ")"
            )
        )

        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS request_predictions ("
                "id INTEGER PRIMARY KEY,"
                "request_id INTEGER NOT NULL,"
                "predicted_priority REAL,"
                "predicted_urgency REAL,"
                "model_id INTEGER,"
                "confidence REAL NOT NULL DEFAULT 0.0,"
                "explanation_json JSON,"
                "created_at DATETIME"
                ")"
            )
        )

        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS inventory_snapshots ("
                "id INTEGER PRIMARY KEY,"
                "solver_run_id INTEGER NOT NULL,"
                "district_code TEXT NOT NULL,"
                "resource_id TEXT NOT NULL,"
                "time INTEGER NOT NULL,"
                "quantity REAL NOT NULL,"
                "created_at DATETIME"
                ")"
            )
        )

        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS shipment_plans ("
                "id INTEGER PRIMARY KEY,"
                "solver_run_id INTEGER NOT NULL,"
                "from_district TEXT NOT NULL,"
                "to_district TEXT NOT NULL,"
                "resource_id TEXT NOT NULL,"
                "time INTEGER NOT NULL,"
                "quantity REAL NOT NULL,"
                "status TEXT NOT NULL DEFAULT 'planned',"
                "created_at DATETIME"
                ")"
            )
        )

        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS mutual_aid_requests ("
                "id INTEGER PRIMARY KEY,"
                "requesting_state TEXT NOT NULL,"
                "requesting_district TEXT NOT NULL,"
                "resource_id TEXT NOT NULL,"
                "quantity_requested REAL NOT NULL,"
                "time INTEGER NOT NULL,"
                "status TEXT NOT NULL DEFAULT 'open',"
                "created_at DATETIME"
                ")"
            )
        )

        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS mutual_aid_offers ("
                "id INTEGER PRIMARY KEY,"
                "request_id INTEGER NOT NULL,"
                "offering_state TEXT NOT NULL,"
                "quantity_offered REAL NOT NULL,"
                "status TEXT NOT NULL DEFAULT 'pending',"
                "created_at DATETIME"
                ")"
            )
        )

        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS state_transfers ("
                "id INTEGER PRIMARY KEY,"
                "solver_run_id INTEGER,"
                "request_id INTEGER,"
                "offer_id INTEGER,"
                "from_state TEXT NOT NULL,"
                "to_state TEXT NOT NULL,"
                "resource_id TEXT NOT NULL,"
                "quantity REAL NOT NULL,"
                "time INTEGER NOT NULL,"
                "status TEXT NOT NULL DEFAULT 'confirmed',"
                "transfer_kind TEXT NOT NULL DEFAULT 'aid',"
                "consumed_in_run_id INTEGER,"
                "created_at DATETIME"
                ")"
            )
        )

        _print_query_plan(
            conn,
            "SELECT solver_run_id, district_code, resource_id, time, SUM(allocated_quantity) "
            "FROM allocations WHERE state_code=:state_code AND is_unmet=0 GROUP BY solver_run_id, district_code, resource_id, time",
            {"state_code": "33"},
        )
        _print_query_plan(
            conn,
            "SELECT solver_run_id, state_code, district_code, resource_id, time, SUM(allocated_quantity) "
            "FROM allocations WHERE is_unmet=0 GROUP BY solver_run_id, state_code, district_code, resource_id, time",
        )
        _print_query_plan(
            conn,
            "SELECT solver_run_id, SUM(allocated_quantity) FROM allocations WHERE state_code=:state_code AND is_unmet=0 GROUP BY solver_run_id",
            {"state_code": "33"},
        )