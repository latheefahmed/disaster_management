import hashlib
import sqlite3

conn = sqlite3.connect("backend.db")
cur = conn.cursor()

district_hash = hashlib.sha256("district123".encode()).hexdigest()
state_hash = hashlib.sha256("state123".encode()).hexdigest()

cur.execute("UPDATE users SET password_hash=? WHERE username LIKE 'district_%'", (district_hash,))
district_count = cur.rowcount
cur.execute("UPDATE users SET password_hash=? WHERE username LIKE 'state_%'", (state_hash,))
state_count = cur.rowcount

conn.commit()
conn.close()

print(f"UPDATED_DISTRICT {district_count}")
print(f"UPDATED_STATE {state_count}")
