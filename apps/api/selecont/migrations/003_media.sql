BEGIN IMMEDIATE;

CREATE TABLE media_assets (
    asset_key TEXT PRIMARY KEY
        CHECK (length(asset_key) BETWEEN 32 AND 80)
        CHECK (asset_key NOT GLOB '*[^A-Za-z0-9_-]*'),
    owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    storage_name TEXT NOT NULL UNIQUE
        CHECK (length(storage_name) BETWEEN 37 AND 85)
        CHECK (storage_name NOT GLOB '*[^A-Za-z0-9_.-]*'),
    content_type TEXT NOT NULL CHECK (content_type = 'image/webp'),
    byte_size INTEGER NOT NULL CHECK (byte_size > 0),
    width INTEGER NOT NULL CHECK (width > 0),
    height INTEGER NOT NULL CHECK (height > 0),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'attached')),
    created_at INTEGER NOT NULL
);
CREATE INDEX media_assets_by_owner ON media_assets(owner_id, status, created_at);

PRAGMA user_version = 3;
COMMIT;
