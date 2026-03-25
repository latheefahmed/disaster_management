import sqlite3
conn=sqlite3.connect('backend.db')
cur=conn.cursor()
print('TABLES_WITH_STOCK', [r[0] for r in cur.execute("select name from sqlite_master where type='table' and name like '%stock%' order by 1").fetchall()])
print('REQUESTS_COLS', cur.execute('pragma table_info(requests)').fetchall())
print('RESOURCE_REQUESTS_COLS', cur.execute('pragma table_info(resource_requests)').fetchall() if cur.execute("select count(*) from sqlite_master where type='table' and name='resource_requests'").fetchone()[0] else 'NO')
conn.close()
