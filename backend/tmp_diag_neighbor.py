import sqlite3

con = sqlite3.connect('backend.db')
cur = con.cursor()

queries = [
    ('mutual_aid_requests', "select count(1) from mutual_aid_requests"),
    ('mutual_aid_offers', "select count(1) from mutual_aid_offers"),
    ('offers_accepted', "select count(1) from mutual_aid_offers where status='accepted'"),
    ('state_transfers_aid', "select count(1) from state_transfers where transfer_kind='aid'"),
    ('state_transfers_unconsumed', "select count(1) from state_transfers where transfer_kind='aid' and consumed_in_run_id is null"),
    ('alloc_neighbor', "select count(1) from allocations where lower(coalesce(allocation_source_scope,''))='neighbor_state'"),
    ('alloc_state', "select count(1) from allocations where lower(coalesce(allocation_source_scope,''))='state'"),
]

for name, sql in queries:
    print(name, cur.execute(sql).fetchone()[0])

rows = cur.execute(
    "select event_type, count(1) from audit_logs "
    "where event_type in ('AUTO_NEIGHBOR_OFFERS_SEEDED','AUTO_ESCALATED_TO_NATIONAL','AUTO_ESCALATED_TO_STATE_MARKET') "
    "group by event_type"
).fetchall()
print('audit', rows)

con.close()
