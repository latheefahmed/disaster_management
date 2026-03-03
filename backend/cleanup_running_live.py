import sqlite3

con = sqlite3.connect("backend.db")
cur = con.cursor()
cur.execute("UPDATE solver_runs SET status='failed' WHERE mode='live' AND status='running'")
con.commit()
print("updated", cur.rowcount)
con.close()
