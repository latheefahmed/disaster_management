from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = CURRENT_DIR.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import SessionLocal, apply_runtime_migrations
from app.services.overflow_reconciliation_service import (
    OverflowReconcileOptions,
    reconcile_overflow_allocations,
)
from app.services.overflow_reconciliation_validation import validate_overflow_reconciliation


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Reconcile allocations older than active window")
    parser.add_argument("--keep-latest", type=int, default=300, help="Number of latest allocations to keep active")
    parser.add_argument("--chunk-size", type=int, default=100, help="Batch size for reconciliation")
    parser.add_argument("--district", type=str, default=None, help="Optional district scope, e.g., 603")
    parser.add_argument("--apply", action="store_true", help="Apply changes; default is dry-run")
    parser.add_argument("--max-process", type=int, default=None, help="Optional max allocations to process in this run")
    parser.add_argument("--compact", action="store_true", help="Print compact summary instead of full JSON")
    parser.add_argument("--run-id", type=str, default=None, help="Logical reconciliation run identifier")
    parser.add_argument(
        "--report",
        type=str,
        default="backend/OVERFLOW_RECONCILIATION_REPORT.json",
        help="Path to write JSON report",
    )
    return parser


def main():
    args = _build_parser().parse_args()
    apply_runtime_migrations()
    run_id = args.run_id or f"overflow-reconcile-{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}"

    options = OverflowReconcileOptions(
        keep_latest=max(1, int(args.keep_latest)),
        chunk_size=max(1, int(args.chunk_size)),
        only_district_code=(None if not args.district else str(args.district)),
        dry_run=(not bool(args.apply)),
        reconcile_run_id=run_id,
        max_process=(None if args.max_process is None else max(1, int(args.max_process))),
    )

    db = SessionLocal()
    try:
        result = reconcile_overflow_allocations(db, options)
    finally:
        db.close()

    result["run_id"] = run_id
    result["applied"] = bool(args.apply)
    result["generated_at"] = datetime.utcnow().isoformat() + "Z"
    validation_db = SessionLocal()
    try:
        result["validation"] = validate_overflow_reconciliation(
            validation_db,
            keep_latest=max(1, int(args.keep_latest)),
            district_code=(None if not args.district else str(args.district)),
        )
    finally:
        validation_db.close()

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    if args.compact:
        print(
            json.dumps(
                {
                    "run_id": result.get("run_id"),
                    "processed": result.get("processed"),
                    "returned": result.get("returned"),
                    "refilled": result.get("refilled"),
                    "skipped": result.get("skipped"),
                    "failed": result.get("failed"),
                    "stopped_early": result.get("stopped_early", False),
                    "validation_ok": bool((result.get("validation") or {}).get("ok", False)),
                    "validation_unresolved": int((result.get("validation") or {}).get("unresolved_overflow", 0)),
                }
            )
        )
    else:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
