BEGIN IMMEDIATE;

CREATE UNIQUE INDEX IF NOT EXISTS media_assets_key_owner ON media_assets(asset_key, owner_id);

CREATE TABLE IF NOT EXISTS profile_media (
    author_id TEXT NOT NULL,
    context_id TEXT NOT NULL,
    asset_key TEXT NOT NULL,
    PRIMARY KEY (author_id, context_id),
    FOREIGN KEY (author_id, context_id)
        REFERENCES profile_variants(author_id, context_id) ON DELETE CASCADE,
    FOREIGN KEY (asset_key, author_id)
        REFERENCES media_assets(asset_key, owner_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS profile_media_by_asset ON profile_media(asset_key);

PRAGMA user_version = 4;
COMMIT;
