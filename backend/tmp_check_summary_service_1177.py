from app.database import SessionLocal
from app.services.scenario_service import get_scenario_run_summary
import json

db=SessionLocal()
try:
    body=get_scenario_run_summary(db, 405, 1177)
    esc=(body or {}).get('escalation_status') or {}
    print(json.dumps({
      'mode': esc.get('mode'),
      'events_found': esc.get('events_found'),
      'state_marked': esc.get('state_marked'),
      'national_marked': esc.get('national_marked'),
      'neighbor_offers_created': esc.get('neighbor_offers_created'),
      'neighbor_offers_accepted': esc.get('neighbor_offers_accepted'),
      'neighbor_accepted_quantity': esc.get('neighbor_accepted_quantity'),
      'used_state_stock': (body or {}).get('used_state_stock'),
      'used_national_stock': (body or {}).get('used_national_stock'),
      'source_scope_breakdown': ((body or {}).get('source_scope_breakdown') or {}).get('allocations'),
      'totals': (body or {}).get('totals'),
    }, indent=2))
finally:
    db.close()
