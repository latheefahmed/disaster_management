from app.database import SessionLocal
from app.services.scenario_service import get_scenario_run_summary

db=SessionLocal()
try:
    s=get_scenario_run_summary(db,429,1200)
    print('MODE', (s.get('escalation_status') or {}).get('mode'))
    print('GLOBAL', ((s.get('source_scope_breakdown') or {}).get('allocations') or {}))
    print('DISTRICT', s.get('district_source_scope_breakdown'))
finally:
    db.close()
