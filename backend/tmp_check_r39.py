import sqlite3
con = sqlite3.connect('backend.db')
cur = con.cursor()
print('COLS', cur.execute("pragma table_info(resources)").fetchall())
print('R39', cur.execute("select * from resources where resource_id='R39'").fetchall())
