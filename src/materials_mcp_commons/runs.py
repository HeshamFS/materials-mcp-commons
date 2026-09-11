from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from types import MappingProxyType
from typing import NoReturn, Self, cast

from .contracts import ContractRegistry
from .errors import ContractError, RunStoreError
from .lifecycle import CapabilityDetail

REFERENCE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s]+$")
TERMINAL_STATES = frozenset({"succeeded", "failed", "cancelled"})
RUN_STATES = frozenset({"queued", "running", *TERMINAL_STATES})
OWNER_SCOPES = frozenset({"user", "project", "workspace", "service"})
ARTIFACT_ROLES = frozenset(
    {
        "source-record",
        "input",
        "output",
        "structure",
        "trajectory",
        "mesh",
        "log",
        "diagnostic",
        "report",
        "other",
    }
)
ACCESS_SCOPES = frozenset({"public", "workspace", "authenticated", "restricted"})


def _fail(code: str, message: str) -> NoReturn:
    raise RunStoreError(code, message)


def _reference(value: str, field_name: str) -> None:
    if type(value) is not str or REFERENCE_PATTERN.fullmatch(value) is None:
        _fail("invalid-reference", f"{field_name} must be an absolute reference")


def _timestamp(value: datetime, field_name: str) -> str:
    if type(value) is not datetime or value.utcoffset() is None:
        _fail("invalid-time", f"{field_name} must include a UTC offset")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise RunStoreError("store-corruption", "Stored timestamp is invalid") from error
    if parsed.utcoffset() is None:
        _fail("store-corruption", "Stored timestamp lacks an offset")
    return parsed.astimezone(UTC)


def _canonical(document: Mapping[str, object]) -> str:
    try:
        return json.dumps(
            document,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as error:
        raise RunStoreError("invalid-json-value", "Document is not strict JSON") from error


def _document(value: str) -> dict[str, object]:
    try:
        parsed: object = json.loads(value)
    except (json.JSONDecodeError, TypeError) as error:
        raise RunStoreError("store-corruption", "Stored JSON is invalid") from error
    if not isinstance(parsed, dict):
        _fail("store-corruption", "Stored JSON root is not an object")
    return cast(dict[str, object], parsed)


def _freeze(value: object) -> object:
    if isinstance(value, dict):
        document = cast(dict[str, object], value)
        return MappingProxyType({key: _freeze(item) for key, item in document.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in cast(list[object], value))
    return value


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {str(key): _thaw(item) for key, item in mapping.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in cast(tuple[object, ...], value)]
    return value


def _validated(contracts: ContractRegistry, schema_name: str, document: dict[str, object]) -> None:
    try:
        contracts.validate(f"{contracts.canonical_base}{schema_name}", document)
    except ContractError as error:
        raise RunStoreError("contract-rejected", "Runtime document failed its contract") from error


def _contained_file(root: Path, relative_path: str) -> Path:
    if type(relative_path) is not str or not relative_path or "\\" in relative_path:
        _fail("unsafe-artifact-path", "Artifact paths must be nonempty POSIX relative paths")
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        _fail("unsafe-artifact-path", "Artifact path is absolute or contains traversal")
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            _fail("unsafe-artifact-path", "Artifact path contains a symbolic link")
    try:
        candidate = (root / relative).resolve(strict=True)
        candidate.relative_to(root)
    except (OSError, ValueError) as error:
        raise RunStoreError("unsafe-artifact-path", "Artifact path escapes its root") from error
    if not candidate.is_file():
        _fail("unsafe-artifact-path", "Artifact path is not a regular file")
    return candidate


@dataclass(frozen=True)
class RunOwner:
    owner_ref: str
    scope: str

    def __post_init__(self) -> None:
        _reference(self.owner_ref, "owner_ref")
        if self.scope not in OWNER_SCOPES:
            _fail("invalid-owner", "Owner scope is invalid")


@dataclass(frozen=True)
class RunSnapshot:
    run_ref: str
    sequence: int
    state: str
    record: Mapping[str, object]

    @classmethod
    def from_document(cls, document: dict[str, object]) -> RunSnapshot:
        return cls(
            run_ref=cast(str, document["run_ref"]),
            sequence=cast(int, document["sequence"]),
            state=cast(str, document["state"]),
            record=cast(Mapping[str, object], _freeze(document)),
        )

    def to_document(self) -> dict[str, object]:
        return cast(dict[str, object], _thaw(self.record))


@dataclass(frozen=True)
class ArtifactSnapshot:
    artifact_ref: str
    run_ref: str
    document: Mapping[str, object]
    provenance: Mapping[str, object]

    def to_document(self) -> dict[str, object]:
        return cast(dict[str, object], _thaw(self.document))

    def provenance_document(self) -> dict[str, object]:
        return cast(dict[str, object], _thaw(self.provenance))


@dataclass(frozen=True)
class ArtifactAttachment:
    artifact: ArtifactSnapshot
    run: RunSnapshot


class RunStore:
    """SQLite-backed exact-owner run, event, provenance, and artifact store."""

    DATABASE_NAME = "materials-mcp-runs.sqlite3"
    SCHEMA_VERSION = 1

    def __init__(
        self,
        state_root: Path,
        artifact_root: Path,
        contracts: ContractRegistry,
    ) -> None:
        self._state_root = self._safe_root(state_root, "state")
        self._artifact_root = self._safe_root(artifact_root, "artifact")
        database_path = self._state_root / self.DATABASE_NAME
        if database_path.exists() and database_path.is_symlink():
            _fail("unsafe-state-path", "Run database cannot be a symbolic link")
        self._contracts = contracts
        self._lock = RLock()
        try:
            connection = sqlite3.connect(
                database_path,
                timeout=5.0,
                isolation_level=None,
                check_same_thread=False,
            )
        except sqlite3.DatabaseError as error:
            raise RunStoreError("storage-failure", "Unable to open the run store") from error
        self._connection = connection
        try:
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA busy_timeout = 5000")
            self._initialize()
        except RunStoreError:
            self._connection.close()
            raise
        except sqlite3.DatabaseError as error:
            self._connection.close()
            raise RunStoreError("storage-failure", "Unable to initialize the run store") from error

    @staticmethod
    def _safe_root(path: Path, label: str) -> Path:
        if path.is_symlink():
            _fail(f"unsafe-{label}-path", f"{label.title()} root cannot be a symbolic link")
        try:
            resolved = path.resolve(strict=True)
        except OSError as error:
            raise RunStoreError(
                f"unsafe-{label}-path", f"{label.title()} root does not exist"
            ) from error
        if not resolved.is_dir():
            _fail(f"unsafe-{label}-path", f"{label.title()} root must be a directory")
        if path.absolute() != resolved:
            _fail(f"unsafe-{label}-path", f"{label.title()} root contains an indirect path")
        return resolved

    def _initialize(self) -> None:
        version = cast(int, self._connection.execute("PRAGMA user_version").fetchone()[0])
        if version not in {0, self.SCHEMA_VERSION}:
            _fail("store-version-incompatible", "Run store schema version is unsupported")
        self._connection.executescript(
            """
            BEGIN IMMEDIATE;
            CREATE TABLE IF NOT EXISTS runs (
                run_ref TEXT PRIMARY KEY,
                request_ref TEXT NOT NULL UNIQUE,
                fingerprint TEXT NOT NULL,
                registration_ref TEXT NOT NULL,
                capability_id TEXT NOT NULL,
                owner_ref TEXT NOT NULL,
                owner_scope TEXT NOT NULL,
                state TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                document_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS run_events (
                run_ref TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                document_json TEXT NOT NULL,
                PRIMARY KEY (run_ref, sequence),
                FOREIGN KEY (run_ref) REFERENCES runs(run_ref) ON DELETE RESTRICT
            );
            CREATE TABLE IF NOT EXISTS provenance (
                provenance_ref TEXT PRIMARY KEY,
                owner_ref TEXT NOT NULL,
                document_sha256 TEXT NOT NULL,
                document_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS artifacts (
                artifact_ref TEXT PRIMARY KEY,
                run_ref TEXT NOT NULL,
                owner_ref TEXT NOT NULL,
                relative_path TEXT NOT NULL,
                provenance_ref TEXT NOT NULL,
                document_json TEXT NOT NULL,
                UNIQUE (run_ref, relative_path),
                FOREIGN KEY (run_ref) REFERENCES runs(run_ref) ON DELETE RESTRICT,
                FOREIGN KEY (provenance_ref)
                    REFERENCES provenance(provenance_ref) ON DELETE RESTRICT
            );
            CREATE INDEX IF NOT EXISTS run_owner_state_index ON runs(owner_ref, state);
            PRAGMA user_version = 1;
            COMMIT;
            """
        )

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @staticmethod
    def _effect(target: CapabilityDetail) -> dict[str, object]:
        effect = target.capability.effect
        return {
            "tier": effect.tier,
            "category": effect.category,
            "description": effect.description,
            "plan_required": effect.plan_required,
            "approval_required": effect.approval_required,
            "strong_confirmation_required": effect.strong_confirmation_required,
        }

    def _load_owned(self, run_ref: str, owner_ref: str) -> sqlite3.Row:
        _reference(run_ref, "run_ref")
        _reference(owner_ref, "owner_ref")
        row = self._connection.execute(
            "SELECT * FROM runs WHERE run_ref = ?", (run_ref,)
        ).fetchone()
        if row is None or cast(str, row["owner_ref"]) != owner_ref:
            _fail("run-not-found", "Owned run was not found")
        return cast(sqlite3.Row, row)

    def _validated_run(self, text: str) -> RunSnapshot:
        document = _document(text)
        _validated(self._contracts, "run-record.schema.json", document)
        return RunSnapshot.from_document(document)

    def create_run(
        self,
        *,
        request_ref: str,
        target: CapabilityDetail,
        owner: RunOwner,
        created_at: datetime,
        plan_ref: str | None = None,
    ) -> RunSnapshot:
        _reference(request_ref, "request_ref")
        _reference(target.registration_ref, "registration_ref")
        _reference(target.capability.capability_id, "capability_id")
        if target.capability.effect.tier not in {"R0", "R1"}:
            _fail("effect-policy-required", "R2-R4 run creation requires the policy runtime")
        if plan_ref is not None:
            _reference(plan_ref, "plan_ref")
        created = _timestamp(created_at, "created_at")
        immutable = {
            "request_ref": request_ref,
            "registration_ref": target.registration_ref,
            "capability_id": target.capability.capability_id,
            "effect": self._effect(target),
            "owner": {"owner_ref": owner.owner_ref, "scope": owner.scope},
            "plan_ref": plan_ref,
        }
        fingerprint = hashlib.sha256(_canonical(immutable).encode("utf-8")).hexdigest()
        run_digest = hashlib.sha256(
            "\0".join(
                (
                    request_ref,
                    target.registration_ref,
                    target.capability.capability_id,
                    owner.owner_ref,
                )
            ).encode("utf-8")
        ).hexdigest()
        run_ref = f"urn:materials-mcp:run:{run_digest}"
        record: dict[str, object] = {
            "contract": f"{self._contracts.canonical_base}run-record.schema.json",
            "profile_version": self._contracts.profile_version,
            "run_ref": run_ref,
            "capability_id": target.capability.capability_id,
            "effect": self._effect(target),
            "state": "queued",
            "sequence": 0,
            "owner": {"owner_ref": owner.owner_ref, "scope": owner.scope},
            "created_at": created,
            "updated_at": created,
            "links": {
                "status": f"{run_ref}:status",
                "result": f"{run_ref}:result",
                "cancel": f"{run_ref}:cancel",
            },
            "artifact_refs": [],
        }
        if plan_ref is not None:
            record["plan_ref"] = plan_ref
        _validated(self._contracts, "run-record.schema.json", record)
        rendered = _canonical(record)
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                existing = self._connection.execute(
                    "SELECT fingerprint, document_json FROM runs WHERE request_ref = ?",
                    (request_ref,),
                ).fetchone()
                if existing is not None:
                    if cast(str, existing["fingerprint"]) != fingerprint:
                        _fail(
                            "request-conflict",
                            "Request reference already identifies another run",
                        )
                    self._connection.execute("COMMIT")
                    return self._validated_run(cast(str, existing["document_json"]))
                self._connection.execute(
                    """INSERT INTO runs
                    (run_ref, request_ref, fingerprint, registration_ref, capability_id,
                     owner_ref, owner_scope, state, sequence, document_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        run_ref,
                        request_ref,
                        fingerprint,
                        target.registration_ref,
                        target.capability.capability_id,
                        owner.owner_ref,
                        owner.scope,
                        "queued",
                        0,
                        rendered,
                    ),
                )
                self._connection.execute(
                    "INSERT INTO run_events (run_ref, sequence, document_json) VALUES (?, ?, ?)",
                    (run_ref, 0, rendered),
                )
                self._connection.execute("COMMIT")
            except sqlite3.DatabaseError as error:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise RunStoreError("storage-failure", "Run creation was not persisted") from error
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise
        return RunSnapshot.from_document(record)

    def latest(self, run_ref: str, owner_ref: str) -> RunSnapshot:
        with self._lock:
            row = self._load_owned(run_ref, owner_ref)
            return self._validated_run(cast(str, row["document_json"]))

    def deltas(
        self,
        run_ref: str,
        owner_ref: str,
        *,
        after_sequence: int,
        limit: int = 100,
    ) -> tuple[RunSnapshot, ...]:
        if type(after_sequence) is not int or after_sequence < -1:
            _fail("invalid-sequence", "after_sequence must be at least -1")
        if type(limit) is not int or not 1 <= limit <= 256:
            _fail("invalid-limit", "Delta limit must be between 1 and 256")
        with self._lock:
            self._load_owned(run_ref, owner_ref)
            rows = self._connection.execute(
                """SELECT document_json FROM run_events
                WHERE run_ref = ? AND sequence > ? ORDER BY sequence LIMIT ?""",
                (run_ref, after_sequence, limit),
            ).fetchall()
            return tuple(self._validated_run(cast(str, row["document_json"])) for row in rows)

    def recover_incomplete(self, owner_ref: str, *, limit: int = 100) -> tuple[RunSnapshot, ...]:
        _reference(owner_ref, "owner_ref")
        if type(limit) is not int or not 1 <= limit <= 256:
            _fail("invalid-limit", "Recovery limit must be between 1 and 256")
        with self._lock:
            rows = self._connection.execute(
                """SELECT document_json FROM runs
                WHERE owner_ref = ? AND state IN ('queued', 'running')
                ORDER BY run_ref LIMIT ?""",
                (owner_ref, limit),
            ).fetchall()
            return tuple(self._validated_run(cast(str, row["document_json"])) for row in rows)

    def transition(
        self,
        run_ref: str,
        owner_ref: str,
        *,
        expected_sequence: int,
        state: str,
        updated_at: datetime,
        progress: tuple[float, str] | None = None,
        result_ref: str | None = None,
        error_ref: str | None = None,
    ) -> RunSnapshot:
        if type(expected_sequence) is not int or expected_sequence < 0:
            _fail("invalid-sequence", "Expected sequence must be non-negative")
        if state not in RUN_STATES:
            _fail("invalid-state", "Run state is invalid")
        updated = _timestamp(updated_at, "updated_at")
        if result_ref is not None:
            _reference(result_ref, "result_ref")
        if error_ref is not None:
            _reference(error_ref, "error_ref")
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                row = self._load_owned(run_ref, owner_ref)
                current_sequence = cast(int, row["sequence"])
                current_state = cast(str, row["state"])
                if current_sequence != expected_sequence:
                    _fail("sequence-conflict", "Run sequence changed before this transition")
                if current_state in TERMINAL_STATES:
                    _fail("terminal-run", "Terminal runs are immutable")
                allowed = (
                    {"running", "failed", "cancelled"}
                    if current_state == "queued"
                    else {"running", "succeeded", "failed", "cancelled"}
                )
                if state not in allowed:
                    _fail("invalid-transition", "Requested run transition is not allowed")
                record = _document(cast(str, row["document_json"]))
                previous_updated = _parse_timestamp(cast(str, record["updated_at"]))
                if _parse_timestamp(updated) < previous_updated:
                    _fail("time-regression", "Run update time cannot move backwards")
                record["state"] = state
                record["sequence"] = current_sequence + 1
                record["updated_at"] = updated
                if progress is not None:
                    fraction, message = progress
                    record["progress"] = {"fraction": fraction, "message": message}
                if state == "succeeded":
                    if result_ref is None:
                        _fail("missing-result", "Succeeded run requires result_ref")
                    record["result_ref"] = result_ref
                elif result_ref is not None:
                    _fail("unexpected-result", "result_ref is valid only for succeeded runs")
                if state == "failed":
                    if error_ref is None:
                        _fail("missing-error", "Failed run requires error_ref")
                    record["error_ref"] = error_ref
                elif error_ref is not None:
                    _fail("unexpected-error", "error_ref is valid only for failed runs")
                _validated(self._contracts, "run-record.schema.json", record)
                rendered = _canonical(record)
                sequence = record["sequence"]
                self._connection.execute(
                    """UPDATE runs SET state = ?, sequence = ?, document_json = ?
                    WHERE run_ref = ?""",
                    (state, sequence, rendered, run_ref),
                )
                self._connection.execute(
                    "INSERT INTO run_events (run_ref, sequence, document_json) VALUES (?, ?, ?)",
                    (run_ref, sequence, rendered),
                )
                self._connection.execute("COMMIT")
            except sqlite3.DatabaseError as error:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise RunStoreError(
                    "storage-failure", "Run transition was not persisted"
                ) from error
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise
        return RunSnapshot.from_document(record)

    def cancel(
        self,
        run_ref: str,
        owner_ref: str,
        *,
        expected_sequence: int,
        updated_at: datetime,
        message: str = "Cancellation recorded by the owning caller.",
    ) -> RunSnapshot:
        return self.transition(
            run_ref,
            owner_ref,
            expected_sequence=expected_sequence,
            state="cancelled",
            updated_at=updated_at,
            progress=(0.0, message),
        )

    def attach_artifact(
        self,
        run_ref: str,
        owner_ref: str,
        *,
        expected_sequence: int,
        updated_at: datetime,
        relative_path: str,
        uri: str,
        media_type: str,
        role: str,
        access_scope: str,
        provenance: dict[str, object],
    ) -> ArtifactAttachment:
        _reference(uri, "artifact uri")
        if role not in ARTIFACT_ROLES or access_scope not in ACCESS_SCOPES:
            _fail("invalid-artifact-metadata", "Artifact role or access scope is invalid")
        path = _contained_file(self._artifact_root, relative_path)
        size = path.stat().st_size
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        provenance_copy = cast(dict[str, object], json.loads(_canonical(provenance)))
        _validated(self._contracts, "provenance.schema.json", provenance_copy)
        provenance_ref = provenance_copy.get("provenance_ref")
        activity_ref = provenance_copy.get("activity_ref")
        if not isinstance(provenance_ref, str) or activity_ref != run_ref:
            _fail("provenance-ownership", "Provenance must identify the owning run activity")
        started_at = provenance_copy.get("started_at")
        ended_at = provenance_copy.get("ended_at")
        if not isinstance(started_at, str) or not isinstance(ended_at, str):
            _fail("invalid-provenance-time", "Provenance timestamps are missing")
        if _parse_timestamp(ended_at) < _parse_timestamp(started_at):
            _fail("invalid-provenance-time", "Provenance end time precedes start time")
        artifact_digest = hashlib.sha256(
            "\0".join((run_ref, uri, digest, provenance_ref)).encode("utf-8")
        ).hexdigest()
        artifact_ref = f"urn:materials-mcp:artifact:{artifact_digest}"
        artifact: dict[str, object] = {
            "artifact_ref": artifact_ref,
            "uri": uri,
            "media_type": media_type,
            "size_bytes": size,
            "sha256": digest,
            "role": role,
            "access_scope": access_scope,
            "provenance_ref": provenance_ref,
        }
        _validated(self._contracts, "artifact.schema.json", artifact)
        updated = _timestamp(updated_at, "updated_at")
        artifact_json = _canonical(artifact)
        provenance_json = _canonical(provenance_copy)
        provenance_sha = hashlib.sha256(provenance_json.encode("utf-8")).hexdigest()
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                row = self._load_owned(run_ref, owner_ref)
                if cast(int, row["sequence"]) != expected_sequence:
                    _fail("sequence-conflict", "Run sequence changed before artifact attachment")
                if cast(str, row["state"]) != "running":
                    _fail("invalid-artifact-state", "Artifacts attach only to running runs")
                existing = self._connection.execute(
                    """SELECT owner_ref, document_sha256 FROM provenance
                    WHERE provenance_ref = ?""",
                    (provenance_ref,),
                ).fetchone()
                if existing is not None and (
                    cast(str, existing["owner_ref"]) != owner_ref
                    or cast(str, existing["document_sha256"]) != provenance_sha
                ):
                    _fail("provenance-conflict", "Provenance reference is not reusable")
                self._connection.execute(
                    """INSERT OR IGNORE INTO provenance
                    (provenance_ref, owner_ref, document_sha256, document_json)
                    VALUES (?, ?, ?, ?)""",
                    (provenance_ref, owner_ref, provenance_sha, provenance_json),
                )
                self._connection.execute(
                    """INSERT INTO artifacts
                    (artifact_ref, run_ref, owner_ref, relative_path, provenance_ref, document_json)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        artifact_ref,
                        run_ref,
                        owner_ref,
                        relative_path,
                        provenance_ref,
                        artifact_json,
                    ),
                )
                record = _document(cast(str, row["document_json"]))
                previous_updated = _parse_timestamp(cast(str, record["updated_at"]))
                if _parse_timestamp(updated) < previous_updated:
                    _fail("time-regression", "Run update time cannot move backwards")
                artifact_refs = record.get("artifact_refs")
                if not isinstance(artifact_refs, list):
                    _fail("store-corruption", "Stored artifact references are invalid")
                cast(list[object], artifact_refs).append(artifact_ref)
                sequence = expected_sequence + 1
                record["sequence"] = sequence
                record["updated_at"] = updated
                _validated(self._contracts, "run-record.schema.json", record)
                rendered = _canonical(record)
                self._connection.execute(
                    "UPDATE runs SET sequence = ?, document_json = ? WHERE run_ref = ?",
                    (sequence, rendered, run_ref),
                )
                self._connection.execute(
                    "INSERT INTO run_events (run_ref, sequence, document_json) VALUES (?, ?, ?)",
                    (run_ref, sequence, rendered),
                )
                self._connection.execute("COMMIT")
            except sqlite3.DatabaseError as error:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise RunStoreError(
                    "storage-failure", "Artifact attachment was not persisted"
                ) from error
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise
        artifact_snapshot = ArtifactSnapshot(
            artifact_ref=artifact_ref,
            run_ref=run_ref,
            document=cast(Mapping[str, object], _freeze(artifact)),
            provenance=cast(Mapping[str, object], _freeze(provenance_copy)),
        )
        return ArtifactAttachment(artifact_snapshot, RunSnapshot.from_document(record))

    def artifact(self, artifact_ref: str, owner_ref: str) -> ArtifactSnapshot:
        _reference(artifact_ref, "artifact_ref")
        _reference(owner_ref, "owner_ref")
        with self._lock:
            row = self._connection.execute(
                """SELECT a.*, p.document_json AS provenance_json
                FROM artifacts a JOIN provenance p ON p.provenance_ref = a.provenance_ref
                WHERE a.artifact_ref = ?""",
                (artifact_ref,),
            ).fetchone()
            if row is None or cast(str, row["owner_ref"]) != owner_ref:
                _fail("artifact-not-found", "Owned artifact was not found")
            document = _document(cast(str, row["document_json"]))
            provenance = _document(cast(str, row["provenance_json"]))
            path = _contained_file(self._artifact_root, cast(str, row["relative_path"]))
            if path.stat().st_size != document.get("size_bytes") or hashlib.sha256(
                path.read_bytes()
            ).hexdigest() != document.get("sha256"):
                _fail("artifact-integrity", "Artifact bytes no longer match the durable record")
            _validated(self._contracts, "artifact.schema.json", document)
            _validated(self._contracts, "provenance.schema.json", provenance)
            return ArtifactSnapshot(
                artifact_ref=artifact_ref,
                run_ref=cast(str, row["run_ref"]),
                document=cast(Mapping[str, object], _freeze(document)),
                provenance=cast(Mapping[str, object], _freeze(provenance)),
            )
