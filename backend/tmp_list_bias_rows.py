import sqlite3
conn=sqlite3.connect('backend.db')
cur=conn.cursor()
rows=cur.execute("""
select id, scope, district_code, state_code, resource_id, quantity_delta, reason, actor_id, source, created_at
from stock_refill_transactions
where lower(reason) like '%suppress%'
   or lower(reason) like '%bias%'
   or lower(reason) like '%temporary%'
   or lower(actor_id) like '%suppress%'
   or lower(actor_id) like '%bias%'
   or lower(actor_id) like '%temp%'
order by id desc
limit 200
""").fetchall()
print('COUNT', len(rows))
for r in rows[:40]:
    print(r)
conn.close()
