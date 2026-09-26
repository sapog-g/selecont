"""T07 end-to-end acceptance and live access-revocation checks."""

from html import unescape
from io import BytesIO
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from PIL import Image

from selecont.core import Store
from selecont.operator import seed_demo
from selecont.web import Settings, create_app


PASSWORD = "correct horse battery staple"
SECRET = b"t07-acceptance-secret-at-least-32-bytes"


def hidden(html, name):
    match = re.search(rf'name="{re.escape(name)}" value="([^"]*)"', html)
    if not match:
        raise AssertionError(f"Missing hidden field {name}")
    return match.group(1)


def watch_url(html):
    match = re.search(r'data-access-check="([^"]+)"', html)
    return unescape(match.group(1)) if match else None


def post_photo_key(html):
    match = re.search(r'<img class="post-photo" src="/media/([A-Za-z0-9_-]+)"', html)
    if not match:
        raise AssertionError("Missing protected post photo")
    return match.group(1)


def image_bytes(color):
    image = Image.new("RGB", (48, 36), color)
    output = BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


class AcceptanceHTTPTests(unittest.TestCase):
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
        self.media_root = self.base / "private-media"
        shutil.copyfile(self.template, self.database)
        self.settings = Settings(
            self.database,
            SECRET,
            cookie_secure=False,
            media_root=self.media_root,
        )
        self.app = create_app(self.settings)
        self.clients = []
        store = Store(self.database)
        try:
            self.users = {
                handle: store.user_id_for_handle(handle)
                for handle in ("grigory", "friend", "family", "stranger")
            }
            self.contexts = {
                row["name"]: row["id"]
                for row in store.author_contexts(
                    self.users["grigory"], self.users["grigory"]
                )
            }
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

    def publish(self, author, body, audiences, color):
        page = author.get("/posts/new")
        response = author.post(
            "/posts",
            data={"csrf": hidden(page.text, "csrf"), "body": body, "audience": audiences},
            files={"photo": ("post.png", image_bytes(color), "image/png")},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303, response.text)
        return response.headers["location"].removeprefix("/p/")

    def comment(self, client, post_id, body, *, thread=None, audience=None, parent=None):
        query = f"thread={thread}" if thread else f"audience={audience}"
        page = client.get(f"/p/{post_id}?{query}")
        data = {"csrf": hidden(page.text, "csrf"), "body": body}
        data["thread" if thread else "audience"] = thread or audience
        if parent:
            data["parent_id"] = parent
        return client.post(
            f"/p/{post_id}/comments", data=data, follow_redirects=False
        )

    def comment_id(self, body):
        with sqlite3.connect(self.database) as db:
            return db.execute("SELECT id FROM comments WHERE body = ?", (body,)).fetchone()[0]

    def react(self, client, post_id, *, thread="private"):
        page = client.get(f"/p/{post_id}?thread={thread}")
        return client.post(
            f"/p/{post_id}/reaction",
            data={
                "csrf": hidden(page.text, "csrf"),
                "thread": thread,
                "active": "1",
            },
            follow_redirects=False,
        )

    def test_complete_private_demo_across_five_independent_sessions_and_restart(self):
        author = self.client("grigory")
        friend = self.client("friend")
        family = self.client("family")
        stranger = self.client("stranger")
        anonymous = self.client()

        shared = self.publish(
            author,
            "One post, two private conversations",
            [self.contexts["Friends"], self.contexts["Family"]],
            "navy",
        )
        public = self.publish(
            author, "Public demo post", [self.contexts["Public"]], "skyblue"
        )

        friend_page = friend.get(f"/p/{shared}")
        family_page = family.get(f"/p/{shared}")
        self.assertEqual(friend_page.status_code, 200)
        self.assertEqual(family_page.status_code, 200)
        self.assertEqual(friend_page.headers["cache-control"], "no-store")
        self.assertIn("script-src 'self'", friend_page.headers["content-security-policy"])
        key = post_photo_key(friend_page.text)
        self.assertEqual(key, post_photo_key(family_page.text))
        self.assertEqual(friend.get(f"/media/{key}").status_code, 200)
        self.assertEqual(family.get(f"/media/{key}").status_code, 200)
        for denied in (stranger, anonymous):
            unavailable = denied.get(f"/p/{shared}")
            self.assertEqual(unavailable.status_code, 404)
            self.assertEqual(unavailable.text, denied.get("/p/missing").text)
            self.assertEqual(denied.get(f"/media/{key}").status_code, 404)
        self.assertIn("Public demo post", anonymous.get(f"/p/{public}").text)

        self.assertEqual(
            self.comment(friend, shared, "friend root", thread="private").status_code,
            303,
        )
        friend_root = self.comment_id("friend root")
        self.assertEqual(
            self.comment(
                author,
                shared,
                "author in friends",
                audience=self.contexts["Friends"],
                parent=friend_root,
            ).status_code,
            303,
        )
        author_reply = self.comment_id("author in friends")
        self.assertEqual(
            self.comment(
                friend,
                shared,
                "friend grandchild",
                thread="private",
                parent=author_reply,
            ).status_code,
            303,
        )
        self.comment(friend, shared, "friend sibling", thread="private")
        self.comment(family, shared, "family root", thread="private")
        family_root = self.comment_id("family root")
        self.assertEqual(
            self.comment(
                friend,
                shared,
                "foreign parent attack",
                thread="private",
                parent=family_root,
            ).status_code,
            404,
        )
        self.assertEqual(
            friend.get(f"/p/{shared}?audience={self.contexts['Friends']}").status_code,
            404,
        )

        self.assertEqual(self.react(friend, shared).status_code, 303)
        self.assertEqual(self.react(family, shared).status_code, 303)
        self.assertIn("Лайков: 2", friend.get(f"/p/{shared}").text)
        self.assertIn("Лайков: 2", family.get(f"/p/{shared}").text)
        self.assertNotIn("family root", friend.get(f"/p/{shared}").text)
        self.assertNotIn("friend root", family.get(f"/p/{shared}").text)
        author_friends = author.get(
            f"/p/{shared}?audience={self.contexts['Friends']}"
        )
        author_family = author.get(
            f"/p/{shared}?audience={self.contexts['Family']}"
        )
        self.assertIn("friend root", author_friends.text)
        self.assertNotIn("family root", author_friends.text)
        self.assertIn("family root", author_family.text)
        self.assertIn("@friend · Friends", author_friends.text)
        self.assertIn("@family · Family", author_friends.text)

        deleted = friend.post(
            f"/comments/{friend_root}/delete",
            data={"csrf": hidden(friend.get(f"/p/{shared}").text, "csrf")},
            follow_redirects=False,
        )
        self.assertEqual(deleted.status_code, 303)
        remaining = friend.get(f"/p/{shared}").text
        self.assertNotIn("friend root", remaining)
        self.assertIn("Комментарий удалён", remaining)
        self.assertIn("author in friends", remaining)
        self.assertIn("friend grandchild", remaining)
        self.assertIn("friend sibling", remaining)

        self.comment(friend, shared, "open before revoke", thread="private")
        old_watch = watch_url(friend.get(f"/p/{shared}").text)
        self.assertEqual(friend.get(old_watch).status_code, 204)
        store = Store(self.database)
        try:
            store.revoke(self.users["grigory"], self.users["friend"])
        finally:
            store.close()
        self.assertEqual(friend.get(old_watch).status_code, 404)
        self.assertEqual(friend.get(f"/p/{shared}").status_code, 404)
        self.assertEqual(
            friend.get(
                f"/media/{key}", headers={"If-None-Match": '"cached-before-revoke"'}
            ).status_code,
            404,
        )
        self.assertIn("Public demo post", friend.get(f"/p/{public}").text)

        restarted = create_app(self.settings)
        with TestClient(restarted, base_url="http://testserver") as restarted_family:
            page = restarted_family.get("/login")
            login = restarted_family.post(
                "/login",
                data={
                    "username": "family",
                    "password": PASSWORD,
                    "csrf": hidden(page.text, "csrf"),
                    "next": f"/p/{shared}",
                },
                follow_redirects=False,
            )
            self.assertEqual(login.status_code, 303)
            detail = restarted_family.get(f"/p/{shared}")
            self.assertIn("family root", detail.text)
            self.assertNotIn("open before revoke", detail.text)
            self.assertIn("Лайков: 2", detail.text)
            self.assertEqual(restarted_family.get(f"/media/{key}").status_code, 200)
            self.assertEqual(restarted_family.get("/healthz").status_code, 204)

    def test_access_watch_is_bound_to_exact_circle_move_revoke_and_session(self):
        friend = self.client("friend")
        stranger = self.client("stranger")
        anonymous = self.client()
        store = Store(self.database)
        try:
            shared = store.publish(
                self.users["grigory"],
                "Shared for watcher",
                [self.contexts["Friends"], self.contexts["Family"]],
            )
            store.add_comment(
                self.users["friend"], shared, "friends history", channel="private"
            )
        finally:
            store.close()

        profile = friend.get("/u/grigory")
        post = friend.get(f"/p/{shared}")
        profile_watch, post_watch = watch_url(profile.text), watch_url(post.text)
        self.assertIsNotNone(profile_watch)
        self.assertIsNotNone(post_watch)
        for private_id in (self.contexts["Friends"], self.contexts["Family"]):
            self.assertNotIn(private_id, profile.text)
            self.assertNotIn(private_id, post.text)
        self.assertEqual(friend.get(profile_watch).status_code, 204)
        self.assertEqual(friend.get(post_watch).status_code, 204)
        self.assertEqual(stranger.get(profile_watch).status_code, 404)
        self.assertEqual(anonymous.get(post_watch).status_code, 404)
        self.assertEqual(friend.get(profile_watch.replace("proof=", "proof=bad")).status_code, 404)

        store = Store(self.database)
        try:
            store.assign(
                self.users["grigory"], self.users["friend"], self.contexts["Family"]
            )
            store.add_comment(
                self.users["family"], shared, "family history", channel="private"
            )
        finally:
            store.close()
        self.assertEqual(friend.get(profile_watch).status_code, 404)
        self.assertEqual(friend.get(post_watch).status_code, 404)
        moved_profile = friend.get("/u/grigory")
        moved_post = friend.get(f"/p/{shared}")
        self.assertIn("Study, home and the people closest to me.", moved_profile.text)
        self.assertNotEqual(watch_url(moved_profile.text), profile_watch)
        self.assertNotIn("friends history", moved_post.text)
        self.assertIn("family history", moved_post.text)

        new_watch = watch_url(moved_post.text)
        store = Store(self.database)
        try:
            store.revoke(self.users["grigory"], self.users["friend"])
        finally:
            store.close()
        self.assertEqual(friend.get(new_watch).status_code, 404)
        fresh_profile = friend.get("/u/grigory")
        self.assertIn("A second-year ITMO student building selecont.", fresh_profile.text)
        self.assertIsNone(watch_url(fresh_profile.text))
        self.assertEqual(friend.get(f"/p/{shared}").status_code, 404)

        script = anonymous.get("/assets/access-watch.js")
        self.assertEqual(script.status_code, 200)
        self.assertIn("replaceChildren", script.text)
        self.assertIn("setInterval(verifyAccess, 800)", script.text)

    def test_http_comment_waiting_on_revoke_rechecks_membership(self):
        friend = self.client("friend")
        store = Store(self.database)
        try:
            post_id = store.publish(
                self.users["grigory"], "Concurrent revoke", [self.contexts["Friends"]]
            )
        finally:
            store.close()
        page = friend.get(f"/p/{post_id}")
        csrf = hidden(page.text, "csrf")
        started = threading.Event()
        result = []

        def submit_comment():
            started.set()
            response = friend.post(
                f"/p/{post_id}/comments",
                data={"csrf": csrf, "thread": "private", "body": "racing write"},
            )
            result.append(response.status_code)

        transaction = Store(self.database)
        try:
            with transaction._transaction(write=True):
                transaction.db.execute(
                    "DELETE FROM memberships WHERE author_id = ? AND follower_id = ?",
                    (self.users["grigory"], self.users["friend"]),
                )
                worker = threading.Thread(target=submit_comment)
                worker.start()
                self.assertTrue(started.wait(2))
            worker.join(6)
            self.assertFalse(worker.is_alive())
        finally:
            transaction.close()
        self.assertEqual(result, [404])
        with sqlite3.connect(self.database) as db:
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM comments WHERE body = 'racing write'"
                ).fetchone()[0],
                0,
            )


if __name__ == "__main__":
    unittest.main()
