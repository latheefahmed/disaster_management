from app.database import SessionLocal
from app.services.scenario_control_service import build_randomizer_preview

db = SessionLocal()
try:
    out = build_randomizer_preview(db, 348, {
        'preset': 'medium',
        'time_horizon': 1,
        'state_codes': ['33'],
        'district_codes': [],
        'resource_ids': [],
        'district_count': 5,
        'resource_count': 4,
        'replace_existing': False,
        'quantity_mode': 'stock_aware',
        'stock_aware_distribution': True,
    })
    print('OK', out.get('district_count'), out.get('resource_count'))
    print('MODES', out.get('district_selection_mode'), out.get('resource_selection_mode'))
    print('REQ', out.get('district_count_requested'), out.get('resource_count_requested'))
except Exception as e:
    print('ERR', type(e).__name__, str(e))
finally:
    db.close()
