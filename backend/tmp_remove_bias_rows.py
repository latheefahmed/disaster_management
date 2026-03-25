import shutil, sqlite3
from datetime import datetime

DB='backend.db'
ts=datetime.now().strftime('%Y%m%d_%H%M%S')
backup=f'backend_pre_remove_bias_{ts}.db'
shutil.copy2(DB, backup)

conn=sqlite3.connect(DB)
cur=conn.cursor()
reasons=('variant_path_bias_603','state_first_urgent_bias')
count_before=cur.execute("select count(*) from stock_refill_transactions where reason in (?,?)", reasons).fetchone()[0]
cur.execute("delete from stock_refill_transactions where reason in (?,?)", reasons)
conn.commit()
count_after=cur.execute("select count(*) from stock_refill_transactions where reason in (?,?)", reasons).fetchone()[0]
conn.close()
print('BACKUP', backup)
print('DELETED', count_before-count_after)
print('REMAINING', count_after)
