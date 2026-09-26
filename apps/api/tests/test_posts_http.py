"""T05 HTTP checks for explicit-audience posts with one protected photo."""

from io import BytesIO
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from PIL import Image

from selecont.core import NotFound, Store
from selecont.media import MAX_INPUT_BYTES, PhotoStore
from selecont.operator import seed_demo
from selecont.web import Settings, create_app


PASSWORD = "correct horse battery staple"
SECRET = b"t05-test-secret-at-least-32-bytes"


def image_bytes(color):
    image = Image.new("RGB", (48, 36), color)
    output = BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


def hidden(html, name):
    match = re.search(rf'name="{re.escape(name)}" value="([^"]*)"', html)
    if not match:
        raise AssertionError(f"Missing hidden field {name}")
    return match.group(1)


def post_id(response):
    match = re.fullmatch(r"/p/([0-9a-f-]{36})", response.headers.get("location", ""))
    if not match:
        raise AssertionError("Missing post redirect")
    return match.group(1)


def post_photo_key(html):
    match = re.search(r'<img class="post-photo" src="/media/([A-Za-z0-9_-]+)"', html)
    if not match:
        raise AssertionError("Missing protected post photo")
    return match.group(1)


class PostHTTPTests(unittest.TestCase):
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
            self.database, SECRET, cookie_secure=False, media_root=self.media_root
        )
        self.app = create_app(self.settings)
        self.clients = []

    def tearDown(self):
        for client in reversed(self.clients):
            client.__exit__(None, None, None)
        self.temp.cleanup()

    def client(self, handle=None):
        client = TestClient(self.app, base_url="http://testserver")
        client.__enter__()
        self.clients.append(client)
        if handle:
            self.login(client, handle)
        return client

    def login(self, client, handle):
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

    def ids(self, handle="grigory"):
        store = Store(self.database)
        try:
            actor = store.user_id_for_handle(handle)
            contexts = {
                row["name"]: row["id"]
                for row in store.author_contexts(actor, actor)
            }
            return actor, contexts
        finally:
            store.close()

    def publish(self, author, body, audiences, color="steelblue"):
        page = author.get("/posts/new")
        response = author.post(
            "/posts",
            data={"csrf": hidden(page.text, "csrf"), "body": body, "audience": audiences},
            files={"photo": ("post.png", image_bytes(color), "image/png")},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303, response.text)
        return post_id(response)

    def test_shared_private_post_and_separate_public_post_have_explicit_access(self):
        author = self.client("grigory")
        friend = self.client("friend")
        family = self.client("family")
        stranger = self.client("stranger")
        anonymous = self.client()
        _, contexts = self.ids()

        shared_body = "A private photo for two parts of my life."
        shared = self.publish(
            author, shared_body, [contexts["Friends"], contexts["Family"]], "navy"
        )
        friend_detail = friend.get(f"/p/{shared}")
        family_detail = family.get(f"/p/{shared}")
        self.assertEqual(friend_detail.status_code, 200)
        self.assertEqual(family_detail.status_code, 200)
        denied_private = anonymous.get(f"/p/{shared}")
        self.assertEqual(denied_private.status_code, 404)
        self.assertEqual(denied_private.text, anonymous.get("/p/missing").text)
        self.assertEqual(stranger.get(f"/p/{shared}").status_code, 404)
        private_key = post_photo_key(friend_detail.text)
        self.assertEqual(private_key, post_photo_key(family_detail.text))
        self.assertEqual(friend.get(f"/media/{private_key}").status_code, 200)
        self.assertEqual(family.get(f"/media/{private_key}").status_code, 200)
        self.assertEqual(anonymous.get(f"/media/{private_key}").status_code, 404)

        for client in (friend, family):
            profile = client.get("/u/grigory")
            self.assertEqual(profile.text.count(shared_body), 1)
            for secret in ("Friends", "Family", contexts["Friends"], contexts["Family"]):
                self.assertNotIn(secret, profile.text)
        self.assertNotIn(shared_body, anonymous.get("/u/grigory").text)

        public_body = "A separate update for everyone."
        public = self.publish(author, public_body, [contexts["Public"]], "skyblue")
        public_detail = anonymous.get(f"/p/{public}")
        self.assertEqual(public_detail.status_code, 200)
        self.assertIn(public_body, public_detail.text)
        self.assertEqual(
            anonymous.get(f"/media/{post_photo_key(public_detail.text)}").status_code, 200
        )
        public_profile = anonymous.get("/u/grigory").text
        self.assertIn(public_body, public_profile)
        self.assertNotIn(shared_body, public_profile)

    def test_post_form_requires_session_csrf_valid_file_and_owned_audiences(self):
        anonymous = self.client()
        author = self.client("grigory")
        friend = self.client("friend")
        _, contexts = self.ids()
        _, family_contexts = self.ids("family")
        payload = image_bytes("red")

        self.assertEqual(
            anonymous.post(
                "/posts",
                data={"csrf": "x", "body": "No", "audience": contexts["Public"]},
                files={"photo": ("a.png", payload, "image/png")},
            ).status_code,
            401,
        )
        self.assertEqual(
            author.post(
                "/posts",
                data={"csrf": "wrong", "body": "No", "audience": contexts["Public"]},
                files={"photo": ("a.png", payload, "image/png")},
            ).status_code,
            403,
        )
        csrf = hidden(author.get("/posts/new").text, "csrf")
        foreign = author.post(
            "/posts",
            data={"csrf": csrf, "body": "Foreign audience", "audience": family_contexts["Public"]},
            files={"photo": ("a.png", payload, "image/png")},
        )
        self.assertEqual(foreign.status_code, 404)

        csrf = hidden(author.get("/posts/new").text, "csrf")
        duplicate = author.post(
            "/posts",
            files=[
                ("csrf", (None, csrf)),
                ("body", (None, "Duplicate")),
                ("audience", (None, contexts["Public"])),
                ("audience", (None, contexts["Public"])),
                ("photo", ("a.png", payload, "image/png")),
            ],
        )
        self.assertEqual(duplicate.status_code, 400)

        csrf = hidden(author.get("/posts/new").text, "csrf")
        damaged = author.post(
            "/posts",
            data={"csrf": csrf, "body": "Damaged", "audience": contexts["Public"]},
            files={"photo": ("a.png", b"not an image", "image/png")},
        )
        self.assertEqual(damaged.status_code, 400)

        csrf = hidden(author.get("/posts/new").text, "csrf")
        no_audience = author.post(
            "/posts",
            data={"csrf": csrf, "body": "No audience"},
            files={"photo": ("a.png", payload, "image/png")},
        )
        self.assertEqual(no_audience.status_code, 400)

        csrf = hidden(author.get("/posts/new").text, "csrf")
        oversized = author.post(
            "/posts",
            data={"csrf": csrf, "body": "Too large", "audience": contexts["Public"]},
            files={
                "photo": (
                    "large.png",
                    b"x" * (MAX_INPUT_BYTES + 300 * 1024),
                    "image/png",
                )
            },
        )
        self.assertEqual(oversized.status_code, 413)

        friend_csrf = hidden(friend.get("/posts/new").text, "csrf")
        forged = friend.post(
            "/posts",
            data={
                "csrf": friend_csrf,
                "body": "Forged author",
                "audience": contexts["Public"],
            },
            files={"photo": ("a.png", payload, "image/png")},
        )
        self.assertEqual(forged.status_code, 404)
        with sqlite3.connect(self.database) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM posts").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM media_assets").fetchone()[0], 0)
        self.assertEqual(list(self.media_root.iterdir()), [])

    def test_text_only_post_is_allowed_but_audience_is_still_explicit(self):
        author = self.client("grigory")
        anonymous = self.client()
        _, contexts = self.ids()
        form = author.get("/posts/new")
        self.assertIn("Фотография <span class=\"meta\">(необязательно", form.text)
        self.assertNotRegex(form.text, r'id="post-photo"[^>]+required')

        created = author.post(
            "/posts",
            files=[
                ("csrf", (None, hidden(form.text, "csrf"))),
                ("body", (None, "Текст без фотографии")),
                ("audience", (None, contexts["Public"])),
            ],
            follow_redirects=False,
        )
        self.assertEqual(created.status_code, 303, created.text)
        detail = anonymous.get(created.headers["location"])
        self.assertEqual(detail.status_code, 200)
        self.assertIn("Текст без фотографии", detail.text)
        self.assertNotIn('class="post-photo"', detail.text)

        no_audience_form = author.get("/posts/new")
        rejected = author.post(
            "/posts",
            files=[
                ("csrf", (None, hidden(no_audience_form.text, "csrf"))),
                ("body", (None, "Нельзя угадать аудиторию")),
            ],
        )
        self.assertEqual(rejected.status_code, 400)
        with sqlite3.connect(self.database) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM post_media").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM media_assets").fetchone()[0], 0)

    def test_service_and_database_reject_foreign_or_reused_attachment(self):
        author_id, contexts = self.ids()
        family_id, _ = self.ids("family")
        photos = PhotoStore(self.database, self.media_root)
        store = Store(self.database)
        try:
            foreign = photos.store_photo(family_id, image_bytes("orange"))
            with self.assertRaises(NotFound):
                store.publish(
                    author_id, "Cannot attach this", [contexts["Public"]], photo_key=foreign.key
                )
            own = photos.store_photo(author_id, image_bytes("green"))
            first = store.publish(
                author_id, "One attached photo", [contexts["Public"]], photo_key=own.key
            )
            with self.assertRaises(NotFound):
                store.publish(
                    author_id, "Cannot reuse it", [contexts["Public"]], photo_key=own.key
                )
            with self.assertRaises(sqlite3.IntegrityError):
                store.db.execute(
                    "INSERT INTO post_media(author_id, post_id, asset_key) VALUES (?, ?, ?)",
                    (author_id, first, foreign.key),
                )
            self.assertEqual(
                store.db.execute("SELECT COUNT(*) FROM posts").fetchone()[0], 1
            )
        finally:
            store.close()
            photos.close()

    def test_delete_requires_owner_and_removes_post_photo_and_direct_urls(self):
        author = self.client("grigory")
        friend = self.client("friend")
        anonymous = self.client()
        _, contexts = self.ids()
        created = self.publish(author, "Temporary private post", [contexts["Friends"]])
        detail = friend.get(f"/p/{created}")
        key = post_photo_key(detail.text)
        with sqlite3.connect(self.database) as db:
            storage_name = db.execute(
                "SELECT storage_name FROM media_assets WHERE asset_key = ?", (key,)
            ).fetchone()[0]

        wrong_owner = friend.post(
            f"/p/{created}/delete",
            data={"csrf": hidden(friend.get("/u/grigory").text, "csrf")},
            follow_redirects=False,
        )
        self.assertEqual(wrong_owner.status_code, 404)
        self.assertEqual(
            author.post(f"/p/{created}/delete", data={"csrf": "wrong"}).status_code,
            403,
        )
        deleted = author.post(
            f"/p/{created}/delete",
            data={"csrf": hidden(author.get("/settings/posts").text, "csrf")},
            follow_redirects=False,
        )
        self.assertEqual(deleted.status_code, 303)
        for client in (author, friend, anonymous):
            self.assertEqual(client.get(f"/p/{created}").status_code, 404)
            self.assertEqual(client.get(f"/media/{key}").status_code, 404)
        with sqlite3.connect(self.database) as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM posts WHERE id = ?", (created,)).fetchone()[0],
                0,
            )
            for table in ("post_audiences", "post_media"):
                self.assertEqual(
                    db.execute(f"SELECT COUNT(*) FROM {table} WHERE post_id = ?", (created,)).fetchone()[0],
                    0,
                )
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM media_assets WHERE asset_key = ?", (key,)).fetchone()[0],
                0,
            )
        self.assertFalse((self.media_root / storage_name).exists())

    def test_revoke_and_expired_session_close_next_page_and_photo_request(self):
        author = self.client("grigory")
        friend = self.client("friend")
        _, contexts = self.ids()
        created = self.publish(author, "Current members only", [contexts["Friends"]])
        key = post_photo_key(friend.get(f"/p/{created}").text)
        self.assertEqual(friend.get(f"/media/{key}").status_code, 200)
        store = Store(self.database)
        try:
            store.revoke(
                store.user_id_for_handle("grigory"), store.user_id_for_handle("friend")
            )
        finally:
            store.close()
        self.assertEqual(friend.get(f"/p/{created}").status_code, 404)
        self.assertEqual(friend.get(f"/media/{key}").status_code, 404)

        store = Store(self.database)
        try:
            store.assign(
                store.user_id_for_handle("grigory"),
                store.user_id_for_handle("friend"),
                contexts["Friends"],
            )
        finally:
            store.close()
        self.assertEqual(friend.get(f"/media/{key}").status_code, 200)
        with sqlite3.connect(self.database) as db:
            db.execute(
                "UPDATE sessions SET created_at = -1, expires_at = 0 "
                "WHERE token_hash IN (SELECT s.token_hash FROM sessions s JOIN users u ON u.id = s.user_id WHERE u.handle = 'friend')"
            )
        self.assertEqual(friend.get(f"/p/{created}").status_code, 404)
        self.assertEqual(friend.get(f"/media/{key}").status_code, 404)

    def test_viewer_responses_escape_text_and_hide_all_audience_metadata(self):
        author = self.client("grigory")
        friend = self.client("friend")
        family = self.client("family")
        _, contexts = self.ids()
        body = '<script>alert("post")</script> & safe text'
        created = self.publish(
            author, body, [contexts["Friends"], contexts["Family"]]
        )
        for client in (friend, family):
            response = client.get(f"/p/{created}")
            self.assertEqual(response.status_code, 200)
            self.assertIn("&lt;script&gt;", response.text)
            self.assertNotIn("<script>", response.text)
            for secret in ("Friends", "Family", contexts["Friends"], contexts["Family"]):
                self.assertNotIn(secret, response.text)
        management = author.get("/settings/posts")
        self.assertIn("Friends", management.text)
        self.assertIn("Family", management.text)
        self.assertNotIn("<script>", management.text)
        self.assertIn("&lt;script&gt;", management.text)
        self.assertNotIn(body, self.client("stranger").get("/settings/posts").text)

    def test_public_post_and_photo_survive_application_restart(self):
        author = self.client("grigory")
        _, contexts = self.ids()
        created = self.publish(author, "Still here after restart", [contexts["Public"]])
        key = post_photo_key(author.get(f"/p/{created}").text)

        restarted = create_app(self.settings)
        with TestClient(restarted, base_url="http://testserver") as anonymous:
            detail = anonymous.get(f"/p/{created}")
            self.assertEqual(detail.status_code, 200)
            self.assertIn("Still here after restart", detail.text)
            self.assertEqual(post_photo_key(detail.text), key)
            self.assertEqual(anonymous.get(f"/media/{key}").status_code, 200)
            self.assertEqual(anonymous.get("/healthz").status_code, 204)
        with sqlite3.connect(self.database) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 7)
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_schema_four_upgrade_preserves_existing_text_posts(self):
        author_id, contexts = self.ids()
        store = Store(self.database)
        legacy_post = store.publish(
            author_id, "Created before post photos", [contexts["Public"]]
        )
        store.db.execute("DROP TABLE post_media")
        store.db.execute("PRAGMA user_version = 4")
        store.close()

        upgraded = Store(self.database)
        try:
            upgraded.migrate()
            self.assertEqual(upgraded.db.execute("PRAGMA user_version").fetchone()[0], 7)
            self.assertEqual(
                upgraded.post(legacy_post)["body"], "Created before post photos"
            )
            self.assertEqual(
                upgraded.db.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'post_media'"
                ).fetchone()[0],
                1,
            )
        finally:
            upgraded.close()


if __name__ == "__main__":
    unittest.main()
