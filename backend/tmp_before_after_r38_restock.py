import sqlite3
from pathlib import Path

db = sqlite3.connect('backend.db')
cur = db.cursor()
backup = Path('backend_pre_bulk_return_integerize_20260304_213517.db').resolve()
cur.execute('ATTACH DATABASE ? AS bkp', (str(backup),))

queries = {
    'before_d603_r38_district_delta': "select coalesce(sum(quantity_delta),0) from bkp.stock_refill_transactions where scope='district' and district_code='603' and resource_id='R38'",
    'before_s33_r38_state_delta': "select coalesce(sum(quantity_delta),0) from bkp.stock_refill_transactions where scope='state' and state_code='33' and resource_id='R38'",
    'before_r38_national_delta': "select coalesce(sum(quantity_delta),0) from bkp.stock_refill_transactions where scope='national' and resource_id='R38'",
    'after_d603_r38_district_delta': "select coalesce(sum(quantity_delta),0) from stock_refill_transactions where scope='district' and district_code='603' and resource_id='R38'",
    'after_s33_r38_state_delta': "select coalesce(sum(quantity_delta),0) from stock_refill_transactions where scope='state' and state_code='33' and resource_id='R38'",
    'after_r38_national_delta': "select coalesce(sum(quantity_delta),0) from stock_refill_transactions where scope='national' and resource_id='R38'",
    'added_bulk_restock_r38_state': "select coalesce(sum(quantity_delta),0) from stock_refill_transactions where reason='bulk_return_restock' and scope='state' and state_code='33' and resource_id='R38'",
    'added_bulk_restock_r38_national': "select coalesce(sum(quantity_delta),0) from stock_refill_transactions where reason='bulk_return_restock' and scope='national' and resource_id='R38'",
}

out = {k: float(cur.execute(v).fetchone()[0] or 0.0) for k, v in queries.items()}
print(out)
cur.execute('DETACH DATABASE bkp')
db.close()
