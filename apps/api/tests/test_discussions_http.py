"""T06 HTTP/UI checks for isolated nested discussions and global reactions."""

from pathlib import Path
import re
import shutil
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from selecont.core import Store
from selecont.operator import seed_demo
from selecont.web import Settings, create_app


PASSWORD = "correct horse battery staple"
SECRET = b"t06-test-secret-at-least-32-bytes"


def hidden(html, name):
    match = re.search(rf'name="{re.escape(name)}" value="([^"]*)"', html)
    if not match:
        raise AssertionError(f"Missing hidden field {name}")
    return match.group(1)


class DiscussionHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template_dir = tempfile.TemporaryDirectory()
        cls.template = Path(cls.template_dir.name) / "template.sqlite3"
        seed_demo(cls.template, PASSWORD)

    @classmethod
    def tearDownClass(cls):
        cls.template_dir.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.database = self.base / "selecont.sqlite3"
        shutil.copyfile(self.template, self.database)
        self.settings = Settings(
            self.database,
            SECRET,
            cookie_secure=False,
            media_root=self.base / "private-media",
        )
        self.app = create_app(self.settings)
        self.clients = []

        store = Store(self.database)
        try:
            self.ids = {
                handle: store.user_id_for_handle(handle)
                for handle in ("grigory", "friend", "family", "stranger")
            }
            self.contexts = {
                row["name"]: row["id"]
                for row in store.author_contexts(self.ids["grigory"], self.ids["grigory"])
            }
            self.public_private = store.publish(
                self.ids["grigory"],
                "Public and friends",
                [self.contexts["Public"], self.contexts["Friends"]],
            )
            self.shared_private = store.publish(
                self.ids["grigory"],
                "Shared private post",
                [self.contexts["Friends"], self.contexts["Family"]],
            )
            self.friends_only = store.publish(
                self.ids["grigory"], "Friends only", [self.contexts["Friends"]]
            )
            self.other_post = store.publish(
                self.ids["grigory"], "Other", [self.contexts["Friends"]]
            )
        finally:
            store.close()

    def tearDown(self):
        for client in reversed(self.clients):
            client.__exit__(None, None, None)
        self.temp.cleanup()

    def client(self, handle=None):
        client = TestClient(self.app, base_url="http://testserver")
        client.__enter__()
        self.clients.append(client)
        if handle:
            page = client.get("/login")
            response = client.post(
                "/login",
                data={
                    "username": handle,
                    "password": PASSWORD,
                    "csrf": hidden(page.text, "csrf"),
                    "next": "/u/grigory",
                },
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 303)
        return client

    def comment(self, client, post_id, body, *, thread=None, audience=None, parent=None):
        query = f"thread={thread}" if thread else f"audience={audience}"
        page = client.get(f"/p/{post_id}?{query}")
        data = {"csrf": hidden(page.text, "csrf"), "body": body}
        if thread:
            data["thread"] = thread
        else:
            data["audience"] = audience
        if parent:
            data["parent_id"] = parent
        return client.post(
            f"/p/{post_id}/comments", data=data, follow_redirects=False
        )

    def comment_id(self, body):
        with sqlite3.connect(self.database) as db:
            return db.execute("SELECT id FROM comments WHERE body = ?", (body,)).fetchone()[0]

    def csrf(self, client, path):
        return hidden(client.get(path).text, "csrf")

    def test_general_and_for_you_are_explicit_and_private_defaults_safer(self):
        friend = self.client("friend")
        family = self.client("family")
        anonymous = self.client()

        page = friend.get(f"/p/{self.public_private}")
        self.assertEqual(page.status_code, 200)
        self.assertIn("General", page.text)
        self.assertIn("Комментарии · For you", page.text)
        self.assertIn('name="thread" value="private"', page.text)
        self.assertNotIn("Это отдельный разговор твоего текущего круга", page.text)
        self.assertNotIn("Названия других скрытых кругов", page.text)

        private = self.comment(
            friend, self.public_private, "only our side", thread="private"
        )
        public = self.comment(
            friend,
            self.public_private,
            "<script>public message</script>",
            thread="public",
        )
        self.assertEqual(private.status_code, 303)
        self.assertEqual(public.status_code, 303)

        public_page = anonymous.get(f"/p/{self.public_private}?thread=public")
        self.assertIn("&lt;script&gt;public message&lt;/script&gt;", public_page.text)
        self.assertNotIn("<script>public message</script>", public_page.text)
        self.assertNotIn("only our side", public_page.text)
        self.assertNotIn("For you", public_page.text)
        self.assertNotIn("Friends", public_page.text)
        self.assertNotIn(self.contexts["Friends"], public_page.text)

        family_page = family.get(f"/p/{self.public_private}")
        self.assertIn("Комментарии · General", family_page.text)
        self.assertNotIn("For you", family_page.text)
        friends_only = friend.get(f"/p/{self.friends_only}")
        self.assertIn("Комментарии · For you", friends_only.text)
        self.assertNotIn("General", friends_only.text)

    def test_nested_replies_cross_thread_parent_and_tombstone_deletion(self):
        author = self.client("grigory")
        friend = self.client("friend")
        family = self.client("family")

        self.assertEqual(
            self.comment(friend, self.shared_private, "root", thread="private").status_code,
            303,
        )
        root = self.comment_id("root")
        self.assertEqual(
            self.comment(
                author,
                self.shared_private,
                "author reply",
                audience=self.contexts["Friends"],
                parent=root,
            ).status_code,
            303,
        )
        child = self.comment_id("author reply")
        self.assertEqual(
            self.comment(
                friend,
                self.shared_private,
                "grandchild",
                thread="private",
                parent=child,
            ).status_code,
            303,
        )
        self.comment(friend, self.shared_private, "sibling", thread="private")

        self.comment(family, self.shared_private, "family root", thread="private")
        family_parent = self.comment_id("family root")
        denied_context = self.comment(
            friend,
            self.shared_private,
            "context attack",
            thread="private",
            parent=family_parent,
        )
        self.assertEqual(denied_context.status_code, 404)
        self.comment(friend, self.other_post, "other parent", thread="private")
        other_parent = self.comment_id("other parent")
        denied_post = self.comment(
            friend,
            self.shared_private,
            "post attack",
            thread="private",
            parent=other_parent,
        )
        self.assertEqual(denied_post.status_code, 404)

        delete_denied = family.post(
            f"/comments/{root}/delete",
            data={"csrf": self.csrf(family, f"/p/{self.shared_private}")},
            follow_redirects=False,
        )
        self.assertEqual(delete_denied.status_code, 404)
        deleted = friend.post(
            f"/comments/{root}/delete",
            data={"csrf": self.csrf(friend, f"/p/{self.shared_private}")},
            follow_redirects=False,
        )
        self.assertEqual(deleted.status_code, 303)
        page = friend.get(f"/p/{self.shared_private}")
        self.assertNotIn("<p>root</p>", page.text)
        self.assertIn("Комментарий удалён", page.text)
        self.assertNotIn("Ответы сохранены, чтобы разговор не потерял смысл.", page.text)
        self.assertIn("<p>author reply</p>", page.text)
        self.assertIn("<p>grandchild</p>", page.text)
        self.assertIn("<p>sibling</p>", page.text)
        self.assertEqual(
            friend.post(
                f"/comments/{root}/delete",
                data={"csrf": self.csrf(friend, f"/p/{self.shared_private}")},
            ).status_code,
            404,
        )

        moderated = author.post(
            f"/comments/{family_parent}/delete",
            data={
                "csrf": self.csrf(
                    author,
                    f"/p/{self.shared_private}?audience={self.contexts['Family']}",
                )
            },
            follow_redirects=False,
        )
        self.assertEqual(moderated.status_code, 303)
        self.assertIn(
            "Комментарий удалён",
            family.get(f"/p/{self.shared_private}").text,
        )

    def test_one_global_like_per_person_and_author_only_breakdown(self):
        author = self.client("grigory")
        friend = self.client("friend")
        family = self.client("family")

        for client in (friend, friend, family):
            response = client.post(
                f"/p/{self.shared_private}/reaction",
                data={
                    "csrf": self.csrf(client, f"/p/{self.shared_private}"),
                    "thread": "private",
                    "active": "1",
                },
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 303)

        friend_page = friend.get(f"/p/{self.shared_private}")
        family_page = family.get(f"/p/{self.shared_private}")
        for page in (friend_page, family_page):
            self.assertIn("Лайков: 2", page.text)
            self.assertNotIn("Кто поставил лайк", page.text)
            self.assertNotIn("Friends", page.text)
            self.assertNotIn("Family", page.text)

        author_page = author.get(
            f"/p/{self.shared_private}?audience={self.contexts['Friends']}"
        )
        self.assertIn("Лайков: 2", author_page.text)
        self.assertIn("Кто поставил лайк", author_page.text)
        self.assertIn("@friend · Friends", author_page.text)
        self.assertIn("@family · Family", author_page.text)

    def test_revoke_blocks_old_private_page_and_all_known_write_paths(self):
        friend = self.client("friend")
        response = self.comment(
            friend, self.shared_private, "before revoke", thread="private"
        )
        self.assertEqual(response.status_code, 303)
        comment_id = self.comment_id("before revoke")
        csrf = self.csrf(friend, f"/p/{self.shared_private}")

        store = Store(self.database)
        try:
            store.revoke(self.ids["grigory"], self.ids["friend"])
        finally:
            store.close()

        self.assertEqual(
            friend.get(f"/p/{self.shared_private}?thread=private").status_code, 404
        )
        self.assertEqual(
            friend.post(
                f"/p/{self.shared_private}/comments",
                data={"csrf": csrf, "thread": "private", "body": "late"},
            ).status_code,
            404,
        )
        self.assertEqual(
            friend.post(
                f"/p/{self.shared_private}/reaction",
                data={"csrf": csrf, "thread": "private", "active": "1"},
            ).status_code,
            404,
        )
        self.assertEqual(
            friend.post(
                f"/comments/{comment_id}/delete", data={"csrf": csrf}
            ).status_code,
            404,
        )
        self.assertEqual(friend.get(f"/p/{self.public_private}?thread=public").status_code, 200)

    def test_anonymous_csrf_and_author_context_injection_are_rejected(self):
        anonymous = self.client()
        friend = self.client("friend")
        self.assertEqual(
            anonymous.post(
                f"/p/{self.public_private}/comments",
                data={"thread": "public", "body": "anonymous"},
            ).status_code,
            401,
        )
        self.assertEqual(
            anonymous.post(
                f"/p/{self.public_private}/reaction",
                data={"thread": "public", "active": "1"},
            ).status_code,
            401,
        )
        self.assertEqual(
            friend.post(
                f"/p/{self.public_private}/comments",
                data={"thread": "private", "body": "no csrf"},
            ).status_code,
            403,
        )
        csrf = self.csrf(friend, f"/p/{self.public_private}")
        self.assertEqual(
            friend.post(
                f"/p/{self.public_private}/comments",
                data={
                    "csrf": csrf,
                    "audience": self.contexts["Friends"],
                    "body": "injected author route",
                },
            ).status_code,
            404,
        )
        injected_reaction = friend.post(
            f"/p/{self.public_private}/reaction",
            data={
                "csrf": csrf,
                "audience": self.contexts["Friends"],
                "active": "1",
            },
        )
        self.assertEqual(injected_reaction.status_code, 404)
        duplicate_branch = friend.post(
            f"/p/{self.public_private}/reaction",
            data={
                "csrf": csrf,
                "thread": "private",
                "audience": self.contexts["Friends"],
                "active": "1",
            },
        )
        self.assertEqual(duplicate_branch.status_code, 400)
        with sqlite3.connect(self.database) as db:
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM reactions WHERE post_id = ?",
                    (self.public_private,),
                ).fetchone()[0],
                0,
            )


class GlobalReactionMigrationTests(unittest.TestCase):
    def test_v5_reactions_collapse_to_one_per_person_and_post(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "migration.sqlite3"
            ids = seed_demo(database, PASSWORD)
            store = Store(database)
            try:
                contexts = {
                    row["name"]: row["id"]
                    for row in store.author_contexts(ids["grigory"], ids["grigory"])
                }
                post_id = store.publish(
                    ids["grigory"],
                    "Old post",
                    [contexts["Public"], contexts["Friends"]],
                )
                store.db.executescript(
                    "DROP TABLE reactions;"
                    "CREATE TABLE reactions("
                    "post_id TEXT NOT NULL, context_id TEXT NOT NULL, user_id TEXT NOT NULL,"
                    "PRIMARY KEY(post_id, context_id, user_id),"
                    "FOREIGN KEY(post_id, context_id) REFERENCES post_audiences(post_id, context_id) ON DELETE CASCADE);"
                    "PRAGMA user_version = 5;"
                )
                store.db.executemany(
                    "INSERT INTO reactions VALUES (?, ?, ?)",
                    [
                        (post_id, contexts["Public"], ids["friend"]),
                        (post_id, contexts["Friends"], ids["friend"]),
                    ],
                )
                store.migrate()
                self.assertEqual(store.db.execute("PRAGMA user_version").fetchone()[0], 7)
                self.assertEqual(
                    store.db.execute(
                        "SELECT COUNT(*) FROM reactions WHERE post_id = ?", (post_id,)
                    ).fetchone()[0],
                    1,
                )
                self.assertEqual(store.db.execute("PRAGMA foreign_key_check").fetchall(), [])
            finally:
                store.close()


class CommentTombstoneMigrationTests(unittest.TestCase):
    def test_v6_comments_gain_tombstones_without_losing_history(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "migration.sqlite3"
            ids = seed_demo(database, PASSWORD)
            store = Store(database)
            try:
                contexts = {
                    row["name"]: row["id"]
                    for row in store.author_contexts(ids["grigory"], ids["grigory"])
                }
                post_id = store.publish(
                    ids["grigory"], "Existing post", [contexts["Friends"]]
                )
                comment_id = store.add_comment(
                    ids["friend"], post_id, "Existing comment", channel="private"
                )
                store.db.execute("ALTER TABLE comments DROP COLUMN deleted_at")
                store.db.execute("PRAGMA user_version = 6")
            finally:
                store.close()

            upgraded = Store(database)
            try:
                upgraded.migrate()
                self.assertEqual(upgraded.db.execute("PRAGMA user_version").fetchone()[0], 7)
                columns = {
                    row["name"] for row in upgraded.db.execute("PRAGMA table_info(comments)")
                }
                self.assertIn("deleted_at", columns)
                [comment] = upgraded.thread(post_id, ids["friend"], channel="private")["comments"]
                self.assertEqual(comment["id"], comment_id)
                self.assertEqual(comment["body"], "Existing comment")
                self.assertIsNone(comment["deleted_at"])
                self.assertEqual(upgraded.db.execute("PRAGMA foreign_key_check").fetchall(), [])
            finally:
                upgraded.close()


if __name__ == "__main__":
    unittest.main()
