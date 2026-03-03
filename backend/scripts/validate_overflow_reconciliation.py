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
from app.services.overflow_reconciliation_validation import validate_overflow_reconciliation


def main():
    parser = argparse.ArgumentParser(description="Validate overflow reconciliation consistency")
    parser.add_argument("--keep-latest", type=int, default=300)
    parser.add_argument("--district", type=str, default=None)
    parser.add_argument(
        "--report",
        type=str,
        default="backend/OVERFLOW_RECONCILIATION_VALIDATION.json",
        help="Path to write JSON report",
    )
    args = parser.parse_args()

    apply_runtime_migrations()

    db = SessionLocal()
    try:
        report = validate_overflow_reconciliation(
            db,
            keep_latest=max(1, int(args.keep_latest)),
            district_code=(None if not args.district else str(args.district)),
        )
    finally:
        db.close()

    report["generated_at"] = datetime.utcnow().isoformat() + "Z"

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(json.dumps(report))


if __name__ == "__main__":
    main()
