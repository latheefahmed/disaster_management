import sqlite3, json
from pathlib import Path

cur_db = Path('backend.db')
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

def table_exists(cur, t):
    return cur.execute("select 1 from sqlite_master where type='table' and name=?", (t,)).fetchone() is not None

def cols(cur, t):
    return {r[1] for r in cur.execute(f"pragma table_info({t})").fetchall()}

def scalar(cur, sql):
    r = cur.execute(sql).fetchone()
    return 0.0 if not r or r[0] is None else float(r[0])

con = sqlite3.connect(str(cur_db))
cur = con.cursor()
bcon = sqlite3.connect(str(backup_db)) if backup_db.exists() else None
bcur = bcon.cursor() if bcon else None

report = {
  'latest_completed_live_run': cur.execute("select id from solver_runs where status='completed' and mode='live' order by id desc limit 1").fetchone(),
  'tables_checked': {},
  'runs_checked': {},
  'scopes_checked': {},
  'resource_maxima_top20': [],
  'remaining_alerts': []
}

# table coverage
for t, qty_cols in TABLES.items():
    if not table_exists(cur, t):
        continue
    present = [c for c in qty_cols if c in cols(cur, t)]
    if not present:
        continue
    row = {'row_count': int(cur.execute(f"select count(1) from {t}").fetchone()[0]), 'columns': {}}
    for c in present:
        now_sum = scalar(cur, f"select coalesce(sum({c}),0) from {t}")
        now_max = scalar(cur, f"select coalesce(max(abs({c})),0) from {t}")
        before_sum = None
        before_max = None
        if bcur and table_exists(bcur, t) and c in cols(bcur, t):
            before_sum = scalar(bcur, f"select coalesce(sum({c}),0) from {t}")
            before_max = scalar(bcur, f"select coalesce(max(abs({c})),0) from {t}")
        row['columns'][c] = {
            'current_sum': now_sum,
            'current_max_abs': now_max,
            'backup_pre_second_sum': before_sum,
            'backup_pre_second_max_abs': before_max,
        }
    report['tables_checked'][t] = row

# run coverage aggregated once
run_rows = cur.execute("""
select sr.id,
       coalesce(a.alloc,0) as allocated,
       coalesce(a.unmet,0) as unmet,
       coalesce(fd.fd,0) as final_demand,
       coalesce(a.max_slot,0) as max_slot
from solver_runs sr
left join (
    select solver_run_id,
           sum(case when is_unmet=0 then allocated_quantity else 0 end) alloc,
           sum(case when is_unmet=1 then allocated_quantity else 0 end) unmet,
           max(abs(allocated_quantity)) max_slot
    from allocations
    group by solver_run_id
) a on a.solver_run_id = sr.id
left join (
    select solver_run_id, sum(demand_quantity) fd
    from final_demands
    group by solver_run_id
) fd on fd.solver_run_id = sr.id
where sr.status='completed' and sr.mode='live'
order by sr.id
""").fetchall()

runs = [
    {
      'run_id': int(r[0]),
      'allocated_total': float(r[1] or 0),
      'unmet_total': float(r[2] or 0),
      'final_demand_total': float(r[3] or 0),
      'max_allocation_slot': float(r[4] or 0),
    }
    for r in run_rows
]

report['runs_checked'] = {
    'count': len(runs),
    'max_allocated_total_run': max(runs, key=lambda x: x['allocated_total']) if runs else None,
    'max_single_slot_run': max(runs, key=lambda x: x['max_allocation_slot']) if runs else None,
    'latest_15_runs': runs[-15:]
}

# scope coverage
alloc_scope = {
    str(k): float(v or 0)
    for k, v in cur.execute("select lower(coalesce(supply_level,'district')), sum(allocated_quantity) from allocations where is_unmet=0 group by lower(coalesce(supply_level,'district'))").fetchall()
}
refill_scope = {
    str(k): float(v or 0)
    for k, v in cur.execute("select lower(coalesce(scope,'unknown')), sum(quantity_delta) from stock_refill_transactions group by lower(coalesce(scope,'unknown'))").fetchall()
}
report['scopes_checked'] = {
    'allocation_supply_level_totals': alloc_scope,
    'refill_scope_totals': refill_scope,
    'scenario_state_stock_total': scalar(cur, "select coalesce(sum(quantity),0) from scenario_state_stock") if table_exists(cur,'scenario_state_stock') else 0,
    'scenario_national_stock_total': scalar(cur, "select coalesce(sum(quantity),0) from scenario_national_stock") if table_exists(cur,'scenario_national_stock') else 0,
    'pool_transactions_abs_total': scalar(cur, "select coalesce(sum(abs(quantity_delta)),0) from pool_transactions") if table_exists(cur,'pool_transactions') else 0,
}

# top maxima by resource across all runs
for rid, name, unit, mx in cur.execute("""
select a.resource_id, r.resource_name, r.unit, max(abs(a.allocated_quantity)) mx
from allocations a
left join resources r on r.resource_id = a.resource_id
group by a.resource_id
order by mx desc
limit 20
""").fetchall():
    report['resource_maxima_top20'].append({
        'resource_id': rid,
        'resource_name': name,
        'unit': unit,
        'max_abs_allocation': float(mx or 0)
    })

# alert scan
for item in report['resource_maxima_top20']:
    unit = str(item.get('unit') or '').lower()
    mx = float(item['max_abs_allocation'])
    if 'liter' in unit and mx > 50000:
        report['remaining_alerts'].append(f"{item['resource_id']} liters max={mx}")
    elif unit == 'kg' and mx > 20000:
        report['remaining_alerts'].append(f"{item['resource_id']} kg max={mx}")
    elif unit in ('units','kits','packets','courses') and mx > 20000:
        report['remaining_alerts'].append(f"{item['resource_id']} units-like max={mx}")

Path('FULL_SCALE_VERIFICATION_REPORT.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps({
    'status':'ok',
    'report':'FULL_SCALE_VERIFICATION_REPORT.json',
    'tables_checked': len(report['tables_checked']),
    'runs_checked': report['runs_checked']['count'],
    'alerts': len(report['remaining_alerts'])
}, indent=2))

if bcon:
    bcon.close()
con.close()
