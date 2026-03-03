from __future__ import annotations

from pathlib import Path


def main():
    sql = """
-- Partition-prep hooks for PostgreSQL deployments
-- Run manually in production if allocations/requests are moved to partitioned tables.

CREATE INDEX IF NOT EXISTS idx_allocations_solver_created_id ON allocations(solver_run_id, created_at, id);
CREATE INDEX IF NOT EXISTS idx_allocations_request_created ON allocations(request_id, created_at);
CREATE INDEX IF NOT EXISTS idx_requests_run_created ON requests(run_id, created_at);

-- Example monthly partition templates (uncomment when allocations is partitioned by created_at)
-- CREATE TABLE IF NOT EXISTS allocations_2026_02 PARTITION OF allocations
--   FOR VALUES FROM ('2026-02-01') TO ('2026-03-01');
-- CREATE INDEX IF NOT EXISTS idx_allocations_2026_02_solver_created_id ON allocations_2026_02(solver_run_id, created_at, id);
""".strip()

    out = Path("backend") / "POSTGRES_PARTITION_PREP.sql"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(sql + "\n", encoding="utf-8")
    print(str(out))


if __name__ == "__main__":
    main()
