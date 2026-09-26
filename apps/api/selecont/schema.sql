BEGIN IMMEDIATE;

CREATE TABLE users (
    id TEXT PRIMARY KEY,
    handle TEXT NOT NULL UNIQUE
);

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

CREATE TABLE contexts (
    id TEXT PRIMARY KEY,
    author_id TEXT NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('public', 'private')),
    UNIQUE (author_id, id)
);
CREATE UNIQUE INDEX one_public_context ON contexts(author_id) WHERE kind = 'public';

CREATE TABLE profile_variants (
    author_id TEXT NOT NULL,
    context_id TEXT NOT NULL,
    bio TEXT NOT NULL DEFAULT '',
    avatar_key TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (author_id, context_id),
    FOREIGN KEY (author_id, context_id) REFERENCES contexts(author_id, id)
);

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
CREATE UNIQUE INDEX media_assets_key_owner ON media_assets(asset_key, owner_id);

CREATE TABLE profile_media (
    author_id TEXT NOT NULL,
    context_id TEXT NOT NULL,
    asset_key TEXT NOT NULL,
    PRIMARY KEY (author_id, context_id),
    FOREIGN KEY (author_id, context_id)
        REFERENCES profile_variants(author_id, context_id) ON DELETE CASCADE,
    FOREIGN KEY (asset_key, author_id)
        REFERENCES media_assets(asset_key, owner_id) ON DELETE CASCADE
);
CREATE INDEX profile_media_by_asset ON profile_media(asset_key);

CREATE TABLE follows (
    author_id TEXT NOT NULL REFERENCES users(id),
    follower_id TEXT NOT NULL REFERENCES users(id),
    PRIMARY KEY (author_id, follower_id),
    CHECK (author_id <> follower_id)
);

CREATE TABLE memberships (
    author_id TEXT NOT NULL,
    follower_id TEXT NOT NULL,
    context_id TEXT NOT NULL,
    PRIMARY KEY (author_id, follower_id),
    FOREIGN KEY (author_id, follower_id) REFERENCES follows(author_id, follower_id) ON DELETE CASCADE,
    FOREIGN KEY (author_id, context_id) REFERENCES contexts(author_id, id)
);
CREATE TRIGGER membership_requires_private_insert BEFORE INSERT ON memberships
WHEN NOT EXISTS (SELECT 1 FROM contexts WHERE id = NEW.context_id AND kind = 'private')
BEGIN SELECT RAISE(ABORT, 'membership requires private context'); END;
CREATE TRIGGER membership_requires_private_update BEFORE UPDATE ON memberships
WHEN NOT EXISTS (SELECT 1 FROM contexts WHERE id = NEW.context_id AND kind = 'private')
BEGIN SELECT RAISE(ABORT, 'membership requires private context'); END;

CREATE TABLE posts (
    id TEXT PRIMARY KEY,
    author_id TEXT NOT NULL REFERENCES users(id),
    body TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (author_id, id)
);

CREATE TABLE post_audiences (
    author_id TEXT NOT NULL,
    post_id TEXT NOT NULL,
    context_id TEXT NOT NULL,
    PRIMARY KEY (post_id, context_id),
    FOREIGN KEY (author_id, post_id) REFERENCES posts(author_id, id) ON DELETE CASCADE,
    FOREIGN KEY (author_id, context_id) REFERENCES contexts(author_id, id)
);

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

CREATE TABLE comments (
    id TEXT PRIMARY KEY,
    post_id TEXT NOT NULL,
    context_id TEXT NOT NULL,
    commenter_id TEXT NOT NULL REFERENCES users(id),
    body TEXT NOT NULL,
    parent_id TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    deleted_at TEXT,
    UNIQUE (id, post_id, context_id),
    FOREIGN KEY (post_id, context_id) REFERENCES post_audiences(post_id, context_id) ON DELETE CASCADE,
    FOREIGN KEY (parent_id, post_id, context_id) REFERENCES comments(id, post_id, context_id) ON DELETE CASCADE
);
CREATE INDEX comments_by_thread ON comments(post_id, context_id, created_at, id);
CREATE INDEX comments_by_parent ON comments(parent_id, post_id, context_id);

CREATE TABLE reactions (
    post_id TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES users(id),
    PRIMARY KEY (post_id, user_id),
    FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE
);

PRAGMA user_version = 7;
COMMIT;
