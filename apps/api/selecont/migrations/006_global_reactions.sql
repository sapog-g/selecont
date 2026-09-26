BEGIN IMMEDIATE;

ALTER TABLE reactions RENAME TO reactions_by_context_v5;

CREATE TABLE reactions (
    post_id TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES users(id),
    PRIMARY KEY (post_id, user_id),
    FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE
);

-- A person could previously react once in every audience. The selected MVP
-- model has one reaction per person and post, so existing duplicates collapse.
INSERT OR IGNORE INTO reactions(post_id, user_id)
SELECT post_id, user_id FROM reactions_by_context_v5;

DROP TABLE reactions_by_context_v5;

PRAGMA user_version = 6;
COMMIT;
