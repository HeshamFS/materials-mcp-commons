from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from types import MappingProxyType
from typing import NoReturn, Self, cast

from .contracts import ContractRegistry
from .dispatch import DispatchRequest
from .errors import ContractError, PolicyError
from .lifecycle import CapabilityDetail

REFERENCE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s]+$")
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
CONFIRMATION_STRENGTH = {"standard": 1, "strong": 2}


def _fail(code: str, message: str) -> NoReturn:
    raise PolicyError(code, message)


def _reference(value: str, field_name: str) -> None:
    if type(value) is not str or REFERENCE_PATTERN.fullmatch(value) is None:
        _fail("invalid-reference", f"{field_name} must be an absolute reference")


def _token(value: str, field_name: str) -> None:
    if type(value) is not str or TOKEN_PATTERN.fullmatch(value) is None or "*" in value:
        _fail("invalid-policy-token", f"{field_name} must be an exact token without wildcards")


def _time(value: datetime, field_name: str) -> datetime:
    if type(value) is not datetime or value.utcoffset() is None:
        _fail("invalid-time", f"{field_name} must include a UTC offset")
    return value.astimezone(UTC)


def _timestamp(value: datetime, field_name: str) -> str:
    return _time(value, field_name).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise PolicyError("audit-corruption", "Stored timestamp is invalid") from error
    if parsed.utcoffset() is None:
        _fail("audit-corruption", "Stored timestamp lacks an offset")
    return parsed.astimezone(UTC)


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {str(key): _plain(item) for key, item in mapping.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in cast(tuple[object, ...], value)]
    if isinstance(value, list):
        return [_plain(item) for item in cast(list[object], value)]
    return value


def _canonical(value: object) -> str:
    try:
        return json.dumps(
            _plain(value),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as error:
        raise PolicyError("invalid-json-value", "Policy value is not strict JSON") from error


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _freeze(value: object) -> object:
    if isinstance(value, dict):
        document = cast(dict[str, object], value)
        return MappingProxyType({key: _freeze(item) for key, item in document.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in cast(list[object], value))
    return value


@dataclass(frozen=True, order=True)
class Permission:
    permission: str
    scope: str

    def __post_init__(self) -> None:
        _token(self.permission, "permission")
        if type(self.scope) is not str or not self.scope.strip() or "*" in self.scope:
            _fail("invalid-permission-scope", "Permission scope must be exact and nonempty")

    def document(self) -> dict[str, object]:
        return {"permission": self.permission, "scope": self.scope}


@dataclass(frozen=True, order=True)
class QuotaLimit:
    kind: str
    limit: int

    def __post_init__(self) -> None:
        _token(self.kind, "quota kind")
        if type(self.limit) is not int or self.limit < 0:
            _fail("invalid-quota", "Quota limit must be a non-negative integer")


@dataclass(frozen=True, order=True)
class QuotaCharge:
    kind: str
    units: int

    def __post_init__(self) -> None:
        _token(self.kind, "quota kind")
        if type(self.units) is not int or self.units <= 0:
            _fail("invalid-quota", "Quota charge must be a positive integer")


@dataclass(frozen=True)
class PolicySnapshot:
    owner_ref: str
    permissions: tuple[Permission, ...]
    quotas: tuple[QuotaLimit, ...]

    def __post_init__(self) -> None:
        _reference(self.owner_ref, "owner_ref")
        if len(set(self.permissions)) != len(self.permissions):
            _fail("duplicate-permission", "Policy permissions must be unique")
        if len({quota.kind for quota in self.quotas}) != len(self.quotas):
            _fail("duplicate-quota", "Policy quota kinds must be unique")

    @property
    def sha256(self) -> str:
        return _digest(
            {
                "owner_ref": self.owner_ref,
                "permissions": [item.document() for item in sorted(self.permissions)],
                "quotas": [
                    {"kind": item.kind, "limit": item.limit} for item in sorted(self.quotas)
                ],
            }
        )


@dataclass(frozen=True)
class OperationPlan:
    plan_ref: str
    owner_ref: str
    registration_ref: str
    capability_id: str
    input_sha256: str
    document: Mapping[str, object]

    def to_document(self) -> dict[str, object]:
        return cast(dict[str, object], _plain(self.document))


@dataclass(frozen=True)
class ApprovalRecord:
    approval_ref: str
    plan_ref: str
    owner_ref: str
    approver_ref: str
    confirmation_kind: str
    approved_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class AuthorizationGrant:
    grant_ref: str
    request_ref: str
    registration_ref: str
    capability_id: str
    owner_ref: str
    input_sha256: str
    effect_tier: str
    plan_ref: str
    policy_sha256: str
    approval_ref: str | None
    charges: tuple[QuotaCharge, ...]


@dataclass(frozen=True)
class AuthorizationReceipt:
    receipt_ref: str
    grant_ref: str
    request_ref: str
    registration_ref: str
    capability_id: str
    owner_ref: str
    input_sha256: str
    effect_tier: str
    plan_ref: str
    policy_sha256: str
    consumed_at: datetime


@dataclass(frozen=True)
class AuditEvent:
    owner_ref: str
    sequence: int
    event_type: str
    subject_ref: str
    occurred_at: datetime
    previous_sha256: str
    event_sha256: str
    details: Mapping[str, object]


class PolicyEngine:
    """Durable exact-scope authorization, quota, and hash-chained audit runtime."""

    DATABASE_NAME = "materials-mcp-policy.sqlite3"
    SCHEMA_VERSION = 1

    def __init__(self, state_root: Path, contracts: ContractRegistry) -> None:
        if state_root.is_symlink():
            _fail("unsafe-state-path", "Policy state root cannot be a symbolic link")
        try:
            root = state_root.resolve(strict=True)
        except OSError as error:
            raise PolicyError("unsafe-state-path", "Policy state root does not exist") from error
        if not root.is_dir() or state_root.absolute() != root:
            _fail("unsafe-state-path", "Policy state root must be an explicit existing directory")
        database_path = root / self.DATABASE_NAME
        if database_path.exists() and database_path.is_symlink():
            _fail("unsafe-state-path", "Policy database cannot be a symbolic link")
        self._contracts = contracts
        self._lock = RLock()
        try:
            self._connection = sqlite3.connect(
                database_path, timeout=5.0, isolation_level=None, check_same_thread=False
            )
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA busy_timeout = 5000")
            self._initialize()
            self._verify_audit()
        except PolicyError:
            self._connection.close()
            raise
        except sqlite3.DatabaseError as error:
            self._connection.close()
            raise PolicyError("storage-failure", "Unable to open policy state") from error

    def _initialize(self) -> None:
        version = cast(int, self._connection.execute("PRAGMA user_version").fetchone()[0])
        if version not in {0, self.SCHEMA_VERSION}:
            _fail("store-version-incompatible", "Policy store schema version is unsupported")
        self._connection.executescript(
            """
            BEGIN IMMEDIATE;
            CREATE TABLE IF NOT EXISTS plans (
                plan_ref TEXT PRIMARY KEY, owner_ref TEXT NOT NULL, registration_ref TEXT NOT NULL,
                capability_id TEXT NOT NULL, input_sha256 TEXT NOT NULL, document_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS approvals (
                approval_ref TEXT PRIMARY KEY, plan_ref TEXT NOT NULL, owner_ref TEXT NOT NULL,
                approver_ref TEXT NOT NULL, confirmation_kind TEXT NOT NULL,
                approved_at TEXT NOT NULL, expires_at TEXT NOT NULL, used_grant_ref TEXT,
                FOREIGN KEY(plan_ref) REFERENCES plans(plan_ref) ON DELETE RESTRICT
            );
            CREATE TABLE IF NOT EXISTS grants (
                grant_ref TEXT PRIMARY KEY, document_json TEXT NOT NULL,
                consumed_at TEXT, receipt_ref TEXT
            );
            CREATE TABLE IF NOT EXISTS quota_usage (
                owner_ref TEXT NOT NULL, policy_sha256 TEXT NOT NULL, kind TEXT NOT NULL,
                used INTEGER NOT NULL, PRIMARY KEY(owner_ref, policy_sha256, kind)
            );
            CREATE TABLE IF NOT EXISTS audit_events (
                owner_ref TEXT NOT NULL, sequence INTEGER NOT NULL, event_type TEXT NOT NULL,
                subject_ref TEXT NOT NULL, occurred_at TEXT NOT NULL, previous_sha256 TEXT NOT NULL,
                event_sha256 TEXT NOT NULL, details_json TEXT NOT NULL,
                PRIMARY KEY(owner_ref, sequence), UNIQUE(event_sha256)
            );
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
    def input_sha256(request: DispatchRequest) -> str:
        return _digest(request.payload)

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

    def _audit(
        self,
        owner_ref: str,
        event_type: str,
        subject_ref: str,
        occurred_at: datetime,
        details: Mapping[str, object],
    ) -> AuditEvent:
        _reference(owner_ref, "owner_ref")
        _token(event_type, "event_type")
        _reference(subject_ref, "subject_ref")
        occurred = _timestamp(occurred_at, "occurred_at")
        row = self._connection.execute(
            "SELECT sequence, event_sha256 FROM audit_events WHERE owner_ref = ? "
            "ORDER BY sequence DESC LIMIT 1",
            (owner_ref,),
        ).fetchone()
        sequence = 0 if row is None else cast(int, row["sequence"]) + 1
        previous = "0" * 64 if row is None else cast(str, row["event_sha256"])
        details_json = _canonical(details)
        material = {
            "owner_ref": owner_ref,
            "sequence": sequence,
            "event_type": event_type,
            "subject_ref": subject_ref,
            "occurred_at": occurred,
            "previous_sha256": previous,
            "details": json.loads(details_json),
        }
        event_sha = _digest(material)
        self._connection.execute(
            "INSERT INTO audit_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                owner_ref,
                sequence,
                event_type,
                subject_ref,
                occurred,
                previous,
                event_sha,
                details_json,
            ),
        )
        return AuditEvent(
            owner_ref,
            sequence,
            event_type,
            subject_ref,
            _parse_time(occurred),
            previous,
            event_sha,
            cast(Mapping[str, object], _freeze(json.loads(details_json))),
        )

    def _verify_audit(self) -> None:
        rows = self._connection.execute(
            "SELECT * FROM audit_events ORDER BY owner_ref, sequence"
        ).fetchall()
        last: dict[str, tuple[int, str]] = {}
        for row in rows:
            owner = cast(str, row["owner_ref"])
            expected_sequence, expected_previous = (
                (0, "0" * 64) if owner not in last else (last[owner][0] + 1, last[owner][1])
            )
            details = json.loads(cast(str, row["details_json"]))
            material = {
                "owner_ref": owner,
                "sequence": cast(int, row["sequence"]),
                "event_type": cast(str, row["event_type"]),
                "subject_ref": cast(str, row["subject_ref"]),
                "occurred_at": cast(str, row["occurred_at"]),
                "previous_sha256": cast(str, row["previous_sha256"]),
                "details": details,
            }
            actual = _digest(material)
            if (
                cast(int, row["sequence"]) != expected_sequence
                or cast(str, row["previous_sha256"]) != expected_previous
                or cast(str, row["event_sha256"]) != actual
            ):
                _fail("audit-corruption", "Policy audit chain verification failed")
            last[owner] = (expected_sequence, actual)

    def _record_denial(
        self,
        owner_ref: str,
        subject_ref: str,
        occurred_at: datetime,
        code: str,
    ) -> None:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                self._audit(
                    owner_ref,
                    "authorization-denied",
                    subject_ref,
                    occurred_at,
                    {"code": code},
                )
                self._connection.execute("COMMIT")
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise

    def create_plan(
        self,
        request: DispatchRequest,
        target: CapabilityDetail,
        *,
        steps: Sequence[Mapping[str, object]],
        permissions: Sequence[Permission],
        expected_outputs: Sequence[Mapping[str, object]],
        estimates: Sequence[Mapping[str, object]] = (),
        risks: Sequence[str] = (),
        recovery: Mapping[str, object] | None = None,
    ) -> OperationPlan:
        if (
            request.registration_ref != target.registration_ref
            or request.capability_id != target.capability.capability_id
        ):
            _fail("target-mismatch", "Plan target does not match the exact dispatch request")
        if not permissions or len(set(permissions)) != len(permissions):
            _fail("invalid-permissions", "A plan requires unique exact permissions")
        approval_kind = (
            "strong"
            if target.capability.effect.tier == "R4"
            else "standard"
            if target.capability.effect.tier in {"R2", "R3"}
            else "none"
        )
        body: dict[str, object] = {
            "contract": f"{self._contracts.canonical_base}operation-plan.schema.json",
            "profile_version": self._contracts.profile_version,
            "capability_id": request.capability_id,
            "effect": self._effect(target),
            "created_at": _timestamp(request.occurred_at, "occurred_at"),
            "input_sha256": self.input_sha256(request),
            "steps": list(steps),
            "permissions": [item.document() for item in permissions],
            "approval": {
                "status": "required" if approval_kind != "none" else "not-required",
                "confirmation_kind": approval_kind,
                "prompt": "Confirm the exact inspected operation plan."
                if approval_kind != "none"
                else "No confirmation is required for this effect tier.",
            },
            "expected_outputs": list(expected_outputs),
            "estimates": list(estimates),
            "risks": list(risks),
        }
        if recovery is not None:
            body["recovery"] = dict(recovery)
        plan_identity = {
            "owner_ref": request.owner_ref,
            "registration_ref": request.registration_ref,
            "document": body,
        }
        plan_ref = f"urn:materials-mcp:plan:{_digest(plan_identity)}"
        body["plan_ref"] = plan_ref
        try:
            self._contracts.validate(cast(str, body["contract"]), body)
        except ContractError as error:
            raise PolicyError(
                "plan-contract-rejected", "Operation plan failed its contract"
            ) from error
        plan = OperationPlan(
            plan_ref,
            request.owner_ref,
            request.registration_ref,
            request.capability_id,
            cast(str, body["input_sha256"]),
            cast(Mapping[str, object], _freeze(body)),
        )
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                existing = self._connection.execute(
                    "SELECT owner_ref, registration_ref, capability_id, input_sha256, "
                    "document_json FROM plans WHERE plan_ref = ?",
                    (plan_ref,),
                ).fetchone()
                rendered = _canonical(body)
                values = (
                    request.owner_ref,
                    request.registration_ref,
                    request.capability_id,
                    plan.input_sha256,
                    rendered,
                )
                if existing is None:
                    self._connection.execute(
                        "INSERT INTO plans VALUES (?, ?, ?, ?, ?, ?)", (plan_ref, *values)
                    )
                    self._audit(
                        request.owner_ref,
                        "plan-created",
                        plan_ref,
                        request.occurred_at,
                        {"input_sha256": plan.input_sha256, "capability_id": request.capability_id},
                    )
                elif tuple(existing) != values:
                    _fail("plan-conflict", "Plan reference identifies different immutable content")
                self._connection.execute("COMMIT")
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise
        return plan

    def approve(
        self,
        plan: OperationPlan,
        *,
        approver_ref: str,
        confirmation_kind: str,
        approved_at: datetime,
        expires_at: datetime,
    ) -> ApprovalRecord:
        _reference(approver_ref, "approver_ref")
        approved = _time(approved_at, "approved_at")
        expires = _time(expires_at, "expires_at")
        if expires <= approved:
            _fail("invalid-approval-expiry", "Approval expiry must follow approval time")
        required = cast(dict[str, object], plan.to_document()["approval"])["confirmation_kind"]
        if required == "none" or CONFIRMATION_STRENGTH.get(
            confirmation_kind, 0
        ) < CONFIRMATION_STRENGTH.get(cast(str, required), 99):
            self._record_denial(plan.owner_ref, plan.plan_ref, approved, "approval-strength")
            _fail("approval-strength", "Approval confirmation does not satisfy the plan")
        material = {
            "plan_ref": plan.plan_ref,
            "owner_ref": plan.owner_ref,
            "approver_ref": approver_ref,
            "confirmation_kind": confirmation_kind,
            "approved_at": _timestamp(approved, "approved_at"),
            "expires_at": _timestamp(expires, "expires_at"),
        }
        approval_ref = f"urn:materials-mcp:approval:{_digest(material)}"
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                self._connection.execute(
                    "INSERT INTO approvals VALUES (?, ?, ?, ?, ?, ?, ?, NULL)",
                    (
                        approval_ref,
                        plan.plan_ref,
                        plan.owner_ref,
                        approver_ref,
                        confirmation_kind,
                        material["approved_at"],
                        material["expires_at"],
                    ),
                )
                self._audit(
                    plan.owner_ref,
                    "approval-recorded",
                    approval_ref,
                    approved,
                    {
                        "plan_ref": plan.plan_ref,
                        "confirmation_kind": confirmation_kind,
                        "expires_at": material["expires_at"],
                    },
                )
                self._connection.execute("COMMIT")
            except sqlite3.IntegrityError as error:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise PolicyError("approval-conflict", "Approval record already exists") from error
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise
        return ApprovalRecord(
            approval_ref,
            plan.plan_ref,
            plan.owner_ref,
            approver_ref,
            confirmation_kind,
            approved,
            expires,
        )

    def issue_grant(
        self,
        request: DispatchRequest,
        target: CapabilityDetail,
        policy: PolicySnapshot,
        plan: OperationPlan,
        *,
        issued_at: datetime,
        approval: ApprovalRecord | None = None,
        charges: Sequence[QuotaCharge] = (),
    ) -> AuthorizationGrant:
        issued = _time(issued_at, "issued_at")
        if request.owner_ref != policy.owner_ref or plan.owner_ref != request.owner_ref:
            self._record_denial(request.owner_ref, request.request_ref, issued, "owner-mismatch")
            _fail("owner-mismatch", "Request, plan, and policy owners must match exactly")
        if (plan.registration_ref, plan.capability_id, plan.input_sha256) != (
            request.registration_ref,
            request.capability_id,
            self.input_sha256(request),
        ):
            self._record_denial(request.owner_ref, request.request_ref, issued, "plan-mismatch")
            _fail("plan-mismatch", "Plan does not bind the exact request")
        if (target.registration_ref, target.capability.capability_id) != (
            request.registration_ref,
            request.capability_id,
        ):
            self._record_denial(request.owner_ref, request.request_ref, issued, "target-mismatch")
            _fail("target-mismatch", "Authorization target does not match the request")
        required = {
            Permission(cast(str, item["permission"]), cast(str, item["scope"]))
            for item in cast(list[dict[str, object]], plan.to_document()["permissions"])
        }
        if not required.issubset(set(policy.permissions)):
            self._record_denial(request.owner_ref, request.request_ref, issued, "permission-denied")
            _fail("permission-denied", "Policy lacks an exact permission required by the plan")
        tier = target.capability.effect.tier
        if tier in {"R2", "R3", "R4"}:
            if (
                approval is None
                or approval.plan_ref != plan.plan_ref
                or approval.owner_ref != request.owner_ref
                or approval.expires_at <= issued
            ):
                self._record_denial(
                    request.owner_ref, request.request_ref, issued, "approval-required"
                )
                _fail("approval-required", "A matching unexpired approval is required")
        elif approval is not None:
            self._record_denial(
                request.owner_ref, request.request_ref, issued, "unexpected-approval"
            )
            _fail("unexpected-approval", "This effect tier does not accept an approval")
        limits = {item.kind: item.limit for item in policy.quotas}
        aggregated: dict[str, int] = {}
        for charge in charges:
            aggregated[charge.kind] = aggregated.get(charge.kind, 0) + charge.units
        if any(kind not in limits or units > limits[kind] for kind, units in aggregated.items()):
            self._record_denial(request.owner_ref, request.request_ref, issued, "quota-denied")
            _fail("quota-denied", "Requested quota charge exceeds the immutable policy")
        charge_tuple = tuple(sorted(charges))
        material = {
            "request_ref": request.request_ref,
            "registration_ref": request.registration_ref,
            "capability_id": request.capability_id,
            "owner_ref": request.owner_ref,
            "input_sha256": self.input_sha256(request),
            "effect_tier": tier,
            "plan_ref": plan.plan_ref,
            "policy_sha256": policy.sha256,
            "approval_ref": None if approval is None else approval.approval_ref,
            "charges": [{"kind": item.kind, "units": item.units} for item in charge_tuple],
        }
        grant_ref = f"urn:materials-mcp:grant:{_digest(material)}"
        grant = AuthorizationGrant(
            grant_ref,
            request.request_ref,
            request.registration_ref,
            request.capability_id,
            request.owner_ref,
            self.input_sha256(request),
            tier,
            plan.plan_ref,
            policy.sha256,
            None if approval is None else approval.approval_ref,
            charge_tuple,
        )
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                plan_row = self._connection.execute(
                    "SELECT owner_ref, registration_ref, capability_id, input_sha256, "
                    "document_json FROM plans WHERE plan_ref = ?",
                    (plan.plan_ref,),
                ).fetchone()
                if plan_row is None or tuple(plan_row) != (
                    plan.owner_ref,
                    plan.registration_ref,
                    plan.capability_id,
                    plan.input_sha256,
                    _canonical(plan.document),
                ):
                    _fail("plan-invalid", "Operation plan is not durable and exact")
                if approval is not None:
                    approval_row = self._connection.execute(
                        "SELECT plan_ref, owner_ref, confirmation_kind, expires_at, "
                        "used_grant_ref FROM approvals WHERE approval_ref = ?",
                        (approval.approval_ref,),
                    ).fetchone()
                    if (
                        approval_row is None
                        or approval_row["plan_ref"] != plan.plan_ref
                        or approval_row["owner_ref"] != request.owner_ref
                        or approval_row["confirmation_kind"] != approval.confirmation_kind
                        or _parse_time(cast(str, approval_row["expires_at"])) <= issued
                        or approval_row["used_grant_ref"] is not None
                    ):
                        _fail(
                            "approval-invalid",
                            "Approval is not durable, exact, unexpired, and unused",
                        )
                self._connection.execute(
                    "INSERT INTO grants VALUES (?, ?, NULL, NULL)",
                    (grant_ref, _canonical(material)),
                )
                if approval is not None:
                    self._connection.execute(
                        "UPDATE approvals SET used_grant_ref = ? WHERE approval_ref = ?",
                        (grant_ref, approval.approval_ref),
                    )
                self._audit(
                    request.owner_ref,
                    "grant-issued",
                    grant_ref,
                    issued,
                    {"plan_ref": plan.plan_ref, "policy_sha256": policy.sha256},
                )
                self._connection.execute("COMMIT")
            except PolicyError as error:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                self._record_denial(request.owner_ref, request.request_ref, issued, error.code)
                raise
            except sqlite3.IntegrityError as error:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                self._record_denial(
                    request.owner_ref, request.request_ref, issued, "grant-conflict"
                )
                raise PolicyError("grant-conflict", "Authorization grant already exists") from error
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise
        return grant

    def consume(
        self,
        grant: AuthorizationGrant,
        request: DispatchRequest,
        target: CapabilityDetail,
        policy: PolicySnapshot,
        *,
        consumed_at: datetime,
    ) -> AuthorizationReceipt:
        consumed = _time(consumed_at, "consumed_at")
        self._assert_binding(grant, request, target, policy)
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._connection.execute(
                    "SELECT document_json, consumed_at FROM grants WHERE grant_ref = ?",
                    (grant.grant_ref,),
                ).fetchone()
                if row is None:
                    _fail("grant-not-found", "Authorization grant is not durable")
                expected_grant = {
                    "request_ref": grant.request_ref,
                    "registration_ref": grant.registration_ref,
                    "capability_id": grant.capability_id,
                    "owner_ref": grant.owner_ref,
                    "input_sha256": grant.input_sha256,
                    "effect_tier": grant.effect_tier,
                    "plan_ref": grant.plan_ref,
                    "policy_sha256": grant.policy_sha256,
                    "approval_ref": grant.approval_ref,
                    "charges": [{"kind": item.kind, "units": item.units} for item in grant.charges],
                }
                if row["document_json"] != _canonical(expected_grant):
                    _fail("grant-invalid", "Authorization grant is not durable and exact")
                if row["consumed_at"] is not None:
                    _fail("grant-consumed", "Authorization grant is single-use")
                if grant.approval_ref is not None:
                    approval = self._connection.execute(
                        "SELECT expires_at FROM approvals WHERE approval_ref = ?",
                        (grant.approval_ref,),
                    ).fetchone()
                    if (
                        approval is None
                        or _parse_time(cast(str, approval["expires_at"])) <= consumed
                    ):
                        _fail("approval-expired", "Authorization approval has expired")
                limits = {item.kind: item.limit for item in policy.quotas}
                for charge in grant.charges:
                    used_row = self._connection.execute(
                        "SELECT used FROM quota_usage WHERE owner_ref = ? "
                        "AND policy_sha256 = ? AND kind = ?",
                        (grant.owner_ref, grant.policy_sha256, charge.kind),
                    ).fetchone()
                    used = 0 if used_row is None else cast(int, used_row["used"])
                    if used + charge.units > limits[charge.kind]:
                        _fail("quota-denied", "Atomic quota reservation would exceed policy")
                receipt_material = {
                    "grant_ref": grant.grant_ref,
                    "consumed_at": _timestamp(consumed, "consumed_at"),
                }
                receipt_ref = f"urn:materials-mcp:receipt:{_digest(receipt_material)}"
                for charge in grant.charges:
                    self._connection.execute(
                        "INSERT INTO quota_usage VALUES (?, ?, ?, ?) "
                        "ON CONFLICT(owner_ref, policy_sha256, kind) "
                        "DO UPDATE SET used = used + excluded.used",
                        (grant.owner_ref, grant.policy_sha256, charge.kind, charge.units),
                    )
                self._connection.execute(
                    "UPDATE grants SET consumed_at = ?, receipt_ref = ? WHERE grant_ref = ?",
                    (_timestamp(consumed, "consumed_at"), receipt_ref, grant.grant_ref),
                )
                self._audit(
                    grant.owner_ref,
                    "grant-consumed",
                    receipt_ref,
                    consumed,
                    {
                        "grant_ref": grant.grant_ref,
                        "plan_ref": grant.plan_ref,
                        "charges": [
                            {"kind": item.kind, "units": item.units} for item in grant.charges
                        ],
                    },
                )
                self._connection.execute("COMMIT")
            except PolicyError as error:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                self._record_denial(grant.owner_ref, grant.request_ref, consumed, error.code)
                raise
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise
        return AuthorizationReceipt(
            receipt_ref,
            grant.grant_ref,
            grant.request_ref,
            grant.registration_ref,
            grant.capability_id,
            grant.owner_ref,
            grant.input_sha256,
            grant.effect_tier,
            grant.plan_ref,
            grant.policy_sha256,
            consumed,
        )

    def _assert_binding(
        self,
        authority: AuthorizationGrant | AuthorizationReceipt,
        request: DispatchRequest,
        target: CapabilityDetail,
        policy: PolicySnapshot,
    ) -> None:
        expected = (
            request.request_ref,
            request.registration_ref,
            request.capability_id,
            request.owner_ref,
            self.input_sha256(request),
            target.capability.effect.tier,
            policy.sha256,
        )
        actual = (
            authority.request_ref,
            authority.registration_ref,
            authority.capability_id,
            authority.owner_ref,
            authority.input_sha256,
            authority.effect_tier,
            authority.policy_sha256,
        )
        if (
            expected != actual
            or target.registration_ref != request.registration_ref
            or target.capability.capability_id != request.capability_id
        ):
            self._record_denial(
                request.owner_ref,
                request.request_ref,
                request.occurred_at,
                "authorization-mismatch",
            )
            _fail(
                "authorization-mismatch", "Authorization does not bind the exact request and target"
            )

    def verify_receipt(
        self,
        receipt: AuthorizationReceipt,
        request: DispatchRequest,
        target: CapabilityDetail,
        policy: PolicySnapshot,
    ) -> None:
        self._assert_binding(receipt, request, target, policy)
        with self._lock:
            row = self._connection.execute(
                "SELECT consumed_at, receipt_ref FROM grants WHERE grant_ref = ?",
                (receipt.grant_ref,),
            ).fetchone()
            if (
                row is None
                or row["receipt_ref"] != receipt.receipt_ref
                or _parse_time(cast(str, row["consumed_at"])) != receipt.consumed_at
            ):
                self._record_denial(
                    request.owner_ref,
                    request.request_ref,
                    request.occurred_at,
                    "authorization-invalid",
                )
                _fail("authorization-invalid", "Authorization receipt is not durable or exact")

    def verify_run_receipt(
        self,
        receipt: AuthorizationReceipt,
        *,
        request_ref: str,
        target: CapabilityDetail,
        owner_ref: str,
        plan_ref: str,
    ) -> None:
        expected = (
            request_ref,
            target.registration_ref,
            target.capability.capability_id,
            owner_ref,
            target.capability.effect.tier,
            plan_ref,
        )
        actual = (
            receipt.request_ref,
            receipt.registration_ref,
            receipt.capability_id,
            receipt.owner_ref,
            receipt.effect_tier,
            receipt.plan_ref,
        )
        if expected != actual:
            _fail("authorization-mismatch", "Authorization does not bind the exact run")
        with self._lock:
            row = self._connection.execute(
                "SELECT consumed_at, receipt_ref FROM grants WHERE grant_ref = ?",
                (receipt.grant_ref,),
            ).fetchone()
            if (
                row is None
                or row["receipt_ref"] != receipt.receipt_ref
                or _parse_time(cast(str, row["consumed_at"])) != receipt.consumed_at
            ):
                _fail("authorization-invalid", "Run authorization receipt is not durable")

    def audit_events(self, owner_ref: str) -> tuple[AuditEvent, ...]:
        _reference(owner_ref, "owner_ref")
        with self._lock:
            self._verify_audit()
            rows = self._connection.execute(
                "SELECT * FROM audit_events WHERE owner_ref = ? ORDER BY sequence", (owner_ref,)
            ).fetchall()
        return tuple(
            AuditEvent(
                owner_ref,
                cast(int, row["sequence"]),
                cast(str, row["event_type"]),
                cast(str, row["subject_ref"]),
                _parse_time(cast(str, row["occurred_at"])),
                cast(str, row["previous_sha256"]),
                cast(str, row["event_sha256"]),
                cast(Mapping[str, object], _freeze(json.loads(cast(str, row["details_json"])))),
            )
            for row in rows
        )
