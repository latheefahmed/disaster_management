import sqlite3, json, math
from collections import defaultdict
from pathlib import Path

cur_db = Path('backend.db')
# latest backup before second pass (contains pre-second values)
backup_db = Path('backend_pre_realworld_scale_20260304_203800.db')

TABLES = {
  'allocations':['allocated_quantity','claimed_quantity','consumed_quantity','returned_quantity','overflow_reconciled_quantity'],
  'claims':['quantity'],
  'consumptions':['quantity'],
  'returns':['quantity'],
  'final_demands':['demand_quantity'],
  'requests':['quantity','allocated_quantity','unmet_quantity','final_demand_quantity'],
  'inventory_snapshots':['quantity'],
  'scenario_requests':['quantity'],
  'scenario_state_stock':['quantity'],
  'scenario_national_stock':['quantity'],
  'shipment_plans':['quantity'],
  'state_transfers':['quantity'],
  'mutual_aid_requests':['quantity_requested'],
  'pool_transactions':['quantity_delta'],
  'stock_refill_transactions':['quantity_delta'],
  'demand_learning_events':['baseline_demand','human_demand','final_demand','allocated','unmet'],
  'priority_urgency_events':['baseline_demand','human_quantity','final_demand','allocated','unmet'],
}

def cols(cur, t):
    return {r[1] for r in cur.execute(f"pragma table_info({t})").fetchall()}

def table_exists(cur, t):
    return cur.execute("select 1 from sqlite_master where type='table' and name=?", (t,)).fetchone() is not None

def scalar(cur, sql):
    r = cur.execute(sql).fetchone()
    return 0.0 if not r or r[0] is None else float(r[0])

con = sqlite3.connect(str(cur_db))
cur = con.cursor()

bcon = sqlite3.connect(str(backup_db)) if backup_db.exists() else None
bcur = bcon.cursor() if bcon else None

report = {
  'db': str(cur_db.resolve()),
  'backup': str(backup_db.resolve()) if backup_db.exists() else None,
  'latest_completed_live_run': cur.execute("select id from solver_runs where status='completed' and mode='live' order by id desc limit 1").fetchone(),
  'table_audit': {},
  'run_audit': {},
  'scope_audit': {},
  'resource_maxima': [],
  'alerts': []
}

# 1) table-level totals before/after per qty col
for t, qty_cols in TABLES.items():
    if not table_exists(cur, t):
      continue
    ecols = cols(cur, t)
    present = [c for c in qty_cols if c in ecols]
    if not present:
      continue
    tentry = {'rows': int(cur.execute(f"select count(1) from {t}").fetchone()[0]), 'columns': {}}
    for c in present:
      now_sum = scalar(cur, f"select coalesce(sum({c}),0) from {t}")
      now_abs_sum = scalar(cur, f"select coalesce(sum(abs({c})),0) from {t}")
      now_max = scalar(cur, f"select coalesce(max(abs({c})),0) from {t}")
      before = None
      if bcur is not None and table_exists(bcur, t) and c in cols(bcur, t):
        before = {
          'sum': scalar(bcur, f"select coalesce(sum({c}),0) from {t}"),
          'abs_sum': scalar(bcur, f"select coalesce(sum(abs({c})),0) from {t}"),
          'max_abs': scalar(bcur, f"select coalesce(max(abs({c})),0) from {t}"),
        }
      tentry['columns'][c] = {
        'current': {'sum': now_sum, 'abs_sum': now_abs_sum, 'max_abs': now_max},
        'backup_pre_second_pass': before,
      }
    report['table_audit'][t] = tentry

# 2) run-level audit across ALL completed live runs
runs = [int(r[0]) for r in cur.execute("select id from solver_runs where status='completed' and mode='live' order by id").fetchall()]
run_stats = []
for rid in runs:
  alloc = scalar(cur, f"select coalesce(sum(allocated_quantity),0) from allocations where solver_run_id={rid} and is_unmet=0")
  unmet = scalar(cur, f"select coalesce(sum(allocated_quantity),0) from allocations where solver_run_id={rid} and is_unmet=1")
  fd = scalar(cur, f"select coalesce(sum(demand_quantity),0) from final_demands where solver_run_id={rid}")
  max_slot = scalar(cur, f"select coalesce(max(abs(allocated_quantity)),0) from allocations where solver_run_id={rid}")
  run_stats.append({'run_id':rid,'allocated_total':alloc,'unmet_total':unmet,'final_demand_total':fd,'max_allocation_slot':max_slot})

report['run_audit'] = {
  'run_count': len(run_stats),
  'max_allocated_total_run': max(run_stats, key=lambda x: x['allocated_total']) if run_stats else None,
  'max_single_slot_run': max(run_stats, key=lambda x: x['max_allocation_slot']) if run_stats else None,
  'latest_10': run_stats[-10:]
}

# 3) scope audit district/state/national/admin-relevant
# district/state from allocations + refill transactions + pool transactions, national from refill/scenario national
scope_alloc = defaultdict(float)
for scope, qty in cur.execute("select lower(coalesce(supply_level,'district')), coalesce(sum(allocated_quantity),0) from allocations where is_unmet=0 group by lower(coalesce(supply_level,'district'))").fetchall():
  scope_alloc[str(scope)] += float(qty or 0)

scope_refill = defaultdict(float)
for scope, qty in cur.execute("select lower(coalesce(scope,'unknown')), coalesce(sum(quantity_delta),0) from stock_refill_transactions group by lower(coalesce(scope,'unknown'))").fetchall():
  scope_refill[str(scope)] += float(qty or 0)

state_pool = scalar(cur, "select coalesce(sum(abs(quantity_delta)),0) from pool_transactions")
nat_stock = scalar(cur, "select coalesce(sum(quantity),0) from scenario_national_stock") if table_exists(cur,'scenario_national_stock') else 0.0
state_stock = scalar(cur, "select coalesce(sum(quantity),0) from scenario_state_stock") if table_exists(cur,'scenario_state_stock') else 0.0

report['scope_audit'] = {
  'allocation_by_supply_level': dict(scope_alloc),
  'stock_refill_by_scope': dict(scope_refill),
  'pool_transactions_abs_total': state_pool,
  'scenario_state_stock_total': state_stock,
  'scenario_national_stock_total': nat_stock,
}

# 4) resource maxima across all runs/resources
for rid, rname, unit, mx, sm in cur.execute("select a.resource_id, r.resource_name, r.unit, max(abs(a.allocated_quantity)) mx, sum(abs(a.allocated_quantity)) sm from allocations a left join resources r on r.resource_id=a.resource_id group by a.resource_id order by mx desc limit 40").fetchall():
  report['resource_maxima'].append({'resource_id':rid,'resource_name':rname,'unit':unit,'max_abs_allocation':float(mx or 0),'sum_abs_allocation':float(sm or 0)})

# 5) simple alerts for very high outliers post-scale
for item in report['resource_maxima'][:10]:
  unit = (item.get('unit') or '').lower()
  mx = float(item['max_abs_allocation'])
  if 'liter' in unit and mx > 50000:
    report['alerts'].append(f"High liters outlier remains: {item['resource_id']} max={mx}")
  if unit == 'kg' and mx > 20000:
    report['alerts'].append(f"High kg outlier remains: {item['resource_id']} max={mx}")
  if unit in ('units','kits','packets') and mx > 20000:
    report['alerts'].append(f"High unit outlier remains: {item['resource_id']} max={mx}")

Path('FULL_SCALE_VERIFICATION_REPORT.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps({'status':'ok','report':'FULL_SCALE_VERIFICATION_REPORT.json','runs_audited':len(runs),'tables_audited':len(report['table_audit']),'alerts':len(report['alerts'])}, indent=2))

if bcon:
  bcon.close()
con.close()
