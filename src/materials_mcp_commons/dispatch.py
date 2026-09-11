from __future__ import annotations

import hashlib
import inspect
import json
import math
import re
import sqlite3
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from threading import RLock
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, cast

from .contracts import ContractRegistry
from .errors import CommonsError, ContractError, DispatchError, LifecycleError, PolicyError
from .lifecycle import ActiveCapabilityTarget, LifecycleRegistry

if TYPE_CHECKING:
    from .policy import AuthorizationReceipt, PolicyEngine, PolicySnapshot

REFERENCE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s]+$")
ERROR_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{2,127}$")
ERROR_STAGES = frozenset(
    {
        "discovery",
        "inspection",
        "validation",
        "planning",
        "authorization",
        "execution",
        "observation",
        "retrieval",
        "projection",
        "internal",
    }
)
EVIDENCE_KINDS = frozenset({"input", "schema", "run", "artifact", "log", "policy", "other"})
MAX_DISPATCH_PAYLOAD_BYTES = 65_536
MAX_DISPATCH_PAYLOAD_DEPTH = 32
MAX_DISPATCH_PAYLOAD_NODES = 4_096


@dataclass
class _PayloadBudget:
    nodes: int = 0
    encoded_bytes: int = 0

    def add_node(self, depth: int) -> None:
        if depth > MAX_DISPATCH_PAYLOAD_DEPTH:
            raise DispatchError("payload-too-deep", "Dispatch payload exceeds the depth limit")
        self.nodes += 1
        if self.nodes > MAX_DISPATCH_PAYLOAD_NODES:
            raise DispatchError("payload-too-complex", "Dispatch payload exceeds the node limit")

    def add_bytes(self, amount: int) -> None:
        self.encoded_bytes += amount
        if self.encoded_bytes > MAX_DISPATCH_PAYLOAD_BYTES:
            raise DispatchError("payload-too-large", "Dispatch payload exceeds the byte limit")


def _snapshot_json(
    value: object, *, depth: int = 0, budget: _PayloadBudget | None = None
) -> object:
    active_budget = budget or _PayloadBudget()
    active_budget.add_node(depth)
    if type(value) is dict:
        active_budget.add_bytes(2)
        result: dict[str, object] = {}
        items = cast(dict[object, object], value).items()
        for index, (key, item) in enumerate(items):
            if type(key) is not str:
                raise DispatchError("invalid-json-value", "JSON object keys must be strings")
            if index:
                active_budget.add_bytes(1)
            active_budget.add_bytes(len(json.dumps(key, ensure_ascii=False).encode("utf-8")) + 1)
            result[key] = _snapshot_json(item, depth=depth + 1, budget=active_budget)
        return result
    if type(value) is list:
        active_budget.add_bytes(2)
        result_list: list[object] = []
        for index, item in enumerate(cast(list[object], value)):
            if index:
                active_budget.add_bytes(1)
            result_list.append(_snapshot_json(item, depth=depth + 1, budget=active_budget))
        return result_list
    if value is None:
        active_budget.add_bytes(4)
        return None
    if type(value) is str:
        active_budget.add_bytes(len(json.dumps(value, ensure_ascii=False).encode("utf-8")))
        return value
    if type(value) is bool:
        active_budget.add_bytes(4 if value else 5)
        return value
    if type(value) is int:
        active_budget.add_bytes(len(str(value).encode("ascii")))
        return value
    if isinstance(value, Decimal) and type(value) is Decimal:
        if not value.is_finite():
            raise DispatchError("invalid-json-value", "JSON numbers must be finite")
        active_budget.add_bytes(len(str(value).encode("ascii")))
        return value
    if isinstance(value, float) and type(value) is float:
        if not math.isfinite(value):
            raise DispatchError("invalid-json-value", "JSON numbers must be finite")
        active_budget.add_bytes(len(json.dumps(value, allow_nan=False).encode("ascii")))
        return value
    raise DispatchError("invalid-json-value", "Dispatch values must use JSON-compatible types")


def _freeze_json(value: object) -> object:
    if type(value) is dict:
        return MappingProxyType(
            {key: _freeze_json(item) for key, item in cast(dict[str, object], value).items()}
        )
    if type(value) is list:
        return tuple(_freeze_json(item) for item in cast(list[object], value))
    return value


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {str(key): _thaw_json(item) for key, item in mapping.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in cast(tuple[object, ...], value)]
    return value


def _absolute_reference(value: str, field_name: str) -> None:
    if REFERENCE_PATTERN.fullmatch(value) is None:
        raise DispatchError("invalid-reference", f"{field_name} must be an absolute reference")


@dataclass(frozen=True)
class DispatchRequest:
    request_ref: str
    registration_ref: str
    capability_id: str
    owner_ref: str
    current_turn: int
    occurred_at: datetime
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        for name, value in (
            ("request_ref", self.request_ref),
            ("registration_ref", self.registration_ref),
            ("capability_id", self.capability_id),
            ("owner_ref", self.owner_ref),
        ):
            if type(value) is not str:
                raise DispatchError("invalid-reference", f"{name} must be a string")
            _absolute_reference(value, name)
        if type(self.current_turn) is not int or self.current_turn < 0:
            raise DispatchError("invalid-turn", "current_turn must be a non-negative integer")
        if type(self.occurred_at) is not datetime or self.occurred_at.utcoffset() is None:
            raise DispatchError("invalid-time", "occurred_at must include a UTC offset")
        if not isinstance(self.payload, dict) or type(self.payload) is not dict:
            raise DispatchError("invalid-json-value", "payload must be a JSON object")
        snapshot = _snapshot_json(self.payload)
        object.__setattr__(self, "payload", cast(Mapping[str, object], _freeze_json(snapshot)))
        object.__setattr__(self, "occurred_at", self.occurred_at.astimezone(UTC))


@dataclass(frozen=True)
class HandlerRequest:
    request_ref: str
    registration_ref: str
    capability_id: str
    payload: Mapping[str, object]


Handler = Callable[[HandlerRequest], object]


@dataclass(frozen=True)
class HandlerBinding:
    registration_ref: str
    capability_id: str
    handler: Handler = field(repr=False, compare=False)


@dataclass(frozen=True)
class DispatchSuccess:
    request_ref: str
    registration_ref: str
    capability_id: str
    result: object

    def to_result(self) -> object:
        return _thaw_json(self.result)


@dataclass(frozen=True)
class DispatchFailure:
    request_ref: str
    registration_ref: str
    capability_id: str
    error: Mapping[str, object]

    def to_document(self) -> dict[str, object]:
        return cast(dict[str, object], _thaw_json(self.error))


@dataclass(frozen=True)
class _PreparedDispatch:
    target: ActiveCapabilityTarget
    binding: HandlerBinding
    handler_request: HandlerRequest


DispatchOutcome = DispatchSuccess | DispatchFailure


class Dispatcher:
    """Fail-closed typed dispatch over exact registered lifecycle snapshots."""

    def __init__(
        self,
        lifecycle: LifecycleRegistry,
        contracts: ContractRegistry,
        policy_engine: PolicyEngine | None = None,
    ) -> None:
        self._lifecycle = lifecycle
        self._contracts = contracts
        self._bindings: dict[tuple[str, str], HandlerBinding] = {}
        self._error_schema = f"{contracts.canonical_base}structured-error.schema.json"
        self._policy_engine = policy_engine
        self._lock = RLock()

    def bind(self, registration_ref: str, capability_id: str, handler: Handler) -> HandlerBinding:
        if not callable(handler):
            raise DispatchError("handler-not-callable", "Handler must be callable")
        try:
            target = self._lifecycle.resolve(capability_id, registration_ref)
        except LifecycleError as error:
            raise DispatchError(error.code, "Handler ownership validation failed") from error
        if target.manifest.profile_version != self._contracts.profile_version:
            raise DispatchError("profile-mismatch", "Handler target uses a different profile")
        if target.detail.capability.error_schema != self._error_schema:
            raise DispatchError(
                "incompatible-error-schema",
                "Handler target must use the profile structured-error contract",
            )
        key = (registration_ref, capability_id)
        with self._lock:
            if key in self._bindings:
                raise DispatchError("handler-already-bound", "Handler target is already bound")
            binding = HandlerBinding(registration_ref, capability_id, handler)
            self._bindings[key] = binding
            return binding

    def unbind(self, registration_ref: str, capability_id: str) -> HandlerBinding:
        key = (registration_ref, capability_id)
        with self._lock:
            binding = self._bindings.pop(key, None)
            if binding is None:
                raise DispatchError("handler-not-bound", "Handler target is not bound")
            return binding

    def bindings(self) -> tuple[HandlerBinding, ...]:
        with self._lock:
            return tuple(
                self._bindings[key]
                for key in sorted(self._bindings, key=lambda item: (item[1], item[0]))
            )

    @property
    def profile_version(self) -> str:
        return self._contracts.profile_version

    @staticmethod
    def _occurred_at(request: DispatchRequest) -> str:
        return request.occurred_at.isoformat(timespec="microseconds").replace("+00:00", "Z")

    def _failure(
        self,
        request: DispatchRequest,
        *,
        code: str,
        stage: str,
        cause: str,
        message: str,
        evidence_kind: str,
        evidence_summary: str,
        retryable: bool,
        next_action: str,
    ) -> DispatchFailure:
        if ERROR_CODE_PATTERN.fullmatch(code) is None or stage not in ERROR_STAGES:
            raise DispatchError("invalid-failure-metadata", "Failure metadata is invalid")
        if evidence_kind not in EVIDENCE_KINDS:
            raise DispatchError("invalid-failure-metadata", "Failure evidence kind is invalid")
        digest = hashlib.sha256(
            "\0".join(
                (
                    request.request_ref,
                    request.registration_ref,
                    request.capability_id,
                    stage,
                    code,
                )
            ).encode("utf-8")
        ).hexdigest()
        document: dict[str, object] = {
            "contract": self._error_schema,
            "profile_version": self._contracts.profile_version,
            "error_ref": f"urn:materials-mcp:error:{digest}",
            "code": code,
            "stage": stage,
            "cause": cause,
            "message": message,
            "evidence": [
                {
                    "kind": evidence_kind,
                    "ref": request.request_ref,
                    "summary": evidence_summary,
                }
            ],
            "retryable": retryable,
            "next_action": next_action,
            "occurred_at": self._occurred_at(request),
        }
        self._contracts.validate(self._error_schema, document)
        return DispatchFailure(
            request_ref=request.request_ref,
            registration_ref=request.registration_ref,
            capability_id=request.capability_id,
            error=cast(Mapping[str, object], _freeze_json(document)),
        )

    def _prepare(
        self,
        request: DispatchRequest,
        *,
        asynchronous: bool,
        policy: PolicySnapshot | None,
        authorization: AuthorizationReceipt | None,
    ) -> _PreparedDispatch | DispatchFailure:
        try:
            target = self._lifecycle.resolve_active(
                request.capability_id,
                request.registration_ref,
                current_turn=request.current_turn,
            )
        except LifecycleError:
            return self._failure(
                request,
                code="TARGET_UNAVAILABLE",
                stage="execution",
                cause="The exact registered capability is unavailable or inactive.",
                message="Dispatch stopped before invoking a handler.",
                evidence_kind="policy",
                evidence_summary="Lifecycle ownership or activation check failed.",
                retryable=False,
                next_action=(
                    "Inspect the registration and activate the exact capability before retrying."
                ),
            )
        capability = target.detail.capability
        if target.manifest.profile_version != self._contracts.profile_version:
            return self._failure(
                request,
                code="PROFILE_INCOMPATIBLE",
                stage="validation",
                cause="The capability profile differs from the dispatch registry profile.",
                message="Dispatch stopped at the compatibility boundary.",
                evidence_kind="schema",
                evidence_summary="Exact profile compatibility check failed.",
                retryable=False,
                next_action="Create a dispatcher with the exact profile used by the registration.",
            )
        if capability.effect.tier != "R0" and (
            self._policy_engine is None or policy is None or authorization is None
        ):
            return self._failure(
                request,
                code="EFFECT_POLICY_REQUIRED",
                stage="authorization",
                cause="Effectful dispatch requires an exact consumed authorization receipt.",
                message="Effectful dispatch stopped at the authorization boundary.",
                evidence_kind="policy",
                evidence_summary=f"Capability declares effect tier {capability.effect.tier}.",
                retryable=False,
                next_action=(
                    "Create and consume an exact plan-bound authorization grant before retrying."
                ),
            )
        if capability.supports_async and not asynchronous:
            return self._failure(
                request,
                code="ASYNC_DISPATCH_REQUIRED",
                stage="validation",
                cause="The capability declares asynchronous dispatch.",
                message="The synchronous dispatcher cannot invoke this capability.",
                evidence_kind="policy",
                evidence_summary="Manifest supports_async is true.",
                retryable=True,
                next_action="Use dispatch_async with the same validated request.",
            )
        with self._lock:
            binding = self._bindings.get((request.registration_ref, request.capability_id))
        if binding is None:
            return self._failure(
                request,
                code="HANDLER_NOT_BOUND",
                stage="execution",
                cause="No handler is bound to the exact registration and capability.",
                message="Dispatch stopped before execution.",
                evidence_kind="policy",
                evidence_summary="Exact handler ownership lookup returned no binding.",
                retryable=False,
                next_action="Bind an authorized handler to the exact registered capability.",
            )
        payload = cast(dict[str, object], _thaw_json(request.payload))
        try:
            target.manifest.validate(capability.input_schema, payload)
        except ContractError:
            return self._failure(
                request,
                code="INPUT_SCHEMA_REJECTED",
                stage="validation",
                cause="The request payload does not satisfy the declared input schema.",
                message="Dispatch stopped before invoking a handler.",
                evidence_kind="schema",
                evidence_summary="Declared capability input validation failed.",
                retryable=False,
                next_action="Correct the payload against the inspected input schema.",
            )
        if capability.effect.tier != "R0":
            assert self._policy_engine is not None
            assert policy is not None
            assert authorization is not None
            try:
                self._policy_engine.redeem_receipt(authorization, request, target.detail, policy)
            except PolicyError:
                return self._failure(
                    request,
                    code="AUTHORIZATION_DENIED",
                    stage="authorization",
                    cause=(
                        "The authorization receipt is absent, invalid, or does not bind "
                        "this exact request."
                    ),
                    message="Effectful dispatch stopped before invoking a handler.",
                    evidence_kind="policy",
                    evidence_summary=(
                        "Exact owner, target, input, effect, plan, and policy binding failed."
                    ),
                    retryable=False,
                    next_action="Create and consume a new exact authorization grant.",
                )
            except sqlite3.OperationalError as error:
                error_code = getattr(error, "sqlite_errorcode", None)
                base_code = error_code & 0xFF if isinstance(error_code, int) else None
                retryable = base_code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}
                return self._failure(
                    request,
                    code="AUTHORIZATION_DENIED",
                    stage="authorization",
                    cause="The authorization store was temporarily unavailable."
                    if retryable
                    else "The authorization store rejected the receipt.",
                    message="Effectful dispatch stopped before invoking a handler.",
                    evidence_kind="policy",
                    evidence_summary="Receipt redemption did not commit.",
                    retryable=retryable,
                    next_action="Retry after the authorization store lock clears."
                    if retryable
                    else "Inspect and repair the policy store before retrying.",
                )
            except Exception:
                return self._failure(
                    request,
                    code="AUTHORIZATION_DENIED",
                    stage="authorization",
                    cause="The authorization boundary rejected an invalid receipt or store state.",
                    message="Effectful dispatch stopped before invoking a handler.",
                    evidence_kind="policy",
                    evidence_summary="Receipt redemption failed closed.",
                    retryable=False,
                    next_action=(
                        "Inspect the policy store and create a new exact authorization grant."
                    ),
                )
        handler_request = HandlerRequest(
            request_ref=request.request_ref,
            registration_ref=request.registration_ref,
            capability_id=request.capability_id,
            payload=cast(Mapping[str, object], _freeze_json(payload)),
        )
        return _PreparedDispatch(target, binding, handler_request)

    def _success_or_failure(
        self, request: DispatchRequest, prepared: _PreparedDispatch, result: object
    ) -> DispatchOutcome:
        try:
            snapshot = _snapshot_json(result)
            prepared.target.manifest.validate(
                prepared.target.detail.capability.result_schema, snapshot
            )
        except (ContractError, DispatchError):
            return self._failure(
                request,
                code="RESULT_SCHEMA_REJECTED",
                stage="validation",
                cause="The handler result does not satisfy the declared result schema.",
                message="An invalid handler result was withheld.",
                evidence_kind="schema",
                evidence_summary="Declared capability result validation failed.",
                retryable=False,
                next_action="Correct the handler to return the inspected result contract.",
            )
        return DispatchSuccess(
            request_ref=request.request_ref,
            registration_ref=request.registration_ref,
            capability_id=request.capability_id,
            result=_freeze_json(snapshot),
        )

    def dispatch(
        self,
        request: DispatchRequest,
        *,
        policy: PolicySnapshot | None = None,
        authorization: AuthorizationReceipt | None = None,
    ) -> DispatchOutcome:
        prepared = self._prepare(
            request, asynchronous=False, policy=policy, authorization=authorization
        )
        if isinstance(prepared, DispatchFailure):
            return prepared
        try:
            result = prepared.binding.handler(prepared.handler_request)
        except CommonsError:
            return self._failure(
                request,
                code="HANDLER_REJECTED",
                stage="execution",
                cause="The handler rejected the validated request.",
                message="The handler did not produce a result.",
                evidence_kind="other",
                evidence_summary="A typed handler failure was contained.",
                retryable=False,
                next_action="Review capability state and inputs before retrying.",
            )
        except Exception:
            return self._failure(
                request,
                code="HANDLER_FAILED",
                stage="execution",
                cause="The handler failed without a safe public diagnostic.",
                message="The handler failure was contained and its raw details were withheld.",
                evidence_kind="other",
                evidence_summary="An untrusted handler exception was contained.",
                retryable=False,
                next_action="Inspect private operator diagnostics and repair the handler.",
            )
        if inspect.isawaitable(result):
            if inspect.iscoroutine(result):
                cast(Any, result).close()
            return self._failure(
                request,
                code="HANDLER_MODE_MISMATCH",
                stage="validation",
                cause="A synchronous capability handler returned an awaitable.",
                message="The mismatched handler result was withheld.",
                evidence_kind="policy",
                evidence_summary="Handler return mode differs from the manifest declaration.",
                retryable=False,
                next_action="Bind a synchronous handler or correct the manifest contract.",
            )
        return self._success_or_failure(request, prepared, result)

    async def dispatch_async(
        self,
        request: DispatchRequest,
        *,
        policy: PolicySnapshot | None = None,
        authorization: AuthorizationReceipt | None = None,
    ) -> DispatchOutcome:
        prepared = self._prepare(
            request, asynchronous=True, policy=policy, authorization=authorization
        )
        if isinstance(prepared, DispatchFailure):
            return prepared
        try:
            pending = prepared.binding.handler(prepared.handler_request)
            if prepared.target.detail.capability.supports_async:
                if not inspect.isawaitable(pending):
                    return self._failure(
                        request,
                        code="HANDLER_MODE_MISMATCH",
                        stage="validation",
                        cause="An asynchronous capability handler returned synchronously.",
                        message="The mismatched handler result was withheld.",
                        evidence_kind="policy",
                        evidence_summary=(
                            "Handler return mode differs from the manifest declaration."
                        ),
                        retryable=False,
                        next_action=(
                            "Bind an asynchronous handler or correct the manifest contract."
                        ),
                    )
                result = await cast(Awaitable[object], pending)
            else:
                if inspect.isawaitable(pending):
                    if inspect.iscoroutine(pending):
                        cast(Any, pending).close()
                    return self._failure(
                        request,
                        code="HANDLER_MODE_MISMATCH",
                        stage="validation",
                        cause="A synchronous capability handler returned an awaitable.",
                        message="The mismatched handler result was withheld.",
                        evidence_kind="policy",
                        evidence_summary=(
                            "Handler return mode differs from the manifest declaration."
                        ),
                        retryable=False,
                        next_action="Bind a synchronous handler or correct the manifest contract.",
                    )
                result = pending
        except CommonsError:
            return self._failure(
                request,
                code="HANDLER_REJECTED",
                stage="execution",
                cause="The handler rejected the validated request.",
                message="The handler did not produce a result.",
                evidence_kind="other",
                evidence_summary="A typed handler failure was contained.",
                retryable=False,
                next_action="Review capability state and inputs before retrying.",
            )
        except Exception:
            return self._failure(
                request,
                code="HANDLER_FAILED",
                stage="execution",
                cause="The handler failed without a safe public diagnostic.",
                message="The handler failure was contained and its raw details were withheld.",
                evidence_kind="other",
                evidence_summary="An untrusted handler exception was contained.",
                retryable=False,
                next_action="Inspect private operator diagnostics and repair the handler.",
            )
        return self._success_or_failure(request, prepared, result)
