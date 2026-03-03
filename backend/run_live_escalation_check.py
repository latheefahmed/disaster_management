import json
from app.database import SessionLocal
from run_stability_matrix import run_live_determinism, run_escalation_non_blocking


def main():
    db = SessionLocal()
    try:
        live = run_live_determinism(db)
        esc = run_escalation_non_blocking(db)
        print(json.dumps({"live": live, "escalation": esc}, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
