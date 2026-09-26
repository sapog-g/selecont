"""HTTP/session regressions for the first closed-demo web slice."""

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
from selecont.web import SESSION_COOKIE, Settings, create_app


PASSWORD = "correct horse battery staple"
PUBLIC_BIO = "A second-year ITMO student building selecont."
FRIEND_BIO = "Campus life, jokes and late-night plans."
FAMILY_BIO = "Study, home and the people closest to me."


def hidden(html, name):
    match = re.search(rf'name="{re.escape(name)}" value="([^"]+)"', html)
    if not match:
        raise AssertionError(f"Missing hidden field {name}")
    return match.group(1)


class WebTests(unittest.TestCase):
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
        self.database = Path(self.temp.name) / "test.sqlite3"
        shutil.copyfile(self.template, self.database)
        settings = Settings(self.database, b"test-secret-that-is-long-and-random", cookie_secure=False)
        self.app = create_app(settings)
        self.client = TestClient(self.app, base_url="http://testserver")
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def login(self, client, handle, password=PASSWORD, **extra):
        page = client.get("/login?next=/u/grigory")
        data = {"username": handle, "password": password, "csrf": hidden(page.text, "csrf"), "next": "/u/grigory", **extra}
        return client.post("/login", data=data, follow_redirects=False)

    def test_anonymous_friend_and_family_see_different_bios_at_one_url(self):
        anonymous = self.client.get("/u/grigory")
        self.assertIn(PUBLIC_BIO, anonymous.text)
        self.assertIn("Анонимный просмотр Public", anonymous.text)

        with TestClient(self.app, base_url="http://testserver") as friend, TestClient(self.app, base_url="http://testserver") as family:
            self.assertEqual(self.login(friend, "friend").status_code, 303)
            self.assertEqual(self.login(family, "family").status_code, 303)
            friend_page = friend.get("/u/grigory")
            family_page = family.get("/u/grigory")
            self.assertIn(FRIEND_BIO, friend_page.text)
            self.assertNotIn(FAMILY_BIO, friend_page.text)
            self.assertIn(FAMILY_BIO, family_page.text)
            self.assertNotIn(FRIEND_BIO, family_page.text)
            self.assertNotIn("Friends</", friend_page.text)
            self.assertNotIn("Family</", family_page.text)

    def test_demo_guide_explains_roles_and_global_navigation(self):
        anonymous = self.client.get("/demo-guide")
        self.assertEqual(anonymous.status_code, 200)
        self.assertIn("Пять шагов, чтобы понять selecont", anonymous.text)
        self.assertIn("Сейчас открыт анонимный режим", anonymous.text)
        for path in ("/u/grigory", "/demo-guide", "/settings/contexts", "/settings/posts", "/posts/new"):
            self.assertIn(f'href="{path}"', anonymous.text)

        self.login(self.client, "friend")
        friend = self.client.get("/demo-guide")
        self.assertIn("Сейчас выполнен вход как @friend", friend.text)
        self.assertNotIn("Friends", friend.text)
        self.assertNotIn("Family", friend.text)

    def test_guide_does_not_disclose_test_memberships(self):
        for handle in (None, "friend", "family", "stranger"):
            with TestClient(self.app) as client:
                if handle:
                    self.login(client, handle)
                page = client.get("/demo-guide")
                self.assertEqual(page.status_code, 200)
                self.assertNotIn("Friends", page.text)
                self.assertNotIn("Family", page.text)
                self.assertNotIn("твоего текущего круга", page.text)
        store = Store(self.database)
        try:
            store.revoke(store.user_id_for_handle("grigory"), store.user_id_for_handle("friend"))
        finally:
            store.close()
        self.login(self.client, "friend")
        page = self.client.get("/demo-guide")
        self.assertNotIn("Friends", page.text)
        self.assertNotIn("друг;", page.text)

    def test_unicode_csrf_is_rejected_without_server_error(self):
        self.client.get("/login")
        response = self.client.post("/login", data={"username": "friend", "password": PASSWORD, "csrf": "неверно"})
        self.assertEqual(response.status_code, 403)
        self.login(self.client, "friend")
        for path in ("/logout", "/u/grigory/follow"):
            self.assertEqual(self.client.post(path, data={"csrf": "неверно"}).status_code, 403)
        for path, data in (("/settings/avatar", {"csrf": "неверно", "context_id": "public"}), ("/posts", {"csrf": "неверно", "body": "text", "audience": "public"})):
            response = self.client.post(path, data=data, files={"photo": ("image.png", b"invalid", "image/png")})
            self.assertEqual(response.status_code, 403)
        self.assertIn(FRIEND_BIO, self.client.get("/u/grigory").text)

    def test_unicode_access_proof_is_rejected_without_server_error(self):
        self.login(self.client, "friend")
        self.assertEqual(self.client.get("/access/u/grigory/private", params={"proof": "неверно"}).status_code, 404)

    def test_oversized_normal_form_rejected_before_parsing(self):
        response = self.client.post("/login", content=b"x" * (16 * 1024 + 1), headers={"content-type": "application/x-www-form-urlencoded"})
        self.assertEqual(response.status_code, 413)

    def test_identity_comes_from_session_and_browser_user_id_is_ignored(self):
        store = Store(self.database)
        try:
            family_id = store.user_id_for_handle("family")
        finally:
            store.close()
        response = self.login(self.client, "friend", user_id=family_id)
        self.assertEqual(response.status_code, 303)
        page = self.client.get("/u/grigory")
        self.assertIn("Вы вошли как <strong>@friend</strong>", page.text)
        self.assertIn(FRIEND_BIO, page.text)
        self.assertNotIn(FAMILY_BIO, page.text)

    def test_revoke_takes_effect_on_next_request_in_same_session(self):
        self.login(self.client, "friend")
        self.assertIn(FRIEND_BIO, self.client.get("/u/grigory").text)
        store = Store(self.database)
        try:
            store.revoke(store.user_id_for_handle("grigory"), store.user_id_for_handle("friend"))
        finally:
            store.close()
        page = self.client.get("/u/grigory")
        self.assertIn(PUBLIC_BIO, page.text)
        self.assertNotIn(FRIEND_BIO, page.text)
        self.assertIn("Вы вошли как <strong>@friend</strong>", page.text)

    def test_login_and_logout_require_csrf_and_logout_only_current_session(self):
        page = self.client.get("/login")
        bad = self.client.post("/login", data={"username": "friend", "password": PASSWORD, "csrf": "wrong"})
        self.assertEqual(bad.status_code, 403)
        self.assertFalse(self.client.cookies.get(SESSION_COOKIE))

        self.login(self.client, "friend")
        profile = self.client.get("/u/grigory")
        rejected = self.client.post("/logout", data={"csrf": "wrong"})
        self.assertEqual(rejected.status_code, 403)
        self.assertIn(FRIEND_BIO, self.client.get("/u/grigory").text)
        accepted = self.client.post(
            "/logout", data={"csrf": hidden(profile.text, "csrf"), "user_id": "family"}, follow_redirects=False
        )
        self.assertEqual(accepted.status_code, 303)
        self.assertIn(PUBLIC_BIO, self.client.get("/u/grigory").text)
        self.assertEqual(self.client.post("/logout", data={"csrf": "anything"}).status_code, 401)

    def test_expired_session_falls_back_to_public_and_is_removed(self):
        self.login(self.client, "friend")
        with sqlite3.connect(self.database) as db:
            db.execute("UPDATE sessions SET created_at = -1, expires_at = 0")
        page = self.client.get("/u/grigory")
        self.assertIn("Анонимный просмотр Public", page.text)
        self.assertNotIn(FRIEND_BIO, page.text)
        with sqlite3.connect(self.database) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 0)

    def test_rate_limit_blocks_correct_password_after_repeated_failures(self):
        for _ in range(5):
            response = self.login(self.client, "friend", "definitely incorrect")
            self.assertEqual(response.status_code, 401)
        blocked = self.login(self.client, "friend")
        self.assertEqual(blocked.status_code, 429)
        self.assertGreaterEqual(int(blocked.headers["retry-after"]), 1)
        self.assertNotIn(FRIEND_BIO, blocked.text)

    def test_password_and_session_token_are_not_stored_in_plaintext(self):
        self.login(self.client, "friend")
        raw_token = self.client.cookies.get(SESSION_COOKIE)
        with sqlite3.connect(self.database) as db:
            password_hash = db.execute("SELECT password_hash FROM credentials c JOIN users u ON u.id = c.user_id WHERE u.handle = 'friend'").fetchone()[0]
            token_hash = db.execute("SELECT token_hash FROM sessions").fetchone()[0]
        self.assertTrue(password_hash.startswith("$argon2"))
        self.assertNotIn(PASSWORD, password_hash)
        self.assertNotEqual(raw_token, token_hash)
        self.assertNotIn(raw_token, token_hash)

    def test_cookie_and_response_security_headers(self):
        response = self.login(self.client, "friend")
        cookies = response.headers.get_list("set-cookie")
        session_cookie = next(value for value in cookies if value.startswith(SESSION_COOKIE + "="))
        self.assertIn("HttpOnly", session_cookie)
        self.assertIn("SameSite=lax", session_cookie)
        profile = self.client.get("/u/grigory")
        self.assertEqual(profile.headers["cache-control"], "no-store")
        self.assertIn("default-src 'none'", profile.headers["content-security-policy"])
        self.assertEqual(profile.headers["x-content-type-options"], "nosniff")

    def test_user_text_is_escaped_and_unknown_profile_is_generic(self):
        store = Store(self.database)
        try:
            author = store.user_id_for_handle("grigory")
            public = next(row["id"] for row in store.author_contexts(author, author) if row["kind"] == "public")
            store.set_profile(author, public, bio='<script>alert("private")</script>')
        finally:
            store.close()
        page = self.client.get("/u/grigory")
        self.assertNotIn("<script>", page.text)
        self.assertIn("&lt;script&gt;", page.text)
        missing = self.client.get("/u/does_not_exist")
        self.assertEqual(missing.status_code, 404)
        self.assertNotIn("database", missing.text.lower())

    def test_form_rejects_wrong_media_type_duplicates_and_oversize(self):
        self.assertEqual(self.client.post("/login", json={}).status_code, 415)
        self.assertEqual(
            self.client.post("/login", content="username=a&username=b", headers={"content-type": "application/x-www-form-urlencoded"}).status_code,
            400,
        )
        self.assertEqual(
            self.client.post("/login", content="x=" + "a" * 17000, headers={"content-type": "application/x-www-form-urlencoded"}).status_code,
            413,
        )


class MigrationTests(unittest.TestCase):
    def test_schema_one_is_upgraded_to_auth_schema(self):
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "old.sqlite3"
            store = Store(database)
            store.migrate()
            for table in (
                "post_media",
                "profile_media",
                "media_assets",
                "login_attempts",
                "sessions",
                "credentials",
            ):
                store.db.execute(f"DROP TABLE {table}")
            store.db.execute("PRAGMA user_version = 1")
            store.close()
            upgraded = Store(database)
            try:
                upgraded.migrate()
                self.assertEqual(upgraded.db.execute("PRAGMA user_version").fetchone()[0], 7)
                tables = {row[0] for row in upgraded.db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
                self.assertTrue({"credentials", "sessions", "login_attempts", "media_assets"} <= tables)
            finally:
                upgraded.close()


if __name__ == "__main__":
    unittest.main()
