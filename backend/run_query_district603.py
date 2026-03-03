import sqlite3

con = sqlite3.connect('backend.db')
cur = con.cursor()
row = cur.execute("SELECT district_code, state_code FROM districts WHERE district_code='603' LIMIT 1").fetchone()
print('DISTRICT_603', row)
if row is None:
    sample = cur.execute("SELECT district_code, state_code FROM districts ORDER BY district_code LIMIT 5").fetchall()
    print('DISTRICT_SAMPLES', sample)
con.close()
