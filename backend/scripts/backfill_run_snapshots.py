import argparse

from app.database import SessionLocal
from app.models.solver_run import SolverRun
from app.services.run_snapshot_service import persist_solver_run_snapshot


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=300)
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        query = db.query(SolverRun).filter(SolverRun.status == "completed").order_by(SolverRun.id.desc())
        if not args.all:
            query = query.limit(max(1, int(args.limit)))
        runs = query.all()

        updated = 0
        skipped = 0
        for run in runs:
            if getattr(run, "summary_snapshot_json", None):
                skipped += 1
                continue
            persist_solver_run_snapshot(db, int(run.id))
            updated += 1
            if updated % 25 == 0:
                db.commit()
                print(f"SNAPSHOT_BACKFILL progress updated={updated} skipped={skipped}")

        db.commit()
        print({"status": "ok", "updated": updated, "skipped": skipped, "total": len(runs)})
    finally:
        db.close()


if __name__ == "__main__":
    main()
