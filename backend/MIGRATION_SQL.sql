-- Disaster management hardening migration (SQLite-compatible)

BEGIN TRANSACTION;

-- requests safeguards
ALTER TABLE requests ADD COLUMN priority INTEGER DEFAULT 1;
ALTER TABLE requests ADD COLUMN urgency INTEGER DEFAULT 1;
ALTER TABLE requests ADD COLUMN confidence REAL DEFAULT 1.0;
ALTER TABLE requests ADD COLUMN source TEXT DEFAULT 'human';

-- allocations lifecycle fields
ALTER TABLE allocations ADD COLUMN claimed_quantity REAL NOT NULL DEFAULT 0.0;
ALTER TABLE allocations ADD COLUMN consumed_quantity REAL NOT NULL DEFAULT 0.0;
ALTER TABLE allocations ADD COLUMN returned_quantity REAL NOT NULL DEFAULT 0.0;
ALTER TABLE allocations ADD COLUMN status TEXT NOT NULL DEFAULT 'allocated';

-- claims run scoping + metadata
ALTER TABLE claims ADD COLUMN solver_run_id INTEGER NOT NULL DEFAULT 0;
ALTER TABLE claims ADD COLUMN claimed_by TEXT NOT NULL DEFAULT 'district_manager';
ALTER TABLE claims ADD COLUMN created_at DATETIME;

-- consumptions run scoping + metadata
ALTER TABLE consumptions ADD COLUMN solver_run_id INTEGER NOT NULL DEFAULT 0;
ALTER TABLE consumptions ADD COLUMN created_at DATETIME;

-- returns run scoping + metadata
ALTER TABLE returns ADD COLUMN solver_run_id INTEGER NOT NULL DEFAULT 0;
ALTER TABLE returns ADD COLUMN reason TEXT NOT NULL DEFAULT 'manual';
ALTER TABLE returns ADD COLUMN created_at DATETIME;

-- audit normalization fields
ALTER TABLE audit_logs ADD COLUMN user_id TEXT;
ALTER TABLE audit_logs ADD COLUMN action TEXT;
ALTER TABLE audit_logs ADD COLUMN entity_type TEXT;
ALTER TABLE audit_logs ADD COLUMN entity_id TEXT;
ALTER TABLE audit_logs ADD COLUMN [before] JSON;
ALTER TABLE audit_logs ADD COLUMN [after] JSON;

-- helpful indexes
CREATE INDEX IF NOT EXISTS idx_allocations_run_district_resource_time
ON allocations(solver_run_id, district_code, resource_id, time);

CREATE INDEX IF NOT EXISTS idx_claims_run_district_resource_time
ON claims(solver_run_id, district_code, resource_id, time);

CREATE INDEX IF NOT EXISTS idx_consumptions_run_district_resource_time
ON consumptions(solver_run_id, district_code, resource_id, time);

CREATE INDEX IF NOT EXISTS idx_returns_run_district_resource_time
ON returns(solver_run_id, district_code, resource_id, time);

CREATE INDEX IF NOT EXISTS idx_requests_state_status
ON requests(state_code, status);

-- canonical resource cleanup
ALTER TABLE resources ADD COLUMN unit TEXT;

UPDATE requests SET resource_id='R2' WHERE LOWER(TRIM(resource_id)) IN ('water','water_liters');
UPDATE requests SET resource_id='R1' WHERE LOWER(TRIM(resource_id)) IN ('food','food_packets');
DELETE FROM requests WHERE UPPER(TRIM(resource_id)) IN ('R99','T99');

UPDATE allocations SET resource_id='R2' WHERE LOWER(TRIM(resource_id)) IN ('water','water_liters');
UPDATE allocations SET resource_id='R1' WHERE LOWER(TRIM(resource_id)) IN ('food','food_packets');
DELETE FROM allocations WHERE UPPER(TRIM(resource_id)) IN ('R99','T99');

UPDATE claims SET resource_id='R2' WHERE LOWER(TRIM(resource_id)) IN ('water','water_liters');
UPDATE claims SET resource_id='R1' WHERE LOWER(TRIM(resource_id)) IN ('food','food_packets');
DELETE FROM claims WHERE UPPER(TRIM(resource_id)) IN ('R99','T99');

UPDATE consumptions SET resource_id='R2' WHERE LOWER(TRIM(resource_id)) IN ('water','water_liters');
UPDATE consumptions SET resource_id='R1' WHERE LOWER(TRIM(resource_id)) IN ('food','food_packets');
DELETE FROM consumptions WHERE UPPER(TRIM(resource_id)) IN ('R99','T99');

UPDATE returns SET resource_id='R2' WHERE LOWER(TRIM(resource_id)) IN ('water','water_liters');
UPDATE returns SET resource_id='R1' WHERE LOWER(TRIM(resource_id)) IN ('food','food_packets');
DELETE FROM returns WHERE UPPER(TRIM(resource_id)) IN ('R99','T99');

DELETE FROM resources WHERE UPPER(TRIM(resource_id)) IN ('R99','T99');
DELETE FROM resources WHERE resource_id NOT IN ('R1','R2','R3','R4','R5','R6','R7','R8','R9','R10','R11');

COMMIT;

-- NOTE:
-- SQLite cannot add foreign key constraints to existing tables via ALTER TABLE.
-- Foreign keys are enforced at ORM model level for new schema creations.
