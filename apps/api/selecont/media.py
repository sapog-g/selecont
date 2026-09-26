"""Private photo validation, normalization and local storage.

Client filenames are never used as filesystem paths. Attached files are read
through the current database permissions; the storage directory is never
mounted as a public/static directory.
"""

from dataclasses import dataclass
from io import BytesIO
import os
from pathlib import Path
import re
import secrets
import sqlite3
import tempfile
import time
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

from .core import NotFound, Store


MAX_INPUT_BYTES = 10 * 1024 * 1024
MAX_OUTPUT_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 20_000_000
MAX_OWNER_BYTES = 100 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
PENDING_TTL_SECONDS = 24 * 60 * 60
READ_CHUNK_BYTES = 64 * 1024

INPUT_FORMATS = ("JPEG", "PNG", "WEBP")
FORMAT_CONTENT_TYPES = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}
SAFE_KEY = re.compile(r"[A-Za-z0-9_-]{32,80}\Z")
SAFE_STORAGE_NAME = re.compile(r"[A-Za-z0-9_-]{32,80}\.webp\Z")


class PhotoRejected(ValueError):
    """The supplied file is not acceptable for the closed demo."""


class StorageLimitExceeded(PhotoRejected):
    """The configured per-owner or total media allowance is exhausted."""


@dataclass(frozen=True)
class PhotoAsset:
    key: str
    owner_id: str
    content_type: str
    byte_size: int
    width: int
    height: int
    status: str
    created_at: int


class PhotoStore:
    """Normalize photos and keep them outside the web application's static tree."""

    def __init__(
        self,
        database,
        root,
        *,
        max_input_bytes=MAX_INPUT_BYTES,
        max_output_bytes=MAX_OUTPUT_BYTES,
        max_pixels=MAX_PIXELS,
        max_owner_bytes=MAX_OWNER_BYTES,
        max_total_bytes=MAX_TOTAL_BYTES,
        cleanup_on_open=True,
    ):
        limits = (
            max_input_bytes,
            max_output_bytes,
            max_pixels,
            max_owner_bytes,
            max_total_bytes,
        )
        if any(not isinstance(limit, int) or limit <= 0 for limit in limits):
            raise ValueError("Media limits must be positive integers")

        initializer = Store(database)
        try:
            initializer.migrate()
        finally:
            initializer.close()

        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        self.db = sqlite3.connect(database, isolation_level=None, timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.max_input_bytes = max_input_bytes
        self.max_output_bytes = max_output_bytes
        self.max_pixels = max_pixels
        self.max_owner_bytes = max_owner_bytes
        self.max_total_bytes = max_total_bytes
        if cleanup_on_open:
            self.cleanup_pending()

    def close(self):
        self.db.close()

    def _read_limited(self, source):
        if isinstance(source, (bytes, bytearray, memoryview)):
            payload = bytes(source)
            if len(payload) > self.max_input_bytes:
                raise PhotoRejected("Photo exceeds the 10 MB input limit")
            if not payload:
                raise PhotoRejected("Photo is empty")
            return payload
        if not hasattr(source, "read"):
            raise PhotoRejected("Photo must be bytes or a binary stream")

        chunks = []
        size = 0
        while True:
            chunk = source.read(min(READ_CHUNK_BYTES, self.max_input_bytes + 1 - size))
            if not chunk:
                break
            if not isinstance(chunk, (bytes, bytearray, memoryview)):
                raise PhotoRejected("Photo stream must return bytes")
            chunk = bytes(chunk)
            size += len(chunk)
            if size > self.max_input_bytes:
                raise PhotoRejected("Photo exceeds the 10 MB input limit")
            chunks.append(chunk)
        if not chunks:
            raise PhotoRejected("Photo is empty")
        return b"".join(chunks)

    def _normalize(self, payload, declared_content_type):
        if declared_content_type is not None:
            if not isinstance(declared_content_type, str):
                raise PhotoRejected("Invalid declared content type")
            declared_content_type = declared_content_type.strip().lower()
            if declared_content_type not in FORMAT_CONTENT_TYPES.values():
                raise PhotoRejected("Unsupported declared content type")

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(payload), formats=list(INPUT_FORMATS)) as probe:
                    actual_format = probe.format
                    if actual_format not in INPUT_FORMATS:
                        raise PhotoRejected("Unsupported photo format")
                    if getattr(probe, "is_animated", False) or getattr(probe, "n_frames", 1) != 1:
                        raise PhotoRejected("Animated images are not supported")
                    width, height = probe.size
                    if width <= 0 or height <= 0 or width * height > self.max_pixels:
                        raise PhotoRejected("Photo exceeds the 20 megapixel limit")
                    if declared_content_type and FORMAT_CONTENT_TYPES[actual_format] != declared_content_type:
                        raise PhotoRejected("Photo content does not match its content type")
                    probe.verify()

                with Image.open(BytesIO(payload), formats=list(INPUT_FORMATS)) as decoded:
                    if getattr(decoded, "is_animated", False) or getattr(decoded, "n_frames", 1) != 1:
                        raise PhotoRejected("Animated images are not supported")
                    decoded.load()
                    oriented = ImageOps.exif_transpose(decoded)
                    has_alpha = oriented.mode in ("RGBA", "LA") or (
                        oriented.mode == "P" and "transparency" in oriented.info
                    )
                    converted = oriented.convert("RGBA" if has_alpha else "RGB")
                    clean = Image.new(converted.mode, converted.size)
                    clean.paste(converted)
                    output = BytesIO()
                    clean.save(
                        output,
                        "WEBP",
                        quality=88,
                        method=4,
                        exif=b"",
                        xmp=b"",
                        icc_profile=None,
                    )
                    width, height = clean.size
        except PhotoRejected:
            raise
        except (
            UnidentifiedImageError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
            OSError,
            SyntaxError,
            ValueError,
        ) as error:
            raise PhotoRejected("Invalid or damaged photo") from error

        normalized = output.getvalue()
        if not normalized or len(normalized) > self.max_output_bytes:
            raise PhotoRejected("Processed photo exceeds the storage limit")
        return normalized, width, height

    def _owner_exists(self, owner_id):
        if not isinstance(owner_id, str) or self.db.execute(
            "SELECT 1 FROM users WHERE id = ?", (owner_id,)
        ).fetchone() is None:
            raise NotFound()

    def _path(self, storage_name):
        if not isinstance(storage_name, str) or SAFE_STORAGE_NAME.fullmatch(storage_name) is None:
            raise RuntimeError("Unsafe media storage name")
        return self.root / storage_name

    def _atomic_write(self, destination, payload):
        temporary = None
        published = False
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", prefix=".upload-", suffix=".tmp", dir=self.root, delete=False
            ) as output:
                temporary = Path(output.name)
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, destination)
            temporary = None
            published = True
            os.chmod(destination, 0o600)
            directory = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except BaseException:
            if published:
                destination.unlink(missing_ok=True)
            raise
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def store_photo(
        self,
        owner_id,
        source,
        *,
        declared_content_type=None,
        original_name=None,
        now=None,
    ):
        """Store one pending normalized photo for a trusted owner identity."""
        self._owner_exists(owner_id)
        if original_name is not None and (
            not isinstance(original_name, str) or len(original_name) > 255
        ):
            raise PhotoRejected("Invalid original filename")
        payload = self._read_limited(source)
        normalized, width, height = self._normalize(payload, declared_content_type)
        created_at = int(time.time() if now is None else now)

        for _ in range(4):
            key = secrets.token_urlsafe(24)
            if SAFE_KEY.fullmatch(key) is not None:
                destination = self._path(f"{key}.webp")
                if not destination.exists():
                    break
        else:
            raise RuntimeError("Could not allocate a media key")

        self._atomic_write(destination, normalized)
        try:
            self.db.execute("BEGIN IMMEDIATE")
            self._owner_exists(owner_id)
            owner_used = self.db.execute(
                "SELECT COALESCE(SUM(byte_size), 0) FROM media_assets WHERE owner_id = ?",
                (owner_id,),
            ).fetchone()[0]
            total_used = self.db.execute(
                "SELECT COALESCE(SUM(byte_size), 0) FROM media_assets"
            ).fetchone()[0]
            if owner_used + len(normalized) > self.max_owner_bytes:
                raise StorageLimitExceeded("Owner media allowance is exhausted")
            if total_used + len(normalized) > self.max_total_bytes:
                raise StorageLimitExceeded("Media storage allowance is exhausted")
            self.db.execute(
                "INSERT INTO media_assets "
                "(asset_key, owner_id, storage_name, content_type, byte_size, width, height, status, created_at) "
                "VALUES (?, ?, ?, 'image/webp', ?, ?, ?, 'pending', ?)",
                (key, owner_id, destination.name, len(normalized), width, height, created_at),
            )
            self.db.execute("COMMIT")
        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            destination.unlink(missing_ok=True)
            raise
        return self.asset_for_owner(owner_id, key)

    def asset_for_owner(self, owner_id, key):
        """Return metadata only when the current trusted actor owns the asset."""
        if not isinstance(key, str) or SAFE_KEY.fullmatch(key) is None:
            raise NotFound()
        row = self.db.execute(
            "SELECT * FROM media_assets WHERE asset_key = ? AND owner_id = ?",
            (key, owner_id),
        ).fetchone()
        if row is None:
            raise NotFound()
        return self._asset_from_row(row)

    @staticmethod
    def _asset_from_row(row):
        return PhotoAsset(
            key=row["asset_key"],
            owner_id=row["owner_id"],
            content_type=row["content_type"],
            byte_size=row["byte_size"],
            width=row["width"],
            height=row["height"],
            status=row["status"],
            created_at=row["created_at"],
        )

    def attach_profile_avatar(self, owner_id, context_id, key):
        """Attach an owned pending/attached asset to one owned profile variant.

        The composite foreign key in ``profile_media`` also enforces ownership
        in SQLite, so a future caller cannot bypass this service check.
        """
        if not isinstance(key, str) or SAFE_KEY.fullmatch(key) is None:
            raise NotFound()
        obsolete_storage = None
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self._owner_exists(owner_id)
            if self.db.execute(
                "SELECT 1 FROM profile_variants WHERE author_id = ? AND context_id = ?",
                (owner_id, context_id),
            ).fetchone() is None:
                raise NotFound()
            asset = self.db.execute(
                "SELECT * FROM media_assets WHERE asset_key = ? AND owner_id = ?",
                (key, owner_id),
            ).fetchone()
            if asset is None:
                raise NotFound()
            previous = self.db.execute(
                "SELECT pm.asset_key, ma.storage_name FROM profile_media pm "
                "JOIN media_assets ma ON ma.asset_key = pm.asset_key "
                "WHERE pm.author_id = ? AND pm.context_id = ?",
                (owner_id, context_id),
            ).fetchone()
            self.db.execute(
                "INSERT INTO profile_media(author_id, context_id, asset_key) VALUES (?, ?, ?) "
                "ON CONFLICT(author_id, context_id) DO UPDATE SET asset_key = excluded.asset_key",
                (owner_id, context_id, key),
            )
            self.db.execute(
                "UPDATE media_assets SET status = 'attached' WHERE asset_key = ? AND owner_id = ?",
                (key, owner_id),
            )
            # Keep the legacy projection in sync until the full profile editor
            # moves entirely to the constrained relation.
            self.db.execute(
                "UPDATE profile_variants SET avatar_key = ? WHERE author_id = ? AND context_id = ?",
                (key, owner_id, context_id),
            )
            if previous is not None and previous["asset_key"] != key:
                references = self.db.execute(
                    "SELECT 1 FROM profile_media WHERE asset_key = ? LIMIT 1",
                    (previous["asset_key"],),
                ).fetchone()
                if references is None:
                    self.db.execute(
                        "DELETE FROM media_assets WHERE asset_key = ? AND owner_id = ?",
                        (previous["asset_key"], owner_id),
                    )
                    obsolete_storage = previous["storage_name"]
            self.db.execute("COMMIT")
        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise
        if obsolete_storage is not None:
            self._path(obsolete_storage).unlink(missing_ok=True)
        return self.asset_for_owner(owner_id, key)

    def profile_avatar_key(self, author_id, viewer_id=None, *, preview_context=None):
        """Return the avatar for the profile variant visible right now."""
        self.db.execute("BEGIN")
        try:
            if self.db.execute(
                "SELECT 1 FROM users WHERE id = ?", (author_id,)
            ).fetchone() is None:
                raise NotFound()
            if viewer_id is not None and self.db.execute(
                "SELECT 1 FROM users WHERE id = ?", (viewer_id,)
            ).fetchone() is None:
                raise NotFound()
            if preview_context is not None:
                if viewer_id != author_id or self.db.execute(
                    "SELECT 1 FROM contexts WHERE author_id = ? AND id = ?",
                    (author_id, preview_context),
                ).fetchone() is None:
                    raise NotFound()
                context_id = preview_context
            else:
                selected = self.db.execute(
                    "SELECT id FROM contexts WHERE author_id = ? AND kind = 'public'",
                    (author_id,),
                ).fetchone()
                membership = None
                if viewer_id is not None:
                    membership = self.db.execute(
                        "SELECT context_id FROM memberships WHERE author_id = ? AND follower_id = ?",
                        (author_id, viewer_id),
                    ).fetchone()
                context_id = membership["context_id"] if membership is not None else selected["id"]
            row = self.db.execute(
                "SELECT pm.asset_key FROM profile_media pm "
                "JOIN media_assets ma ON ma.asset_key = pm.asset_key "
                "WHERE pm.author_id = ? AND pm.context_id = ? AND ma.status = 'attached'",
                (author_id, context_id),
            ).fetchone()
            self.db.execute("COMMIT")
        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise
        return row["asset_key"] if row is not None else None

    def read_for_viewer(self, viewer_id, key):
        """Read an asset only after evaluating the viewer's current access."""
        if not isinstance(key, str) or SAFE_KEY.fullmatch(key) is None:
            raise NotFound()
        self.db.execute("BEGIN")
        try:
            if viewer_id is not None and self.db.execute(
                "SELECT 1 FROM users WHERE id = ?", (viewer_id,)
            ).fetchone() is None:
                raise NotFound()
            row = self.db.execute(
                "SELECT * FROM media_assets WHERE asset_key = ?", (key,)
            ).fetchone()
            if row is None:
                raise NotFound()
            allowed = viewer_id == row["owner_id"]
            if not allowed and row["status"] == "attached":
                allowed = self.db.execute(
                    "SELECT 1 FROM ("
                    "SELECT pm.author_id, pm.context_id FROM profile_media pm WHERE pm.asset_key = ? "
                    "UNION ALL "
                    "SELECT post_media.author_id, pa.context_id FROM post_media "
                    "JOIN post_audiences pa ON pa.author_id = post_media.author_id "
                    "AND pa.post_id = post_media.post_id WHERE post_media.asset_key = ?"
                    ") protected JOIN contexts c "
                    "ON c.author_id = protected.author_id AND c.id = protected.context_id "
                    "WHERE c.kind = 'public' OR EXISTS ("
                    "SELECT 1 FROM memberships m WHERE m.author_id = protected.author_id "
                    "AND m.follower_id = ? AND m.context_id = protected.context_id) LIMIT 1",
                    (key, key, viewer_id),
                ).fetchone() is not None
            if not allowed:
                raise NotFound()
            storage_name = row["storage_name"]
            asset = self._asset_from_row(row)
            self.db.execute("COMMIT")
        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise
        try:
            payload = self._path(storage_name).read_bytes()
        except FileNotFoundError as error:
            raise NotFound() from error
        if len(payload) != asset.byte_size:
            raise NotFound()
        return asset, payload

    def remove_orphan(self, storage_name):
        """Remove a file after its media row was transactionally deleted."""
        if not isinstance(storage_name, str) or SAFE_STORAGE_NAME.fullmatch(storage_name) is None:
            raise RuntimeError("Unsafe media storage name")
        if self.db.execute(
            "SELECT 1 FROM media_assets WHERE storage_name = ?", (storage_name,)
        ).fetchone() is not None:
            raise RuntimeError("Media file is still referenced")
        self._path(storage_name).unlink(missing_ok=True)

    def read_owned(self, owner_id, key):
        """Read an owner's asset for internal operator/service work."""
        self.asset_for_owner(owner_id, key)
        row = self.db.execute(
            "SELECT storage_name FROM media_assets WHERE asset_key = ? AND owner_id = ?",
            (key, owner_id),
        ).fetchone()
        try:
            return self._path(row["storage_name"]).read_bytes()
        except FileNotFoundError as error:
            raise NotFound() from error

    def discard_owned(self, owner_id, key):
        """Remove an unattached upload; a different owner sees the same NotFound."""
        asset = self.asset_for_owner(owner_id, key)
        row = self.db.execute(
            "SELECT storage_name FROM media_assets WHERE asset_key = ? AND owner_id = ? AND status = 'pending'",
            (asset.key, owner_id),
        ).fetchone()
        if row is None:
            raise NotFound()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            deleted = self.db.execute(
                "DELETE FROM media_assets WHERE asset_key = ? AND owner_id = ? AND status = 'pending'",
                (asset.key, owner_id),
            ).rowcount
            if deleted != 1:
                raise NotFound()
            self.db.execute("COMMIT")
        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise
        self._path(row["storage_name"]).unlink(missing_ok=True)

    def cleanup_pending(self, *, max_age_seconds=PENDING_TTL_SECONDS, now=None):
        """Delete expired pending rows plus stale staging and untracked files."""
        if not isinstance(max_age_seconds, int) or max_age_seconds < 0:
            raise ValueError("Invalid cleanup age")
        current = int(time.time() if now is None else now)
        cutoff = current - max_age_seconds
        self.db.execute("BEGIN IMMEDIATE")
        try:
            expired = self.db.execute(
                "SELECT storage_name FROM media_assets WHERE status = 'pending' AND created_at <= ?",
                (cutoff,),
            ).fetchall()
            self.db.execute(
                "DELETE FROM media_assets WHERE status = 'pending' AND created_at <= ?",
                (cutoff,),
            )
            self.db.execute("COMMIT")
        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise

        removed_files = 0
        for row in expired:
            path = self._path(row["storage_name"])
            if path.exists():
                path.unlink()
                removed_files += 1

        referenced = {
            row[0] for row in self.db.execute("SELECT storage_name FROM media_assets")
        }
        for path in self.root.iterdir():
            if not path.is_file() or path.stat().st_mtime > cutoff:
                continue
            if path.name.startswith(".upload-") or (
                SAFE_STORAGE_NAME.fullmatch(path.name) is not None and path.name not in referenced
            ):
                path.unlink(missing_ok=True)
                removed_files += 1
        return {"records": len(expired), "files": removed_files}
