import sqlite3

DB_PATH = r"C:/Users/LATHEEF/Desktop/disaster_management/backend/backend.db"

con = sqlite3.connect(DB_PATH)
cur = con.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
names = [row[0] for row in cur.fetchall()]
print(f"TABLES {len(names)}")
for name in names:
    print(name)
