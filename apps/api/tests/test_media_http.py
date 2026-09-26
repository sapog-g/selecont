"""T03 HTTP and persistence checks for protected profile photos."""

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
SECRET = b"persistent-test-secret-at-least-32-bytes"


def image_bytes(color, image_format="PNG"):
    image = Image.new("RGB", (24, 18), color)
    output = BytesIO()
    image.save(output, image_format)
    return output.getvalue()


def hidden(html, name):
    match = re.search(rf'name="{re.escape(name)}" value="([^"]+)"', html)
    if not match:
        raise AssertionError(f"Missing hidden field {name}")
    return match.group(1)


def image_key(html):
    match = re.search(r'<img class="avatar" src="/media/([A-Za-z0-9_-]+)"', html)
    if not match:
        raise AssertionError("Missing protected avatar URL")
    return match.group(1)


class ProtectedMediaHTTPTests(unittest.TestCase):
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
        self.client = TestClient(self.app, base_url="http://testserver")
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def login(self, client, handle):
        page = client.get("/login")
        return client.post(
            "/login",
            data={
                "username": handle,
                "password": PASSWORD,
                "csrf": hidden(page.text, "csrf"),
                "next": "/u/grigory",
            },
            follow_redirects=False,
        )

    def contexts(self, handle="grigory"):
        store = Store(self.database)
        try:
            actor = store.user_id_for_handle(handle)
            return actor, {
                row["name"]: row["id"] for row in store.author_contexts(actor, actor)
            }
        finally:
            store.close()

    def upload(self, client, context_id, payload, *, filename="avatar.png", content_type="image/png"):
        page = client.get("/settings/avatar")
        return client.post(
            "/settings/avatar",
            data={"csrf": hidden(page.text, "csrf"), "context_id": context_id},
            files={"photo": (filename, payload, content_type)},
            follow_redirects=False,
        )

    def attach_three_variants(self):
        self.assertEqual(self.login(self.client, "grigory").status_code, 303)
        _, contexts = self.contexts()
        for name, color in (
            ("Public", (20, 80, 140)),
            ("Friends", (30, 150, 90)),
            ("Family", (230, 160, 40)),
        ):
            response = self.upload(self.client, contexts[name], image_bytes(color))
            self.assertEqual(response.status_code, 303)

    def test_profile_variants_and_each_direct_media_request_use_current_access(self):
        self.attach_three_variants()
        owner_key = image_key(self.client.get("/u/grigory").text)

        anonymous = TestClient(self.app, base_url="http://testserver")
        friend = TestClient(self.app, base_url="http://testserver")
        family = TestClient(self.app, base_url="http://testserver")
        with anonymous, friend, family:
            self.login(friend, "friend")
            self.login(family, "family")
            public_key = image_key(anonymous.get("/u/grigory").text)
            friend_key = image_key(friend.get("/u/grigory").text)
            family_key = image_key(family.get("/u/grigory").text)
            self.assertEqual(owner_key, public_key)
            self.assertEqual(len({public_key, friend_key, family_key}), 3)

            allowed = friend.get(f"/media/{friend_key}")
            self.assertEqual(allowed.status_code, 200)
            self.assertEqual(allowed.headers["content-type"], "image/webp")
            self.assertEqual(allowed.headers["cache-control"], "private, no-store, max-age=0")
            self.assertEqual(allowed.headers["cross-origin-resource-policy"], "same-origin")
            self.assertEqual(allowed.headers["vary"], "Cookie")
            self.assertEqual(family.get(f"/media/{friend_key}").status_code, 404)
            self.assertEqual(anonymous.get(f"/media/{friend_key}").status_code, 404)
            self.assertEqual(anonymous.get(f"/media/{public_key}").status_code, 200)
            self.assertEqual(self.client.get(f"/media/{friend_key}").status_code, 200)
            self.assertEqual(anonymous.get(f"/static/{friend_key}.webp").status_code, 404)

            store = Store(self.database)
            try:
                store.revoke(
                    store.user_id_for_handle("grigory"),
                    store.user_id_for_handle("friend"),
                )
            finally:
                store.close()
            revoked = friend.get(
                f"/media/{friend_key}", headers={"If-None-Match": '"old-cached-copy"'}
            )
            self.assertEqual(revoked.status_code, 404)
            self.assertNotEqual(image_key(friend.get("/u/grigory").text), friend_key)

    def test_expired_session_cannot_read_private_media(self):
        self.attach_three_variants()
        with TestClient(self.app, base_url="http://testserver") as family:
            self.login(family, "family")
            private_key = image_key(family.get("/u/grigory").text)
            self.assertEqual(family.get(f"/media/{private_key}").status_code, 200)
            with sqlite3.connect(self.database) as db:
                db.execute(
                    "UPDATE sessions SET created_at = -1, expires_at = 0 "
                    "WHERE token_hash IN (SELECT token_hash FROM sessions s JOIN users u ON u.id = s.user_id WHERE u.handle = 'family')"
                )
            denied = family.get(f"/media/{private_key}")
            self.assertEqual(denied.status_code, 404)
            self.assertTrue(any("Max-Age=0" in value for value in denied.headers.get_list("set-cookie")))

    def test_upload_requires_session_csrf_valid_file_and_owned_context(self):
        _, contexts = self.contexts()
        self.assertEqual(
            self.client.post(
                "/settings/avatar",
                data={"csrf": "anything", "context_id": contexts["Public"]},
                files={"photo": ("a.png", image_bytes("red"), "image/png")},
            ).status_code,
            401,
        )
        self.login(self.client, "grigory")
        page = self.client.get("/settings/avatar")
        bad_csrf = self.client.post(
            "/settings/avatar",
            data={"csrf": "wrong", "context_id": contexts["Public"]},
            files={"photo": ("a.png", image_bytes("red"), "image/png")},
        )
        self.assertEqual(bad_csrf.status_code, 403)
        damaged = self.client.post(
            "/settings/avatar",
            data={"csrf": hidden(page.text, "csrf"), "context_id": contexts["Public"]},
            files={"photo": ("a.png", b"not an image", "image/png")},
        )
        self.assertEqual(damaged.status_code, 400)

        _, foreign_contexts = self.contexts("family")
        foreign = self.upload(
            self.client, foreign_contexts["Public"], image_bytes("blue")
        )
        self.assertEqual(foreign.status_code, 404)
        with sqlite3.connect(self.database) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM media_assets").fetchone()[0], 0)
        self.assertEqual(list(self.media_root.iterdir()), [])

        oversized = self.upload(
            self.client,
            contexts["Public"],
            b"x" * (MAX_INPUT_BYTES + 300 * 1024),
        )
        self.assertEqual(oversized.status_code, 413)

        # A client can omit Content-Length and stream with chunked encoding;
        # the ASGI receive wrapper must enforce the same total-body ceiling.
        csrf = hidden(self.client.get("/settings/avatar").text, "csrf")
        boundary = "selecont-test-boundary"

        def chunked_body():
            yield (
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"csrf\"\r\n\r\n"
                f"{csrf}\r\n--{boundary}\r\nContent-Disposition: form-data; "
                f"name=\"context_id\"\r\n\r\n{contexts['Public']}\r\n--{boundary}\r\n"
                "Content-Disposition: form-data; name=\"photo\"; filename=\"large.png\"\r\n"
                "Content-Type: image/png\r\n\r\n"
            ).encode()
            chunk = b"x" * (256 * 1024)
            for _ in range(42):
                yield chunk
            yield f"\r\n--{boundary}--\r\n".encode()

        chunked = self.client.post(
            "/settings/avatar",
            content=chunked_body(),
            headers={"content-type": f"multipart/form-data; boundary={boundary}"},
        )
        self.assertEqual(chunked.status_code, 413)

    def test_database_and_service_reject_cross_owner_attachment(self):
        author_id, contexts = self.contexts()
        other_id, _ = self.contexts("family")
        photos = PhotoStore(self.database, self.media_root)
        try:
            asset = photos.store_photo(other_id, image_bytes("orange"))
            with self.assertRaises(NotFound):
                photos.attach_profile_avatar(author_id, contexts["Public"], asset.key)
            with self.assertRaises(sqlite3.IntegrityError):
                photos.db.execute(
                    "INSERT INTO profile_media(author_id, context_id, asset_key) VALUES (?, ?, ?)",
                    (author_id, contexts["Public"], asset.key),
                )
        finally:
            photos.close()

    def test_database_and_photo_survive_application_restart(self):
        self.attach_three_variants()
        with TestClient(self.app, base_url="http://testserver") as friend:
            self.login(friend, "friend")
            key = image_key(friend.get("/u/grigory").text)
            expected = friend.get(f"/media/{key}").content

        self.client.__exit__(None, None, None)
        restarted = create_app(self.settings)
        with TestClient(restarted, base_url="http://testserver") as friend:
            self.login(friend, "friend")
            self.assertEqual(image_key(friend.get("/u/grigory").text), key)
            self.assertEqual(friend.get(f"/media/{key}").content, expected)
            self.assertEqual(friend.get("/healthz").status_code, 204)
        self.client = TestClient(self.app, base_url="http://testserver")
        self.client.__enter__()


if __name__ == "__main__":
    unittest.main()
