import sqlite3, json
con=sqlite3.connect('backend.db')
cur=con.cursor()
# district populations availability
for t in ['districts','states','resources']:
    cols=[c[1] for c in cur.execute(f'pragma table_info({t})').fetchall()]
    print(t, cols)
print('sample districts', cur.execute("select * from districts limit 5").fetchall())
print('sample states', cur.execute("select * from states limit 5").fetchall())
print('sample resources', cur.execute("select resource_id, resource_name, unit from resources limit 20").fetchall())
