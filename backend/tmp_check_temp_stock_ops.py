import sqlite3
conn=sqlite3.connect('backend.db')
cur=conn.cursor()
rows=cur.execute("""
select reason, actor_id, source, count(*) c, round(sum(quantity_delta),3) q
from stock_refill_transactions
group by reason, actor_id, source
order by c desc
limit 30
""").fetchall()
print('TOP_REASONS', rows)
print('TEMP_ROWS', cur.execute("select count(*) from stock_refill_transactions where lower(reason) like '%suppress%' or lower(reason) like '%bias%' or lower(reason) like '%temporary%' or lower(actor_id) like '%temp%' or lower(actor_id) like '%suppress%' ").fetchone()[0])
conn.close()
