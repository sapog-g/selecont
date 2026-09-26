BEGIN IMMEDIATE;

CREATE TABLE credentials (
    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    password_hash TEXT NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    CHECK (expires_at > created_at)
);
CREATE INDEX sessions_by_user ON sessions(user_id, expires_at);
CREATE INDEX sessions_by_expiry ON sessions(expires_at);

CREATE TABLE login_attempts (
    bucket_hash TEXT PRIMARY KEY,
    failures INTEGER NOT NULL CHECK (failures >= 0),
    window_started_at INTEGER NOT NULL,
    blocked_until INTEGER NOT NULL DEFAULT 0
);

PRAGMA user_version = 2;
COMMIT;
