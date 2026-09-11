from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Never, cast

from .errors import StateRecoveryError
from .policy import PolicyEngine
from .runs import RunStore

SNAPSHOT_FORMAT = "materials-mcp-state-snapshot/1"
SNAPSHOT_MANIFEST = "snapshot.json"
_DATABASES = (
    (RunStore.DATABASE_NAME, RunStore.SCHEMA_VERSION),
    (PolicyEngine.DATABASE_NAME, PolicyEngine.SCHEMA_VERSION),
)


def _fail(code: str, message: str) -> Never:
    raise StateRecoveryError(code, message)


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    except OSError as error:
        raise StateRecoveryError(
            "database-read-failed", "Database content could not be read"
        ) from error
    return digest.hexdigest()


def _is_indirect(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _existing_root(path: Path, label: str) -> Path:
    if _is_indirect(path):
        _fail(f"unsafe-{label}-path", f"{label.title()} root cannot be a symbolic link")
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise StateRecoveryError(
            f"unsafe-{label}-path", f"{label.title()} root does not exist"
        ) from error
    if not resolved.is_dir() or path.absolute() != resolved:
        _fail(f"unsafe-{label}-path", f"{label.title()} root must be an explicit directory")
    return resolved


def _new_root(path: Path, label: str) -> tuple[Path, Path]:
    if _is_indirect(path) or path.exists():
        _fail(f"{label}-exists", f"{label.title()} target must not already exist")
    parent = _existing_root(path.parent, f"{label}-parent")
    expected = parent / path.name
    if not path.name or path.absolute() != expected:
        _fail(f"unsafe-{label}-path", f"{label.title()} target must be a direct child")
    return expected, parent


def _open_read_only(path: Path) -> sqlite3.Connection:
    try:
        connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=5.0)
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection
    except sqlite3.DatabaseError as error:
        raise StateRecoveryError(
            "database-open-failed", "Unable to open database safely"
        ) from error


def _inspect_database(path: Path, expected_version: int, max_bytes: int) -> tuple[int, int, str]:
    if _is_indirect(path) or not path.is_file():
        _fail("snapshot-incomplete", "Required database file is missing or indirect")
    try:
        size = path.stat().st_size
    except OSError as error:
        raise StateRecoveryError(
            "database-read-failed", "Database metadata could not be read"
        ) from error
    if size < 1 or size > max_bytes:
        _fail("database-size-rejected", "Database size is outside the configured recovery limit")
    connection = _open_read_only(path)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchall()
        if integrity != [("ok",)]:
            _fail("database-integrity-failed", "SQLite integrity validation failed")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            _fail("database-integrity-failed", "SQLite foreign-key validation failed")
        version = cast(int, connection.execute("PRAGMA user_version").fetchone()[0])
    except sqlite3.DatabaseError as error:
        raise StateRecoveryError(
            "database-integrity-failed", "SQLite integrity validation failed"
        ) from error
    finally:
        connection.close()
    if version != expected_version:
        _fail("store-version-incompatible", "Database schema version is unsupported")
    return size, version, _sha256(path)


def _online_backup(source: Path, destination: Path) -> None:
    source_connection = _open_read_only(source)
    try:
        destination_connection = sqlite3.connect(destination, timeout=5.0)
        try:
            source_connection.backup(destination_connection)
        finally:
            destination_connection.close()
    except sqlite3.DatabaseError as error:
        raise StateRecoveryError("backup-failed", "SQLite online backup failed") from error
    finally:
        source_connection.close()


def _remove_created_tree(path: Path, parent: Path) -> None:
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        return
    if resolved.parent == parent and resolved.name.startswith(".materials-mcp-"):
        shutil.rmtree(resolved)


@dataclass(frozen=True)
class RecoveryLimits:
    max_manifest_bytes: int = 64 * 1024
    max_database_bytes: int = 2 * 1024 * 1024 * 1024

    def __post_init__(self) -> None:
        if (
            type(self.max_manifest_bytes) is not int
            or not 256 <= self.max_manifest_bytes <= 1024 * 1024
        ):
            _fail("invalid-recovery-limit", "Manifest limit is outside the supported range")
        if type(self.max_database_bytes) is not int or not self.max_database_bytes >= 4096:
            _fail("invalid-recovery-limit", "Database limit is outside the supported range")


@dataclass(frozen=True)
class DatabaseSnapshot:
    name: str
    schema_version: int
    size_bytes: int
    sha256: str

    def __post_init__(self) -> None:
        versions = dict(_DATABASES)
        if (
            type(self.name) is not str
            or self.name not in versions
            or type(self.schema_version) is not int
            or self.schema_version != versions[self.name]
        ):
            _fail("invalid-snapshot", "Database snapshot identity or version is invalid")
        if type(self.size_bytes) is not int or self.size_bytes < 1:
            _fail("invalid-snapshot", "Database snapshot size is invalid")
        if (
            type(self.sha256) is not str
            or len(self.sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.sha256)
        ):
            _fail("invalid-snapshot", "Database snapshot digest is invalid")

    def to_document(self) -> dict[str, object]:
        return {
            "name": self.name,
            "schema_version": self.schema_version,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class StateSnapshot:
    created_at: datetime
    databases: tuple[DatabaseSnapshot, ...]

    def __post_init__(self) -> None:
        if type(self.created_at) is not datetime or self.created_at.utcoffset() is None:
            _fail("invalid-snapshot", "State snapshot time must include a UTC offset")
        expected_names = tuple(name for name, _ in _DATABASES)
        if (
            type(self.databases) is not tuple
            or tuple(database.name for database in self.databases) != expected_names
        ):
            _fail("invalid-snapshot", "State snapshot database set is invalid")
        object.__setattr__(self, "created_at", self.created_at.astimezone(UTC))

    def to_document(self) -> dict[str, object]:
        return {
            "format": SNAPSHOT_FORMAT,
            "created_at": self.created_at.isoformat(timespec="microseconds").replace("+00:00", "Z"),
            "databases": [database.to_document() for database in self.databases],
        }


class StateRecovery:
    """Integrity-check, snapshot, and fresh-root restore for engine SQLite state."""

    def __init__(self, limits: RecoveryLimits | None = None) -> None:
        self._limits = limits or RecoveryLimits()

    def inspect_snapshot(self, snapshot_root: Path) -> StateSnapshot:
        root = _existing_root(snapshot_root, "snapshot")
        expected_members = {SNAPSHOT_MANIFEST, *(name for name, _ in _DATABASES)}
        try:
            members = tuple(root.iterdir())
        except OSError as error:
            raise StateRecoveryError("snapshot-rejected", "Snapshot cannot be inspected") from error
        if {member.name for member in members} != expected_members or any(
            _is_indirect(member) or not member.is_file() for member in members
        ):
            _fail("snapshot-rejected", "Snapshot member set is not exact")
        manifest_path = root / SNAPSHOT_MANIFEST
        if _is_indirect(manifest_path) or not manifest_path.is_file():
            _fail("snapshot-incomplete", "Snapshot manifest is missing or indirect")
        try:
            size = manifest_path.stat().st_size
        except OSError as error:
            raise StateRecoveryError(
                "snapshot-manifest-rejected", "Snapshot manifest cannot be inspected"
            ) from error
        if size < 1 or size > self._limits.max_manifest_bytes:
            _fail("snapshot-manifest-rejected", "Snapshot manifest size is invalid")
        try:
            loaded: object = json.loads(manifest_path.read_text(encoding="utf-8", errors="strict"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise StateRecoveryError(
                "snapshot-manifest-rejected", "Snapshot manifest is not strict JSON"
            ) from error
        if not isinstance(loaded, dict):
            _fail("snapshot-manifest-rejected", "Snapshot manifest shape is invalid")
        raw_document = cast(dict[object, object], loaded)
        if any(not isinstance(key, str) for key in raw_document):
            _fail("snapshot-manifest-rejected", "Snapshot manifest keys are invalid")
        document = cast(dict[str, object], raw_document)
        if set(document) != {
            "format",
            "created_at",
            "databases",
        }:
            _fail("snapshot-manifest-rejected", "Snapshot manifest shape is invalid")
        if document["format"] != SNAPSHOT_FORMAT or not isinstance(document["created_at"], str):
            _fail("snapshot-manifest-rejected", "Snapshot format or creation time is invalid")
        try:
            created_at = datetime.fromisoformat(document["created_at"].replace("Z", "+00:00"))
        except ValueError as error:
            raise StateRecoveryError(
                "snapshot-manifest-rejected", "Snapshot creation time is invalid"
            ) from error
        if created_at.utcoffset() is None:
            _fail("snapshot-manifest-rejected", "Snapshot creation time must include UTC offset")
        rows_value = document["databases"]
        rows = cast(list[object], rows_value) if isinstance(rows_value, list) else None
        if rows is None or len(rows) != len(_DATABASES):
            _fail("snapshot-incomplete", "Snapshot database set is incomplete")

        declared: dict[str, Mapping[str, object]] = {}
        for raw_item in rows:
            if not isinstance(raw_item, dict):
                _fail("snapshot-manifest-rejected", "Snapshot database entry is invalid")
            raw_mapping = cast(dict[object, object], raw_item)
            if any(not isinstance(key, str) for key in raw_mapping):
                _fail("snapshot-manifest-rejected", "Snapshot database entry is invalid")
            item = cast(dict[str, object], raw_mapping)
            if set(item) != {
                "name",
                "schema_version",
                "size_bytes",
                "sha256",
            }:
                _fail("snapshot-manifest-rejected", "Snapshot database entry is invalid")
            name = item["name"]
            if not isinstance(name, str) or name in declared:
                _fail("snapshot-manifest-rejected", "Snapshot database identity is invalid")
            declared[name] = item

        snapshots: list[DatabaseSnapshot] = []
        for name, expected_version in _DATABASES:
            item = declared.get(name)
            if item is None:
                _fail("snapshot-incomplete", "Snapshot database set is incomplete")
            size_bytes, schema_version, digest = _inspect_database(
                root / name, expected_version, self._limits.max_database_bytes
            )
            if (
                item["schema_version"] != schema_version
                or item["size_bytes"] != size_bytes
                or item["sha256"] != digest
            ):
                _fail("snapshot-checksum-mismatch", "Snapshot database metadata does not match")
            snapshots.append(DatabaseSnapshot(name, schema_version, size_bytes, digest))
        if set(declared) != {name for name, _ in _DATABASES}:
            _fail("snapshot-manifest-rejected", "Snapshot contains an unknown database")
        return StateSnapshot(created_at.astimezone(UTC), tuple(snapshots))

    def create_snapshot(
        self,
        state_root: Path,
        destination: Path,
        *,
        created_at: datetime | None = None,
    ) -> StateSnapshot:
        source_root = _existing_root(state_root, "state")
        target, parent = _new_root(destination, "snapshot")
        timestamp = created_at or datetime.now(UTC)
        if type(timestamp) is not datetime or timestamp.utcoffset() is None:
            _fail("invalid-snapshot-time", "Snapshot time must include a UTC offset")
        temporary = parent / f".materials-mcp-snapshot-{uuid.uuid4().hex}"
        try:
            temporary.mkdir()
        except OSError as error:
            raise StateRecoveryError(
                "snapshot-write-failed", "Snapshot staging directory could not be created"
            ) from error
        try:
            snapshots: list[DatabaseSnapshot] = []
            for name, expected_version in _DATABASES:
                source = source_root / name
                _inspect_database(source, expected_version, self._limits.max_database_bytes)
                copied = temporary / name
                _online_backup(source, copied)
                size_bytes, schema_version, digest = _inspect_database(
                    copied, expected_version, self._limits.max_database_bytes
                )
                snapshots.append(DatabaseSnapshot(name, schema_version, size_bytes, digest))
            snapshot = StateSnapshot(timestamp.astimezone(UTC), tuple(snapshots))
            manifest = temporary / SNAPSHOT_MANIFEST
            manifest.write_text(_canonical(snapshot.to_document()) + "\n", encoding="utf-8")
            with manifest.open("rb+") as stream:
                os.fsync(stream.fileno())
            temporary.rename(target)
            return snapshot
        except StateRecoveryError:
            _remove_created_tree(temporary, parent)
            raise
        except OSError as error:
            _remove_created_tree(temporary, parent)
            raise StateRecoveryError(
                "snapshot-write-failed", "Snapshot could not be written"
            ) from error

    def restore(self, snapshot_root: Path, target_state_root: Path) -> StateSnapshot:
        snapshot = self.inspect_snapshot(snapshot_root)
        source_root = _existing_root(snapshot_root, "snapshot")
        target, parent = _new_root(target_state_root, "restore")
        temporary = parent / f".materials-mcp-restore-{uuid.uuid4().hex}"
        try:
            temporary.mkdir()
        except OSError as error:
            raise StateRecoveryError(
                "restore-write-failed", "Restore staging directory could not be created"
            ) from error
        try:
            for database in snapshot.databases:
                restored = temporary / database.name
                shutil.copyfile(source_root / database.name, restored, follow_symlinks=False)
                with restored.open("rb+") as stream:
                    os.fsync(stream.fileno())
                size_bytes, schema_version, digest = _inspect_database(
                    restored, database.schema_version, self._limits.max_database_bytes
                )
                if (
                    size_bytes != database.size_bytes
                    or schema_version != database.schema_version
                    or digest != database.sha256
                ):
                    _fail(
                        "restore-verification-failed", "Restored database does not match snapshot"
                    )
            temporary.rename(target)
            return snapshot
        except StateRecoveryError:
            _remove_created_tree(temporary, parent)
            raise
        except OSError as error:
            _remove_created_tree(temporary, parent)
            raise StateRecoveryError(
                "restore-write-failed", "Restore could not be written"
            ) from error
