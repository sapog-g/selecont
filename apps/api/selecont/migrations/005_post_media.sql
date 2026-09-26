BEGIN IMMEDIATE;

CREATE TABLE post_media (
    author_id TEXT NOT NULL,
    post_id TEXT NOT NULL,
    asset_key TEXT NOT NULL,
    PRIMARY KEY (post_id),
    UNIQUE (asset_key),
    FOREIGN KEY (author_id, post_id)
        REFERENCES posts(author_id, id) ON DELETE CASCADE,
    FOREIGN KEY (asset_key, author_id)
        REFERENCES media_assets(asset_key, owner_id) ON DELETE CASCADE
);
CREATE INDEX post_media_by_asset ON post_media(asset_key);

PRAGMA user_version = 5;
COMMIT;
