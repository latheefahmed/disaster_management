import sqlite3
conn=sqlite3.connect('backend.db')
cur=conn.cursor()

for table,col in [('scenario_state_stock','state_code'),('stock_refill_transactions','state_code'),('allocations','origin_state_code')]:
    try:
        cur.execute(f"SELECT {col}, COUNT(*) c FROM {table} WHERE {col} IS NOT NULL AND TRIM({col})<>'' GROUP BY {col} ORDER BY c DESC LIMIT 20")
        rows=cur.fetchall()
        print(table, rows[:10])
    except Exception as e:
        print(table, 'ERR', e)

cur.execute("""
SELECT COUNT(*) FROM allocations
WHERE LOWER(COALESCE(allocation_source_scope,supply_level,''))='state'
  AND COALESCE(origin_state_code,'') <> ''
  AND COALESCE(state_code,'') <> ''
  AND origin_state_code <> state_code
""")
print('GLOBAL_INTERSTATE_STATE_ALLOC_ROWS', cur.fetchone()[0])

conn.close()
