import sqlite3

conn = sqlite3.connect('backend.db')
cur = conn.cursor()
latest = cur.execute("""
select id
from solver_runs
where lower(coalesce(status,''))='completed'
  and lower(coalesce(mode,''))='live'
order by id desc
limit 1
""").fetchone()[0]
districts = cur.execute("select count(*) from districts").fetchone()[0]
resources = cur.execute("select count(*) from canonical_resources").fetchone()[0]
actual_rows = cur.execute("select count(*) from inventory_snapshots where solver_run_id=?", (latest,)).fetchone()[0]
nonzero_fail_rows = cur.execute("select count(*) from inventory_snapshots where solver_run_id=? and quantity < 1", (latest,)).fetchone()[0]
missing_pairs = (districts * resources) - actual_rows
print({
    'latest_run': latest,
    'districts': districts,
    'resources': resources,
    'expected_pairs': districts * resources,
    'actual_rows': actual_rows,
    'missing_pairs': missing_pairs,
    'nonzero_fail_rows': nonzero_fail_rows,
})
conn.close()
