from app.database import SessionLocal
from app.services.stock_refill_service import build_live_stock_override_files
import csv

db = SessionLocal()
try:
    d_path, s_path, n_path = build_live_stock_override_files(db)
    print('PATHS', d_path, s_path, n_path)
    d_qty = None
    s_qty = None
    n_qty = None
    if d_path:
        with open(d_path, newline='', encoding='utf-8') as f:
            for r in csv.DictReader(f):
                if r.get('district_code') == '603' and r.get('resource_id') == 'R38':
                    d_qty = float(r.get('quantity') or 0.0)
                    break
    if s_path:
        with open(s_path, newline='', encoding='utf-8') as f:
            for r in csv.DictReader(f):
                if r.get('state_code') == '33' and r.get('resource_id') == 'R38':
                    s_qty = float(r.get('quantity') or 0.0)
                    break
    if n_path:
        with open(n_path, newline='', encoding='utf-8') as f:
            for r in csv.DictReader(f):
                if r.get('resource_id') == 'R38':
                    n_qty = float(r.get('quantity') or 0.0)
                    break
    print({'R38_district_603_live_override': d_qty, 'R38_state_33_live_override': s_qty, 'R38_national_live_override': n_qty})
finally:
    db.close()
