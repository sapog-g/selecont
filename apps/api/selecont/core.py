"""Persistent access-controlled domain service for the closed selecont demo.

actor_id/viewer_id MUST come from a trusted session in the HTTP adapter.
This module does not authenticate users and must not be exposed as a raw API.
Each Store is used by one request/thread. No permissions are cached in sessions.
"""

from contextlib import contextmanager
from pathlib import Path
import re
import sqlite3
from uuid import uuid4


class NotFound(Exception):
    """Missing and inaccessible resources intentionally have the same error."""


class AuthenticationRequired(Exception):
    pass


class InvalidInput(ValueError):
    pass


MAX_PRIVATE_CIRCLES = 20
MAX_COMMENT_DEPTH = 12
MAX_COMMENTS_PER_THREAD = 500


def _text(value, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise InvalidInput("Invalid text")
    return value.strip()


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path, isolation_level=None, timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")

    def close(self):
        self.db.close()

    def migrate(self):
        """Run on startup before serving requests. Refuse unknown schema versions."""
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            self.db.executescript(Path(__file__).with_name("schema.sql").read_text())
            return
        if version == 1:
            self.db.executescript(
                Path(__file__).with_name("migrations").joinpath("002_auth.sql").read_text()
            )
            version = 2
        if version == 2:
            self.db.executescript(
                Path(__file__).with_name("migrations").joinpath("003_media.sql").read_text()
            )
            version = 3
        if version == 3:
            self.db.executescript(
                Path(__file__).with_name("migrations").joinpath("004_profile_media.sql").read_text()
            )
            version = 4
        if version == 4:
            self.db.executescript(
                Path(__file__).with_name("migrations").joinpath("005_post_media.sql").read_text()
            )
            version = 5
        if version == 5:
            self.db.executescript(
                Path(__file__).with_name("migrations").joinpath("006_global_reactions.sql").read_text()
            )
            version = 6
        if version == 6:
            columns = {
                row["name"] for row in self.db.execute("PRAGMA table_info(comments)")
            }
            if "deleted_at" in columns:
                self.db.execute("PRAGMA user_version = 7")
            else:
                self.db.executescript(
                    Path(__file__).with_name("migrations").joinpath("007_comment_tombstones.sql").read_text()
                )
            version = 7
        if version != 7:
            raise RuntimeError("Unsupported database schema")

    @contextmanager
    def _transaction(self, write=False):
        # A revoke and a write cannot race past one another's membership check.
        self.db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def _user(self, user_id):
        if user_id is None:
            raise AuthenticationRequired()
        row = self.db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise NotFound()
        return row

    def _author(self, actor_id, author_id):
        self._user(actor_id)
        if actor_id != author_id:
            raise NotFound()

    def _context(self, author_id, context_id):
        row = self.db.execute(
            "SELECT * FROM contexts WHERE author_id = ? AND id = ?",
            (author_id, context_id),
        ).fetchone()
        if row is None:
            raise NotFound()
        return row

    def _public(self, author_id):
        row = self.db.execute(
            "SELECT id FROM contexts WHERE author_id = ? AND kind = 'public'", (author_id,)
        ).fetchone()
        if row is None:
            raise NotFound()
        return row[0]

    def _visible_contexts(self, author_id, viewer_id):
        public_id = self._public(author_id)
        if viewer_id is not None:
            self._user(viewer_id)
        membership = self.db.execute(
            "SELECT context_id FROM memberships WHERE author_id = ? AND follower_id = ?",
            (author_id, viewer_id),
        ).fetchone()
        return {"public": public_id, **({"private": membership[0]} if membership else {})}

    def _post(self, post_id):
        row = self.db.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
        if row is None:
            raise NotFound()
        return row

    def _post_channels(self, post, viewer_id):
        contexts = self._visible_contexts(post["author_id"], viewer_id)
        channels = [
            channel
            for channel, context_id in contexts.items()
            if self.db.execute(
                "SELECT 1 FROM post_audiences WHERE post_id = ? AND context_id = ?",
                (post["id"], context_id),
            ).fetchone()
        ]
        if not channels and viewer_id != post["author_id"]:
            raise NotFound()
        return channels

    def _thread_context(self, post_id, viewer_id, channel, author_context=None):
        post = self._post(post_id)
        if author_context is not None:
            self._author(viewer_id, post["author_id"])
            self._context(post["author_id"], author_context)
            context_id = author_context
        else:
            # Caller-selected opaque IDs are not accepted as viewer channels.
            contexts = self._visible_contexts(post["author_id"], viewer_id)
            context_id = contexts.get(channel)
        if context_id is None or self.db.execute(
            "SELECT 1 FROM post_audiences WHERE post_id = ? AND context_id = ?",
            (post_id, context_id),
        ).fetchone() is None:
            raise NotFound()
        return context_id

    def create_user(self, handle):
        """Operator-only provisioning; authentication is not implemented here."""
        if not isinstance(handle, str) or not re.fullmatch(r"[a-z0-9_]{3,30}", handle):
            raise InvalidInput("Invalid handle")
        user_id, public_id = str(uuid4()), str(uuid4())
        with self._transaction(write=True):
            self.db.execute("INSERT INTO users VALUES (?, ?)", (user_id, handle))
            self.db.execute("INSERT INTO contexts VALUES (?, ?, 'Public', 'public')", (public_id, user_id))
            self.db.execute(
                "INSERT INTO profile_variants(author_id, context_id) VALUES (?, ?)",
                (user_id, public_id),
            )
        return user_id

    def user_id_for_handle(self, handle):
        """Resolve the stable public handle without exposing other user data."""
        if not isinstance(handle, str) or not re.fullmatch(r"[a-z0-9_]{3,30}", handle):
            raise NotFound()
        row = self.db.execute("SELECT id FROM users WHERE handle = ?", (handle,)).fetchone()
        if row is None:
            raise NotFound()
        return row[0]

    def create_circle(self, actor_id, name):
        name = _text(name, 60)
        if any(ord(character) < 32 for character in name):
            raise InvalidInput("Invalid circle name")
        context_id = str(uuid4())
        with self._transaction(write=True):
            self._user(actor_id)
            private_names = [
                row[0]
                for row in self.db.execute(
                    "SELECT name FROM contexts WHERE author_id = ? AND kind = 'private'",
                    (actor_id,),
                )
            ]
            if len(private_names) >= MAX_PRIVATE_CIRCLES:
                raise InvalidInput("Private circle limit reached")
            if any(existing.casefold() == name.casefold() for existing in private_names):
                raise InvalidInput("Circle name already exists")
            public_id = self._public(actor_id)
            self.db.execute("INSERT INTO contexts VALUES (?, ?, ?, 'private')", (context_id, actor_id, name))
            self.db.execute(
                "INSERT INTO profile_variants SELECT author_id, ?, bio, avatar_key "
                "FROM profile_variants WHERE author_id = ? AND context_id = ?",
                (context_id, actor_id, public_id),
            )
            self.db.execute(
                "INSERT INTO profile_media(author_id, context_id, asset_key) "
                "SELECT author_id, ?, asset_key FROM profile_media "
                "WHERE author_id = ? AND context_id = ?",
                (context_id, actor_id, public_id),
            )
        return context_id

    def author_contexts(self, actor_id, author_id):
        with self._transaction():
            self._author(actor_id, author_id)
            return [dict(row) for row in self.db.execute(
                "SELECT id, name, kind FROM contexts WHERE author_id = ? ORDER BY kind, name, id", (author_id,)
            )]

    def set_profile(self, actor_id, context_id, *, bio, avatar_key=""):
        if not isinstance(bio, str) or len(bio) > 500:
            raise InvalidInput("Invalid bio")
        if not isinstance(avatar_key, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{0,80}", avatar_key):
            raise InvalidInput("Avatar must be a local asset key, not a URL")
        with self._transaction(write=True):
            self._user(actor_id)
            self._context(actor_id, context_id)
            self.db.execute(
                "UPDATE profile_variants SET bio = ?, avatar_key = ? WHERE author_id = ? AND context_id = ?",
                (bio, avatar_key, actor_id, context_id),
            )

    def set_profile_bio(self, actor_id, context_id, *, bio):
        """Update one owned variant without changing its attached photo."""
        if not isinstance(bio, str) or len(bio) > 500:
            raise InvalidInput("Bio must contain at most 500 characters")
        with self._transaction(write=True):
            self._user(actor_id)
            self._context(actor_id, context_id)
            self.db.execute(
                "UPDATE profile_variants SET bio = ? WHERE author_id = ? AND context_id = ?",
                (bio, actor_id, context_id),
            )

    def author_profile_variants(self, actor_id, author_id):
        """Return private profile-management data only to its author."""
        with self._transaction():
            self._author(actor_id, author_id)
            return [
                dict(row)
                for row in self.db.execute(
                    "SELECT c.id, c.name, c.kind, pv.bio, pm.asset_key "
                    "FROM contexts c "
                    "JOIN profile_variants pv ON pv.author_id = c.author_id AND pv.context_id = c.id "
                    "LEFT JOIN profile_media pm ON pm.author_id = c.author_id AND pm.context_id = c.id "
                    "WHERE c.author_id = ? "
                    "ORDER BY CASE c.kind WHEN 'public' THEN 0 ELSE 1 END, c.name COLLATE NOCASE, c.id",
                    (author_id,),
                )
            ]

    def _profile_projection(self, author_id, viewer_id, preview_context):
        if preview_context is not None:
            self._author(viewer_id, author_id)
            self._context(author_id, preview_context)
            context_id = preview_context
            channel = "preview"
        else:
            contexts = self._visible_contexts(author_id, viewer_id)
            channel = "private" if "private" in contexts else "public"
            context_id = contexts.get("private", contexts["public"])
        row = self.db.execute(
            "SELECT users.handle, profile_variants.bio, profile_variants.avatar_key "
            "FROM profile_variants JOIN users ON users.id = profile_variants.author_id "
            "WHERE author_id = ? AND context_id = ?", (author_id, context_id)
        ).fetchone()
        if row is None:
            raise NotFound()
        return dict(row), channel, context_id

    def profile(self, author_id, viewer_id=None, *, preview_context=None):
        with self._transaction():
            value, _, _ = self._profile_projection(author_id, viewer_id, preview_context)
            return value  # Never include context name, ID, or member list.

    def profile_with_channel(self, author_id, viewer_id=None):
        """Trusted HTTP projection; the symbolic channel matches the returned value."""
        with self._transaction():
            return self._profile_projection(author_id, viewer_id, None)

    def viewer_private_context(self, author_id, viewer_id):
        """Trusted-adapter helper. Never serialize the returned circle ID to a viewer."""
        with self._transaction():
            context_id = self._visible_contexts(author_id, viewer_id).get("private")
            if context_id is None:
                raise NotFound()
            return context_id

    def follow(self, actor_id, author_id):
        with self._transaction(write=True):
            self._user(actor_id)
            self._user(author_id)
            if actor_id == author_id:
                raise InvalidInput("Cannot follow yourself")
            self.db.execute("INSERT OR IGNORE INTO follows VALUES (?, ?)", (author_id, actor_id))

    def is_following(self, actor_id, author_id):
        with self._transaction():
            self._user(actor_id)
            self._user(author_id)
            return self.db.execute(
                "SELECT 1 FROM follows WHERE author_id = ? AND follower_id = ?",
                (author_id, actor_id),
            ).fetchone() is not None

    def unfollow(self, actor_id, author_id):
        with self._transaction(write=True):
            self._user(actor_id)
            self.db.execute("DELETE FROM follows WHERE author_id = ? AND follower_id = ?", (author_id, actor_id))

    def assign(self, actor_id, follower_id, context_id):
        with self._transaction(write=True):
            self._user(actor_id)
            context = self._context(actor_id, context_id)
            if context["kind"] != "private":
                raise InvalidInput("Public is not a membership circle")
            if self.db.execute("SELECT 1 FROM follows WHERE author_id = ? AND follower_id = ?",
                               (actor_id, follower_id)).fetchone() is None:
                raise NotFound()
            self.db.execute(
                "INSERT INTO memberships VALUES (?, ?, ?) ON CONFLICT(author_id, follower_id) "
                "DO UPDATE SET context_id = excluded.context_id", (actor_id, follower_id, context_id)
            )

    def revoke(self, actor_id, follower_id):
        with self._transaction(write=True):
            self._user(actor_id)
            self.db.execute("DELETE FROM memberships WHERE author_id = ? AND follower_id = ?",
                            (actor_id, follower_id))

    def author_followers(self, actor_id, author_id):
        """Return follower assignment metadata only to the profile author."""
        with self._transaction():
            self._author(actor_id, author_id)
            return [
                dict(row)
                for row in self.db.execute(
                    "SELECT u.id AS follower_id, u.handle, "
                    "m.context_id, c.name AS context_name "
                    "FROM follows f "
                    "JOIN users u ON u.id = f.follower_id "
                    "LEFT JOIN memberships m ON m.author_id = f.author_id AND m.follower_id = f.follower_id "
                    "LEFT JOIN contexts c ON c.author_id = m.author_id AND c.id = m.context_id "
                    "WHERE f.author_id = ? ORDER BY u.handle",
                    (author_id,),
                )
            ]

    def publish(self, actor_id, body, context_ids, *, photo_key=None):
        body = _text(body, 5000)
        if not isinstance(context_ids, (list, tuple)) or not context_ids or len(context_ids) > 20:
            raise InvalidInput("Choose at least one audience")
        if any(not isinstance(x, str) for x in context_ids):
            raise InvalidInput("Invalid audience")
        if len(set(context_ids)) != len(context_ids):
            raise InvalidInput("Choose each audience once")
        if photo_key is not None and not isinstance(photo_key, str):
            raise InvalidInput("Invalid photo")
        post_id = str(uuid4())
        with self._transaction(write=True):
            self._user(actor_id)
            for context_id in context_ids:
                self._context(actor_id, context_id)
            if photo_key is not None and self.db.execute(
                "SELECT 1 FROM media_assets "
                "WHERE asset_key = ? AND owner_id = ? AND status = 'pending'",
                (photo_key, actor_id),
            ).fetchone() is None:
                raise NotFound()
            self.db.execute("INSERT INTO posts(id, author_id, body) VALUES (?, ?, ?)", (post_id, actor_id, body))
            self.db.executemany("INSERT INTO post_audiences VALUES (?, ?, ?)",
                                [(actor_id, post_id, x) for x in context_ids])
            if photo_key is not None:
                self.db.execute(
                    "INSERT INTO post_media(author_id, post_id, asset_key) VALUES (?, ?, ?)",
                    (actor_id, post_id, photo_key),
                )
                self.db.execute(
                    "UPDATE media_assets SET status = 'attached' "
                    "WHERE asset_key = ? AND owner_id = ?",
                    (photo_key, actor_id),
                )
        return post_id

    def post(self, post_id, viewer_id=None):
        with self._transaction():
            post = self._post(post_id)
            channels = self._post_channels(post, viewer_id)
            handle = self.db.execute(
                "SELECT handle FROM users WHERE id = ?", (post["author_id"],)
            ).fetchone()["handle"]
            return {
                "id": post["id"],
                "body": post["body"],
                "created_at": post["created_at"],
                "channels": channels,
                "author_handle": handle,
            }

    def list_posts(self, author_id, viewer_id=None):
        with self._transaction():
            contexts = list(self._visible_contexts(author_id, viewer_id).values())
            placeholders = ",".join("?" for _ in contexts)
            return [dict(row) for row in self.db.execute(
                "SELECT DISTINCT p.id, p.body, p.created_at FROM posts p JOIN post_audiences a ON a.post_id = p.id "
                f"WHERE p.author_id = ? AND a.context_id IN ({placeholders}) ORDER BY p.created_at, p.id",
                (author_id, *contexts),
            )]

    def author_posts(self, actor_id, author_id):
        """Management projection; never return this through a viewer endpoint."""
        with self._transaction():
            self._author(actor_id, author_id)
            return [dict(row) for row in self.db.execute(
                "SELECT p.id, p.body, p.created_at, pm.asset_key FROM posts p "
                "LEFT JOIN post_media pm ON pm.post_id = p.id "
                "WHERE p.author_id = ? ORDER BY p.created_at DESC, p.id", (author_id,)
            )]

    def author_post(self, actor_id, post_id):
        with self._transaction():
            post = self._post(post_id)
            self._author(actor_id, post["author_id"])
            audiences = [dict(row) for row in self.db.execute(
                "SELECT c.id, c.name, c.kind FROM post_audiences a JOIN contexts c ON c.id = a.context_id "
                "WHERE a.post_id = ? ORDER BY c.kind, c.name, c.id", (post_id,)
            )]
            media = self.db.execute(
                "SELECT asset_key FROM post_media WHERE author_id = ? AND post_id = ?",
                (post["author_id"], post_id),
            ).fetchone()
            return {
                "id": post["id"],
                "body": post["body"],
                "created_at": post["created_at"],
                "asset_key": media["asset_key"] if media is not None else None,
                "audiences": audiences,
            }

    def post_photo_key(self, post_id, viewer_id=None):
        """Return the opaque photo key only after current post access succeeds."""
        with self._transaction():
            post = self._post(post_id)
            self._post_channels(post, viewer_id)
            row = self.db.execute(
                "SELECT asset_key FROM post_media WHERE post_id = ?", (post_id,)
            ).fetchone()
            return row["asset_key"] if row is not None else None

    def _thread_projection(self, post_id, context_id):
        comments = [dict(row) for row in self.db.execute(
            "SELECT c.id, c.commenter_id, u.handle, c.body, c.parent_id, c.deleted_at FROM comments c JOIN users u ON u.id = c.commenter_id "
            "WHERE c.post_id = ? AND c.context_id = ? ORDER BY c.created_at, c.id", (post_id, context_id)
        )]
        count = self.db.execute(
            "SELECT COUNT(*) FROM reactions WHERE post_id = ?", (post_id,)
        ).fetchone()[0]
        return {"comments": comments, "reaction_count": count}

    def thread(self, post_id, viewer_id=None, *, channel="public", author_context=None):
        with self._transaction():
            context_id = self._thread_context(post_id, viewer_id, channel, author_context)
            return self._thread_projection(post_id, context_id)

    def thread_with_context(self, post_id, viewer_id=None, *, channel="public"):
        """Trusted HTTP projection with the internal context used for access watching."""
        with self._transaction():
            context_id = self._thread_context(post_id, viewer_id, channel)
            return self._thread_projection(post_id, context_id), context_id

    def add_comment(self, actor_id, post_id, body, *, channel="public", author_context=None, parent_id=None):
        body = _text(body, 2000)
        comment_id = str(uuid4())
        with self._transaction(write=True):
            self._user(actor_id)
            context_id = self._thread_context(post_id, actor_id, channel, author_context)
            if parent_id is not None and (not isinstance(parent_id, str) or self.db.execute(
                "SELECT 1 FROM comments WHERE id = ? AND post_id = ? AND context_id = ? AND deleted_at IS NULL",
                (parent_id, post_id, context_id),
            ).fetchone() is None):
                raise NotFound()
            if parent_id is not None:
                depth = self.db.execute(
                    "WITH RECURSIVE ancestors(id, parent_id, depth) AS ("
                    "SELECT id, parent_id, 1 FROM comments WHERE id = ? AND post_id = ? AND context_id = ? "
                    "UNION ALL SELECT c.id, c.parent_id, a.depth + 1 FROM comments c "
                    "JOIN ancestors a ON c.id = a.parent_id WHERE c.post_id = ? AND c.context_id = ?) "
                    "SELECT MAX(depth) FROM ancestors",
                    (parent_id, post_id, context_id, post_id, context_id),
                ).fetchone()[0]
                if depth >= MAX_COMMENT_DEPTH:
                    raise InvalidInput("Reply nesting limit reached")
            count = self.db.execute(
                "SELECT COUNT(*) FROM comments WHERE post_id = ? AND context_id = ?",
                (post_id, context_id),
            ).fetchone()[0]
            if count >= MAX_COMMENTS_PER_THREAD:
                raise InvalidInput("This discussion has reached its comment limit")
            self.db.execute(
                "INSERT INTO comments(id, post_id, context_id, commenter_id, body, parent_id) VALUES (?, ?, ?, ?, ?, ?)",
                (comment_id, post_id, context_id, actor_id, body, parent_id),
            )
        return comment_id

    def react(self, actor_id, post_id, *, active=True):
        if not isinstance(active, bool):
            raise InvalidInput("active must be boolean")
        with self._transaction(write=True):
            self._user(actor_id)
            post = self._post(post_id)
            self._post_channels(post, actor_id)
            if active:
                self.db.execute(
                    "INSERT OR IGNORE INTO reactions(post_id, user_id) VALUES (?, ?)",
                    (post_id, actor_id),
                )
            else:
                self.db.execute(
                    "DELETE FROM reactions WHERE post_id = ? AND user_id = ?",
                    (post_id, actor_id),
                )

    def has_reacted(self, actor_id, post_id):
        with self._transaction():
            self._user(actor_id)
            post = self._post(post_id)
            self._post_channels(post, actor_id)
            return self.db.execute(
                "SELECT 1 FROM reactions WHERE post_id = ? AND user_id = ?",
                (post_id, actor_id),
            ).fetchone() is not None

    def author_reactions(self, actor_id, post_id):
        """Author-only reaction identities with each person's current assignment."""
        with self._transaction():
            post = self._post(post_id)
            self._author(actor_id, post["author_id"])
            return [dict(row) for row in self.db.execute(
                "SELECT u.handle, COALESCE(c.name, CASE WHEN r.user_id = ? "
                "THEN 'Author' ELSE 'No private circle' END) AS context_name, "
                "CASE WHEN c.id IS NULL THEN 'unassigned' ELSE 'private' END AS context_kind "
                "FROM reactions r JOIN users u ON u.id = r.user_id "
                "LEFT JOIN memberships m ON m.author_id = ? AND m.follower_id = r.user_id "
                "LEFT JOIN contexts c ON c.id = m.context_id AND c.author_id = ? "
                "WHERE r.post_id = ? ORDER BY context_kind, context_name, u.handle",
                (post["author_id"], post["author_id"], post["author_id"], post_id),
            )]

    def delete_comment(self, actor_id, comment_id):
        with self._transaction(write=True):
            self._user(actor_id)
            row = self.db.execute(
                "SELECT c.*, p.author_id FROM comments c JOIN posts p ON p.id = c.post_id "
                "WHERE c.id = ? AND c.deleted_at IS NULL",
                (comment_id,),
            ).fetchone()
            if row is None:
                raise NotFound()
            if actor_id != row["author_id"]:
                visible = self._visible_contexts(row["author_id"], actor_id)
                if actor_id != row["commenter_id"] or row["context_id"] not in visible.values():
                    raise NotFound()
                channel = next(
                    name for name, context_id in visible.items()
                    if context_id == row["context_id"]
                )
            else:
                channel = None
            self.db.execute(
                "UPDATE comments SET body = '', deleted_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE id = ?",
                (comment_id,),
            )
            return {
                "post_id": row["post_id"],
                "context_id": row["context_id"],
                "post_author_id": row["author_id"],
                "channel": channel,
            }

    def _delete_comment_tree(self, comment_id):
        """Delete leaves first inside the caller's write transaction.

        A single cascading DELETE hits SQLite's trigger recursion limit on
        deeply nested replies. Materialise the order before mutating the tree;
        each DELETE then has no descendants left to cascade into.
        """
        rows = self.db.execute(
            "WITH RECURSIVE tree(id, post_id, context_id, depth) AS ("
            "SELECT id, post_id, context_id, 0 FROM comments WHERE id = ? "
            "UNION ALL SELECT c.id, c.post_id, c.context_id, t.depth + 1 "
            "FROM comments c JOIN tree t ON c.parent_id = t.id "
            "AND c.post_id = t.post_id AND c.context_id = t.context_id) "
            "SELECT id FROM tree ORDER BY depth DESC", (comment_id,)
        ).fetchall()
        self.db.executemany("DELETE FROM comments WHERE id = ?", [(row[0],) for row in rows])

    def delete_post(self, actor_id, post_id):
        removed_storage = None
        with self._transaction(write=True):
            post = self._post(post_id)
            self._author(actor_id, post["author_id"])
            media = self.db.execute(
                "SELECT pm.asset_key, ma.storage_name FROM post_media pm "
                "JOIN media_assets ma ON ma.asset_key = pm.asset_key "
                "WHERE pm.author_id = ? AND pm.post_id = ?",
                (actor_id, post_id),
            ).fetchone()
            roots = self.db.execute(
                "SELECT id FROM comments WHERE post_id = ? AND parent_id IS NULL", (post_id,)
            ).fetchall()
            for root in roots:
                self._delete_comment_tree(root[0])
            self.db.execute("DELETE FROM posts WHERE id = ?", (post_id,))
            if media is not None:
                self.db.execute(
                    "DELETE FROM media_assets WHERE asset_key = ? AND owner_id = ?",
                    (media["asset_key"], actor_id),
                )
                removed_storage = media["storage_name"]
        return removed_storage
