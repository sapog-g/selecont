"""T01 tests for private photo validation and storage."""

from io import BytesIO
import os
from pathlib import Path
import sqlite3
import stat
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image
from PIL.PngImagePlugin import PngInfo

from selecont.core import NotFound, Store
from selecont.media import (
    MAX_INPUT_BYTES,
    MAX_PIXELS,
    PhotoRejected,
    PhotoStore,
    StorageLimitExceeded,
)


def image_bytes(image_format="JPEG", *, size=(8, 6), exif=None, png_text=None):
    image = Image.new("RGB", size, (34, 109, 185))
    output = BytesIO()
    options = {}
    if exif is not None:
        options["exif"] = exif
    if png_text is not None:
        options["pnginfo"] = png_text
    image.save(output, image_format, **options)
    return output.getvalue()


class PhotoStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.database = self.base / "selecont.sqlite3"
        self.media_root = self.base / "private-media"
        domain = Store(self.database)
        try:
            domain.migrate()
            self.owner = domain.create_user("owner")
            self.other = domain.create_user("other")
        finally:
            domain.close()
        self.photos = PhotoStore(self.database, self.media_root)

    def tearDown(self):
        self.photos.close()
        self.temp.cleanup()

    def extra_store(self, **limits):
        store = PhotoStore(self.database, self.media_root, **limits)
        self.addCleanup(store.close)
        return store

    def test_real_jpeg_png_and_webp_files_are_normalized_into_private_webp(self):
        samples = [
            ("JPEG", "image/jpeg"),
            ("PNG", "image/png"),
            ("WEBP", "image/webp"),
        ]
        for index, (image_format, content_type) in enumerate(samples):
            source = self.base / f"photo-{index}.bin"
            source.write_bytes(image_bytes(image_format))
            with source.open("rb") as stream:
                asset = self.photos.store_photo(
                    self.owner,
                    stream,
                    declared_content_type=content_type,
                    original_name=f"../../private-{index}.{image_format.lower()}",
                )
            self.assertEqual(asset.content_type, "image/webp")
            self.assertEqual((asset.width, asset.height), (8, 6))
            self.assertEqual(asset.status, "pending")
            stored = self.photos.read_owned(self.owner, asset.key)
            with Image.open(BytesIO(stored)) as normalized:
                self.assertEqual(normalized.format, "WEBP")
                self.assertEqual(normalized.n_frames, 1)
                normalized.load()

        names = [row[0] for row in self.photos.db.execute("SELECT storage_name FROM media_assets")]
        self.assertTrue(all(name.endswith(".webp") and "/" not in name and ".." not in name for name in names))
        self.assertEqual(stat.S_IMODE(self.media_root.stat().st_mode), 0o700)
        for name in names:
            self.assertEqual(stat.S_IMODE((self.media_root / name).stat().st_mode), 0o600)

    def test_orientation_is_applied_and_exif_png_text_and_profiles_are_removed(self):
        exif = Image.Exif()
        exif[274] = 6
        exif[315] = "private author"
        jpeg = self.photos.store_photo(
            self.owner,
            image_bytes("JPEG", size=(2, 3), exif=exif),
            declared_content_type="image/jpeg",
        )
        self.assertEqual((jpeg.width, jpeg.height), (3, 2))
        with Image.open(BytesIO(self.photos.read_owned(self.owner, jpeg.key))) as normalized:
            self.assertEqual(dict(normalized.getexif()), {})
            self.assertNotIn("exif", normalized.info)
            self.assertNotIn("icc_profile", normalized.info)
            self.assertNotIn("xmp", normalized.info)

        text = PngInfo()
        text.add_text("private-note", "do not keep")
        png = self.photos.store_photo(self.owner, image_bytes("PNG", png_text=text))
        with Image.open(BytesIO(self.photos.read_owned(self.owner, png.key))) as normalized:
            self.assertNotIn("private-note", normalized.info)

    def test_invalid_mismatch_unsupported_and_animated_files_are_rejected(self):
        with self.assertRaises(PhotoRejected):
            self.photos.store_photo(self.owner, b"not an image", declared_content_type="image/jpeg", original_name="fake.jpg")
        with self.assertRaises(PhotoRejected):
            self.photos.store_photo(self.owner, image_bytes("JPEG"), declared_content_type="image/png")
        with self.assertRaises(PhotoRejected):
            self.photos.store_photo(self.owner, image_bytes("GIF"), declared_content_type="image/jpeg")

        first = Image.new("RGB", (4, 4), "red")
        second = Image.new("RGB", (4, 4), "blue")
        animated = BytesIO()
        first.save(animated, "PNG", save_all=True, append_images=[second], duration=50, loop=0)
        with self.assertRaises(PhotoRejected):
            self.photos.store_photo(self.owner, animated.getvalue(), declared_content_type="image/png")
        self.assertEqual(self.photos.db.execute("SELECT COUNT(*) FROM media_assets").fetchone()[0], 0)
        self.assertEqual(list(self.media_root.iterdir()), [])

    def test_input_output_and_pixel_limits_are_enforced(self):
        valid = image_bytes("PNG", size=(4, 4))
        too_small_input_limit = self.extra_store(max_input_bytes=len(valid) - 1)
        with self.assertRaises(PhotoRejected):
            too_small_input_limit.store_photo(self.owner, BytesIO(valid))

        tiny_pixel_limit = self.extra_store(max_pixels=15)
        with self.assertRaises(PhotoRejected):
            tiny_pixel_limit.store_photo(self.owner, valid)

        tiny_output_limit = self.extra_store(max_output_bytes=8)
        with self.assertRaises(PhotoRejected):
            tiny_output_limit.store_photo(self.owner, valid)
        self.assertEqual(MAX_INPUT_BYTES, 10 * 1024 * 1024)
        self.assertEqual(MAX_PIXELS, 20_000_000)

    def test_owner_checks_prevent_read_delete_and_quota_bypass(self):
        first = self.photos.store_photo(self.owner, image_bytes("JPEG"))
        for action in (
            lambda: self.photos.asset_for_owner(self.other, first.key),
            lambda: self.photos.read_owned(self.other, first.key),
            lambda: self.photos.discard_owned(self.other, first.key),
            lambda: self.photos.store_photo("missing-owner", image_bytes("JPEG")),
        ):
            with self.assertRaises(NotFound):
                action()
        self.assertEqual(self.photos.read_owned(self.owner, first.key)[:4], b"RIFF")

        limited = self.extra_store(max_owner_bytes=first.byte_size + 1)
        with self.assertRaises(StorageLimitExceeded):
            limited.store_photo(self.owner, image_bytes("JPEG", size=(9, 7)))
        self.assertEqual(self.photos.db.execute("SELECT COUNT(*) FROM media_assets").fetchone()[0], 1)
        self.photos.discard_owned(self.owner, first.key)
        self.assertEqual(list(self.media_root.iterdir()), [])

    def test_atomic_write_failure_leaves_no_file_or_database_row(self):
        with mock.patch("selecont.media.os.replace", side_effect=OSError("simulated failure")):
            with self.assertRaises(OSError):
                self.photos.store_photo(self.owner, image_bytes("JPEG"))
        with mock.patch("selecont.media.os.chmod", side_effect=OSError("simulated permission failure")):
            with self.assertRaises(OSError):
                self.photos.store_photo(self.owner, image_bytes("JPEG"))
        self.assertEqual(self.photos.db.execute("SELECT COUNT(*) FROM media_assets").fetchone()[0], 0)
        self.assertEqual(list(self.media_root.iterdir()), [])

    def test_expired_pending_staging_and_orphan_files_are_cleaned(self):
        asset = self.photos.store_photo(self.owner, image_bytes("JPEG"), now=0)
        attached = self.photos.store_photo(self.owner, image_bytes("PNG"), now=0)
        self.photos.db.execute(
            "UPDATE media_assets SET status = 'attached' WHERE asset_key = ?", (attached.key,)
        )
        staging = self.media_root / ".upload-abandoned.tmp"
        orphan = self.media_root / ("x" * 32 + ".webp")
        staging.write_bytes(b"partial")
        orphan.write_bytes(b"orphan")
        os.utime(staging, (0, 0))
        os.utime(orphan, (0, 0))
        result = self.photos.cleanup_pending(max_age_seconds=1, now=100)
        self.assertEqual(result, {"records": 1, "files": 3})
        self.assertEqual(self.photos.db.execute("SELECT COUNT(*) FROM media_assets").fetchone()[0], 1)
        self.assertEqual(len(list(self.media_root.iterdir())), 1)
        self.assertTrue(self.photos.read_owned(self.owner, attached.key))
        with self.assertRaises(NotFound):
            self.photos.asset_for_owner(self.owner, asset.key)

    def test_database_rejects_client_controlled_storage_paths(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.photos.db.execute(
                "INSERT INTO media_assets "
                "(asset_key, owner_id, storage_name, content_type, byte_size, width, height, created_at) "
                "VALUES (?, ?, ?, 'image/webp', 1, 1, 1, 0)",
                ("a" * 32, self.owner, "../../outside.webp"),
            )


class MediaMigrationTests(unittest.TestCase):
    def test_schema_two_is_upgraded_to_private_media_schema(self):
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "schema-two.sqlite3"
            store = Store(database)
            store.migrate()
            store.db.execute("DROP TABLE post_media")
            store.db.execute("DROP TABLE profile_media")
            store.db.execute("DROP INDEX media_assets_key_owner")
            store.db.execute("DROP TABLE media_assets")
            store.db.execute("PRAGMA user_version = 2")
            store.close()
            upgraded = Store(database)
            try:
                upgraded.migrate()
                self.assertEqual(upgraded.db.execute("PRAGMA user_version").fetchone()[0], 7)
                columns = {
                    row[1] for row in upgraded.db.execute("PRAGMA table_info(media_assets)")
                }
                self.assertTrue({"asset_key", "owner_id", "storage_name", "status"} <= columns)
                tables = {
                    row[0]
                    for row in upgraded.db.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                self.assertIn("profile_media", tables)
            finally:
                upgraded.close()

    def test_schema_three_upgrade_preserves_media_and_can_attach_it(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            database = base / "schema-three.sqlite3"
            media_root = base / "media"
            store = Store(database)
            store.migrate()
            owner = store.create_user("owner")
            public = next(
                row["id"]
                for row in store.author_contexts(owner, owner)
                if row["kind"] == "public"
            )
            store.close()
            photos = PhotoStore(database, media_root)
            asset = photos.store_photo(owner, image_bytes("PNG"))
            photos.close()

            old = Store(database)
            old.db.execute("DROP TABLE post_media")
            old.db.execute("DROP TABLE profile_media")
            old.db.execute("DROP INDEX media_assets_key_owner")
            old.db.execute("PRAGMA user_version = 3")
            old.close()

            upgraded = Store(database)
            upgraded.migrate()
            self.assertEqual(upgraded.db.execute("PRAGMA user_version").fetchone()[0], 7)
            self.assertEqual(
                upgraded.db.execute("SELECT COUNT(*) FROM media_assets").fetchone()[0], 1
            )
            upgraded.close()
            photos = PhotoStore(database, media_root)
            try:
                photos.attach_profile_avatar(owner, public, asset.key)
                self.assertTrue(photos.read_for_viewer(None, asset.key)[1])
            finally:
                photos.close()


if __name__ == "__main__":
    unittest.main()
