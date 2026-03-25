from app.database import SessionLocal
from app.services.mutual_aid_service import create_requests_from_unmet_allocations, auto_progress_mutual_aid_for_solver_run

db = SessionLocal()
try:
    created = create_requests_from_unmet_allocations(db, solver_run_id=1177)
    out = auto_progress_mutual_aid_for_solver_run(db, solver_run_id=1177)
    print('CREATED_REQUESTS', created)
    print('AUTO_CHAIN', out)
finally:
    db.close()
