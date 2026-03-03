import sqlite3
from datetime import datetime

con = sqlite3.connect('backend.db')
cur = con.cursor()

print('--- candidate misrouted return pool tx (recent) ---')
rows = cur.execute(
    """
    select pt.id, pt.state_code, pt.district_code, pt.resource_id, pt.time, pt.quantity_delta, pt.reason
    from pool_transactions pt
    where pt.reason like 'district_return_to_origin:%' and pt.quantity_delta > 0
    order by pt.id desc
    limit 50
    """
).fetchall()
for r in rows:
    print(r)

# Backfill only obvious district-origin cases:
# if the latest matching allocation slot for district/resource/time is district-sourced,
# then credit district stock and neutralize pool mis-credit exactly once.
fix_count = 0
for tx_id, state_code, district_code, resource_id, time_idx, qty, reason in rows:
    alloc = cur.execute(
        """
        select allocation_source_scope, allocation_source_code
        from allocations
        where district_code = ? and resource_id = ? and time = ? and is_unmet = 0
        order by solver_run_id desc, id desc
        limit 1
        """,
        (str(district_code), str(resource_id), int(time_idx)),
    ).fetchone()
    if not alloc:
        continue
    scope, code = alloc
    if str(scope or '').strip().lower() != 'district':
        continue

    marker = f'district_return_backfill_from_pool_tx:{tx_id}'
    exists = cur.execute(
        "select 1 from stock_refill_transactions where source = 'district_return_backfill' and reason = ? limit 1",
        (marker,),
    ).fetchone()
    if exists:
        continue

    # 1) district stock credit
    cur.execute(
        """
        insert into stock_refill_transactions
        (scope, district_code, state_code, resource_id, quantity_delta, reason, actor_role, actor_id, source, solver_run_id, created_at)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            'district',
            str(district_code),
            str(code or ''),
            str(resource_id),
            float(qty),
            marker,
            'system',
            'backfill',
            'district_return_backfill',
            None,
            datetime.utcnow().isoformat(sep=' '),
        ),
    )

    # 2) neutralize incorrect pool credit
    cur.execute(
        """
        insert into pool_transactions
        (state_code, district_code, resource_id, time, quantity_delta, reason, actor_role, actor_id, created_at)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(state_code),
            str(district_code),
            str(resource_id),
            int(time_idx),
            -float(qty),
            f'district_return_pool_backfill_reversal:{tx_id}',
            'system',
            'backfill',
            datetime.utcnow().isoformat(sep=' '),
        ),
    )

    fix_count += 1

if fix_count:
    con.commit()

print(f'backfilled={fix_count}')

print('--- latest stock refills for R37 ---')
for r in cur.execute("select id, scope, district_code, state_code, resource_id, quantity_delta, source, reason from stock_refill_transactions where resource_id='R37' order by id desc limit 20"):
    print(r)

print('--- latest pool tx for R37 ---')
for r in cur.execute("select id, state_code, district_code, resource_id, time, quantity_delta, reason from pool_transactions where resource_id='R37' order by id desc limit 20"):
    print(r)

con.close()
