import sqlite3
conn=sqlite3.connect('backend.db')
cur=conn.cursor()
print('BIAS_REASONS_LEFT', cur.execute("select count(*) from stock_refill_transactions where reason in ('variant_path_bias_603','state_first_urgent_bias')").fetchone()[0])
print('TEMP_PATTERN_LEFT', cur.execute("select count(*) from stock_refill_transactions where lower(reason) like '%suppress%' or lower(reason) like '%bias%' or lower(reason) like '%temporary%' or lower(actor_id) like '%temp%' or lower(actor_id) like '%bias%' or lower(actor_id) like '%suppress%'").fetchone()[0])
conn.close()
