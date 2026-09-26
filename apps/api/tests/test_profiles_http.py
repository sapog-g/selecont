"""T04 browser-facing profile, circle and follower management checks."""

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

from selecont.core import InvalidInput, MAX_PRIVATE_CIRCLES, Store
from selecont.operator import seed_demo
from selecont.web import Settings, create_app


PASSWORD = "correct horse battery staple"
SECRET = b"t04-test-secret-at-least-32-bytes"
PUBLIC_BIO = "A second-year ITMO student building selecont."
FRIEND_BIO = "Campus life, jokes and late-night plans."
FAMILY_BIO = "Study, home and the people closest to me."


def hidden(html, name):
    match = re.search(rf'name="{re.escape(name)}" value="([^"]*)"', html)
    if not match:
        raise AssertionError(f"Missing hidden field {name}")
    return match.group(1)


def image_key(html):
    match = re.search(r'<img class="avatar(?: small)?" src="/media/([A-Za-z0-9_-]+)"', html)
    if not match:
        raise AssertionError("Missing protected avatar URL")
    return match.group(1)


def image_bytes(color):
    image = Image.new("RGB", (30, 24), color)
    output = BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


class ProfileManagementHTTPTests(unittest.TestCase):
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
        self.app = create_app(
            Settings(
                self.database,
                SECRET,
                cookie_secure=False,
                media_root=self.media_root,
            )
        )
        self.clients = []

    def tearDown(self):
        for client in reversed(self.clients):
            client.__exit__(None, None, None)
        self.temp.cleanup()

    def client(self):
        client = TestClient(self.app, base_url="http://testserver")
        client.__enter__()
        self.clients.append(client)
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

    def context_ids(self, handle="grigory"):
        store = Store(self.database)
        try:
            actor = store.user_id_for_handle(handle)
            return actor, {
                row["name"]: row["id"]
                for row in store.author_contexts(actor, actor)
            }
        finally:
            store.close()

    def post_session_form(self, client, path, data, *, source="/settings/contexts"):
        page = client.get(source)
        return client.post(
            path,
            data={"csrf": hidden(page.text, "csrf"), **data},
            follow_redirects=False,
        )

    def upload(self, author, context_id, color):
        page = author.get(f"/settings/avatar?context_id={context_id}")
        return author.post(
            "/settings/avatar",
            data={"csrf": hidden(page.text, "csrf"), "context_id": context_id},
            files={"photo": ("avatar.png", image_bytes(color), "image/png")},
            follow_redirects=False,
        )

    def test_follow_assign_move_revoke_and_unfollow(self):
        author, stranger = self.client(), self.client()
        self.login(author, "grigory")
        self.login(stranger, "stranger")

        public_page = stranger.get("/u/grigory")
        self.assertIn(PUBLIC_BIO, public_page.text)
        self.assertIn(">Подписаться<", public_page.text)
        followed = stranger.post(
            "/u/grigory/follow",
            data={"csrf": hidden(public_page.text, "csrf")},
            follow_redirects=False,
        )
        self.assertEqual(followed.status_code, 303)
        self.assertIn(PUBLIC_BIO, stranger.get("/u/grigory").text)
        self.assertIn("@stranger", author.get("/settings/contexts").text)

        _, contexts = self.context_ids()
        assigned = self.post_session_form(
            author,
            "/settings/membership",
            {"follower_id": self.context_ids("stranger")[0], "context_id": contexts["Friends"]},
        )
        self.assertEqual(assigned.status_code, 303)
        self.assertIn(FRIEND_BIO, stranger.get("/u/grigory").text)

        moved = self.post_session_form(
            author,
            "/settings/membership",
            {"follower_id": self.context_ids("stranger")[0], "context_id": contexts["Family"]},
        )
        self.assertEqual(moved.status_code, 303)
        moved_page = stranger.get("/u/grigory")
        self.assertIn(FAMILY_BIO, moved_page.text)
        self.assertNotIn(FRIEND_BIO, moved_page.text)
        self.assertNotIn("Ты видишь вариант профиля", moved_page.text)
        self.assertNotIn("Название скрытого круга", moved_page.text)
        with sqlite3.connect(self.database) as db:
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM memberships WHERE author_id = ? AND follower_id = ?",
                    (self.context_ids()[0], self.context_ids("stranger")[0]),
                ).fetchone()[0],
                1,
            )

        revoked = self.post_session_form(
            author,
            "/settings/membership",
            {"follower_id": self.context_ids("stranger")[0], "context_id": ""},
        )
        self.assertEqual(revoked.status_code, 303)
        self.assertIn(PUBLIC_BIO, stranger.get("/u/grigory").text)

        self.post_session_form(
            author,
            "/settings/membership",
            {"follower_id": self.context_ids("stranger")[0], "context_id": contexts["Friends"]},
        )
        followed_page = stranger.get("/u/grigory")
        unfollowed = stranger.post(
            "/u/grigory/unfollow",
            data={"csrf": hidden(followed_page.text, "csrf")},
            follow_redirects=False,
        )
        self.assertEqual(unfollowed.status_code, 303)
        self.assertIn(PUBLIC_BIO, stranger.get("/u/grigory").text)
        self.assertNotIn("@stranger", author.get("/settings/contexts").text)

    def test_circle_first_member_picker_is_alphabetical_and_preserves_selection(self):
        author = self.client()
        self.login(author, "grigory")
        author_id, contexts = self.context_ids()
        store = Store(self.database)
        try:
            alice = store.create_user("alice")
            zoe = store.create_user("zoe")
            store.follow(alice, author_id)
            store.follow(zoe, author_id)
        finally:
            store.close()

        page = author.get(f"/settings/contexts?circle={contexts['Friends']}")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Участники · Friends", page.text)
        self.assertIn("Добавить людей", page.text)
        self.assertLess(page.text.index("letter-heading\">A"), page.text.index("letter-heading\">F"))
        self.assertLess(page.text.index("letter-heading\">F"), page.text.index("letter-heading\">Z"))
        self.assertLess(page.text.index("@alice"), page.text.index("@family"))
        self.assertLess(page.text.index("@family"), page.text.index("@zoe"))
        self.assertIn("Сейчас: Family", page.text)

        response = self.post_session_form(
            author,
            "/settings/membership",
            {
                "follower_id": alice,
                "context_id": contexts["Friends"],
                "return_circle": contexts["Friends"],
            },
            source=f"/settings/contexts?circle={contexts['Friends']}",
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            response.headers["location"],
            f"/settings/contexts?circle={contexts['Friends']}",
        )
        refreshed = author.get(response.headers["location"])
        self.assertIn("@alice", refreshed.text)
        self.assertEqual(
            author.get("/settings/contexts?circle=missing").status_code,
            404,
        )

    def test_circle_profile_preview_and_hidden_metadata(self):
        author, stranger, anonymous = self.client(), self.client(), self.client()
        self.login(author, "grigory")
        self.login(stranger, "stranger")
        circle_name = "Top Secret <Circle>"
        created = self.post_session_form(
            author, "/settings/circles", {"name": circle_name}
        )
        self.assertEqual(created.status_code, 303)
        settings_page = author.get("/settings/contexts")
        self.assertIn("Top Secret &lt;Circle&gt;", settings_page.text)
        _, contexts = self.context_ids()
        context_id = contexts[circle_name]
        private_bio = 'Only this audience sees <script>alert("x")</script>.'
        updated = self.post_session_form(
            author,
            "/settings/profile",
            {"context_id": context_id, "bio": private_bio},
        )
        self.assertEqual(updated.status_code, 303)

        preview = author.get(f"/settings/preview/{context_id}")
        self.assertIn("Предпросмотр: Top Secret &lt;Circle&gt;", preview.text)
        self.assertIn("&lt;script&gt;", preview.text)
        self.assertNotIn("<script>", preview.text)
        self.assertNotIn("method=\"post\"", preview.text.lower())

        stranger_page = stranger.get("/u/grigory")
        stranger.post(
            "/u/grigory/follow",
            data={"csrf": hidden(stranger_page.text, "csrf")},
            follow_redirects=False,
        )
        self.post_session_form(
            author,
            "/settings/membership",
            {"follower_id": self.context_ids("stranger")[0], "context_id": context_id},
        )
        viewer_page = stranger.get("/u/grigory")
        self.assertIn("Only this audience sees &lt;script&gt;", viewer_page.text)
        self.assertNotIn("<script>", viewer_page.text)
        self.assertNotIn("Top Secret", viewer_page.text)
        self.assertNotIn(context_id, viewer_page.text)
        self.assertNotIn("@friend", viewer_page.text)
        self.assertNotIn(private_bio, anonymous.get("/u/grigory").text)
        self.assertEqual(stranger.get(f"/settings/preview/{context_id}").status_code, 404)

    def test_forms_enforce_session_csrf_ownership_names_and_circle_limit(self):
        anonymous, author, friend = self.client(), self.client(), self.client()
        self.login(author, "grigory")
        self.login(friend, "friend")
        self.assertEqual(
            anonymous.post(
                "/settings/circles", data={"csrf": "x", "name": "No"}
            ).status_code,
            401,
        )
        self.assertEqual(
            author.post(
                "/settings/circles", data={"csrf": "wrong", "name": "No"}
            ).status_code,
            403,
        )
        self.assertEqual(
            self.post_session_form(author, "/settings/circles", {"name": "friends"}).status_code,
            400,
        )
        self.assertEqual(
            self.post_session_form(author, "/settings/circles", {"name": "x" * 61}).status_code,
            400,
        )
        _, contexts = self.context_ids()
        self.assertEqual(
            self.post_session_form(
                author,
                "/settings/profile",
                {"context_id": contexts["Public"], "bio": "x" * 501},
            ).status_code,
            400,
        )
        forged = self.post_session_form(
            friend,
            "/settings/profile",
            {
                "context_id": contexts["Family"],
                "bio": "Forged",
                "actor_id": self.context_ids()[0],
            },
        )
        self.assertEqual(forged.status_code, 404)
        self.assertEqual(
            self.post_session_form(
                friend,
                "/settings/membership",
                {
                    "follower_id": self.context_ids("family")[0],
                    "context_id": contexts["Friends"],
                },
            ).status_code,
            404,
        )
        author_id = self.context_ids()[0]
        family_id = self.context_ids("family")[0]
        store = Store(self.database)
        try:
            self.assertEqual(
                store.profile(author_id, family_id)["bio"],
                FAMILY_BIO,
            )
            existing = len(
                [
                    row
                    for row in store.author_contexts(author_id, author_id)
                    if row["kind"] == "private"
                ]
            )
            for number in range(existing, MAX_PRIVATE_CIRCLES):
                store.create_circle(author_id, f"Limit {number}")
            with self.assertRaises(InvalidInput):
                store.create_circle(author_id, "One too many")
        finally:
            store.close()

    def test_profile_forms_produce_distinct_bios_and_avatars_at_one_url(self):
        author, friend, family, anonymous = (
            self.client(), self.client(), self.client(), self.client()
        )
        self.login(author, "grigory")
        self.login(friend, "friend")
        self.login(family, "family")
        _, contexts = self.context_ids()
        expected = {
            "Public": ("Public view written in T04", (20, 80, 140)),
            "Friends": ("Plans after class", (30, 150, 90)),
            "Family": ("News from university", (230, 160, 40)),
        }
        for name, (bio, color) in expected.items():
            self.assertEqual(
                self.post_session_form(
                    author,
                    "/settings/profile",
                    {"context_id": contexts[name], "bio": bio},
                ).status_code,
                303,
            )
            self.assertEqual(self.upload(author, contexts[name], color).status_code, 303)

        pages = {
            "Public": anonymous.get("/u/grigory"),
            "Friends": friend.get("/u/grigory"),
            "Family": family.get("/u/grigory"),
        }
        for name, page in pages.items():
            self.assertIn(expected[name][0], page.text)
            for other_name in expected:
                if other_name != name:
                    self.assertNotIn(expected[other_name][0], page.text)
        self.assertEqual(len({image_key(page.text) for page in pages.values()}), 3)

    def test_new_circle_copies_public_variant_and_bio_edit_keeps_photo(self):
        author = self.client()
        self.login(author, "grigory")
        _, contexts = self.context_ids()
        self.assertEqual(self.upload(author, contexts["Public"], (20, 80, 140)).status_code, 303)
        public_key = image_key(author.get("/u/grigory").text)
        self.assertEqual(
            self.post_session_form(author, "/settings/circles", {"name": "New circle"}).status_code,
            303,
        )
        new_context = self.context_ids()[1]["New circle"]
        inherited = author.get(f"/settings/preview/{new_context}")
        self.assertIn(PUBLIC_BIO, inherited.text)
        self.assertEqual(image_key(inherited.text), public_key)
        self.assertEqual(
            self.post_session_form(
                author,
                "/settings/profile",
                {"context_id": new_context, "bio": "Changed without replacing the photo"},
            ).status_code,
            303,
        )
        edited = author.get(f"/settings/preview/{new_context}")
        self.assertIn("Changed without replacing the photo", edited.text)
        self.assertEqual(image_key(edited.text), public_key)


if __name__ == "__main__":
    unittest.main()
