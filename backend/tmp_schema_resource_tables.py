import sqlite3, json
con = sqlite3.connect('backend.db')
cur = con.cursor()
# all tables
all_tables = [r[0] for r in cur.execute("select name from sqlite_master where type='table' order by name").fetchall()]
# detect tables with resource_id and numeric qty-like columns
out=[]
for t in all_tables:
    cols = cur.execute(f"pragma table_info({t})").fetchall()
    col_names=[c[1] for c in cols]
    if 'resource_id' in col_names:
        qty_cols=[c[1] for c in cols if any(k in c[1].lower() for k in ['quantity','stock','demand']) and c[1].lower() not in ['resource_id']]
        out.append({'table':t,'cols':col_names,'qty_cols':qty_cols})
print(json.dumps(out, indent=2))
