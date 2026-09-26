BEGIN IMMEDIATE;

ALTER TABLE comments ADD COLUMN deleted_at TEXT;

PRAGMA user_version = 7;
COMMIT;
