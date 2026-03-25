import sqlite3

con = sqlite3.connect("backend.db")
con.row_factory = sqlite3.Row
cur = con.cursor()

rows = cur.execute(
    """
    select id, resource_id, quantity, time, status, run_id, created_at
    from requests
    where district_code = ?
    order by id desc
    limit 25
    """,
    ("603",),
).fetchall()

print("REQS")
for r in rows:
    print(dict(r))

request_ids = [int(r["id"]) for r in rows]
if request_ids:
    placeholders = ",".join("?" for _ in request_ids)
    allocs = cur.execute(
        f"""
        select
            request_id,
            coalesce(allocation_source_scope, '') as scope,
            coalesce(allocation_source_code, '') as code,
            coalesce(origin_state_code, '') as origin,
            sum(allocated_quantity) as qty,
            max(case when is_unmet = 1 then 1 else 0 end) as unmet
        from allocations
        where request_id in ({placeholders})
        group by request_id, scope, code, origin
        order by request_id desc, scope asc
        """,
        request_ids,
    ).fetchall()

    print("ALLOCS")
    for a in allocs:
        print(dict(a))

con.close()
