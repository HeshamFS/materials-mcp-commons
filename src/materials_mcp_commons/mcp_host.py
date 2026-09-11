from __future__ import annotations

import asyncio
import hashlib
import re
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import version
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    Literal,
    NotRequired,
    Protocol,
    TypeAlias,
    cast,
    get_type_hints,
)

from typing_extensions import TypedDict

from .dispatch import Dispatcher, DispatchFailure, DispatchRequest
from .errors import CommonsError, HostError
from .lifecycle import CapabilityDetail, LifecycleRegistry
from .operations import OperationName, OperationObserver, OperationOutcome
from .policy import AuthorizationReceipt, PolicySnapshot

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

_ABSOLUTE_REFERENCE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s]+$")

PUBLIC_MCP_ERROR_CODES = (
    "ACTIVATION_FAILED",
    "ASYNC_DISPATCH_REQUIRED",
    "AUTHORIZATION_DENIED",
    "AUTHORIZATION_RESOLVER_FAILED",
    "DISCOVERY_FAILED",
    "EFFECT_POLICY_REQUIRED",
    "EXECUTION_FAILED",
    "HANDLER_FAILED",
    "HANDLER_MODE_MISMATCH",
    "HANDLER_NOT_BOUND",
    "HANDLER_REJECTED",
    "INPUT_SCHEMA_REJECTED",
    "INSPECTION_FAILED",
    "PROFILE_INCOMPATIBLE",
    "RESULT_SCHEMA_REJECTED",
    "TARGET_UNAVAILABLE",
)

_PublicErrorCode: TypeAlias = Literal[
    "ACTIVATION_FAILED",
    "ASYNC_DISPATCH_REQUIRED",
    "AUTHORIZATION_DENIED",
    "AUTHORIZATION_RESOLVER_FAILED",
    "DISCOVERY_FAILED",
    "EFFECT_POLICY_REQUIRED",
    "EXECUTION_FAILED",
    "HANDLER_FAILED",
    "HANDLER_MODE_MISMATCH",
    "HANDLER_NOT_BOUND",
    "HANDLER_REJECTED",
    "INPUT_SCHEMA_REJECTED",
    "INSPECTION_FAILED",
    "PROFILE_INCOMPATIBLE",
    "RESULT_SCHEMA_REJECTED",
    "TARGET_UNAVAILABLE",
]
_ErrorStage: TypeAlias = Literal[
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
]

_TOOL_INPUTS = {
    "materials_discover": frozenset({"query", "limit"}),
    "materials_inspect": frozenset({"capability_id"}),
    "materials_activate": frozenset({"capability_id", "lease_turns"}),
    "materials_execute": frozenset({"registration_ref", "capability_id", "payload"}),
}


class _JsonSchemaConstraints:
    """Dependency-free metadata consumed when the optional MCP stack builds schemas."""

    def __init__(self, **keywords: object) -> None:
        self._keywords = keywords

    def __get_pydantic_json_schema__(self, core_schema: object, handler: Any) -> dict[str, Any]:
        schema = cast(dict[str, Any], handler(core_schema))
        schema.update(self._keywords)
        return schema


_AbsoluteReference: TypeAlias = Annotated[
    str,
    _JsonSchemaConstraints(
        format="uri",
        pattern=r"^(?:https://[^\s]+|urn:[A-Za-z0-9][A-Za-z0-9()+,.:=@;$_!*'%/?#-]*)$",
        maxLength=2048,
    ),
]
_NonEmptyString: TypeAlias = Annotated[str, _JsonSchemaConstraints(minLength=1, maxLength=4096)]
_ShortText: TypeAlias = Annotated[str, _JsonSchemaConstraints(minLength=1, maxLength=16384)]
_OccurredAt: TypeAlias = Annotated[
    str,
    _JsonSchemaConstraints(
        format="date-time",
        pattern=(
            r"^[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])"
            r"T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]"
            r"(?:\.[0-9]+)?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])$"
        ),
    ),
]
_Extensions: TypeAlias = Annotated[
    dict[str, dict[str, object]],
    _JsonSchemaConstraints(
        maxProperties=32,
        propertyNames={
            "type": "string",
            "format": "uri",
            "pattern": r"^https://[^\s?#]+(?:/[^\s?#]*)?$",
            "maxLength": 2048,
        },
    ),
]


class _ErrorEvidence(TypedDict, closed=True):
    kind: Literal["input", "schema", "run", "artifact", "log", "policy", "other"]
    ref: NotRequired[_AbsoluteReference]
    summary: _NonEmptyString


class _StructuredError(TypedDict, closed=True):
    contract: Literal[
        "https://schemas.autonomouslab.io/materials-mcp/0.1.0/structured-error.schema.json",
        "https://schemas.autonomouslab.io/materials-mcp/0.2.0/structured-error.schema.json",
    ]
    profile_version: Literal["0.1.0", "0.2.0"]
    error_ref: _AbsoluteReference
    run_ref: NotRequired[_AbsoluteReference]
    code: _PublicErrorCode
    stage: _ErrorStage
    cause: _ShortText
    message: _ShortText
    evidence: Annotated[list[_ErrorEvidence], _JsonSchemaConstraints(minItems=1, maxItems=64)]
    retryable: bool
    next_action: _ShortText
    occurred_at: _OccurredAt
    extensions: NotRequired[_Extensions]


class _CapabilityCardOutput(TypedDict, closed=True):
    capability_id: str
    title: str
    description: str
    effect_tier: str
    supports_async: bool


class _FailureOutput(TypedDict, closed=True):
    ok: Literal[False]
    error: _StructuredError


class _DiscoverSuccess(TypedDict, closed=True):
    ok: Literal[True]
    cards: list[_CapabilityCardOutput]


class _InspectSuccess(TypedDict, closed=True):
    ok: Literal[True]
    registration_ref: str
    plugin_id: str
    plugin_version: str
    capability_id: str
    input_schema: str
    result_schema: str
    error_schema: str
    effect_tier: str
    supports_async: bool


class _ActivateSuccess(TypedDict, closed=True):
    ok: Literal[True]
    activation_ref: str
    capability_id: str
    registration_ref: str
    activated_at_turn: int
    expires_at_turn: int


class _ExecuteSuccess(TypedDict, closed=True):
    ok: Literal[True]
    result: dict[str, object]


_DiscoverOutput: TypeAlias = _DiscoverSuccess | _FailureOutput
_InspectOutput: TypeAlias = _InspectSuccess | _FailureOutput
_ActivateOutput: TypeAlias = _ActivateSuccess | _FailureOutput
_ExecuteOutput: TypeAlias = _ExecuteSuccess | _FailureOutput


class AuthorizationResolver(Protocol):
    """Trusted host callback for an exact effectful dispatch request."""

    def __call__(
        self, request: DispatchRequest, target: CapabilityDetail
    ) -> tuple[PolicySnapshot, AuthorizationReceipt]: ...


@dataclass(frozen=True)
class HostHealth:
    status: str
    profile_version: str
    registrations: int
    bindings: int
    metrics: Mapping[str, object]

    def to_document(self) -> dict[str, object]:
        return {
            "status": self.status,
            "profile_version": self.profile_version,
            "registrations": self.registrations,
            "bindings": self.bindings,
            "metrics": dict(self.metrics),
        }


class EngineMCPHost:
    """Four-tool MCP-facing adapter over explicit engine runtime instances."""

    def __init__(
        self,
        lifecycle: LifecycleRegistry,
        dispatcher: Dispatcher,
        *,
        owner_ref: str,
        authorization_resolver: AuthorizationResolver | None = None,
        observer: OperationObserver | None = None,
        initial_turn: int = 0,
        clock: Callable[[], datetime] | None = None,
        request_ref_factory: Callable[[], str] | None = None,
    ) -> None:
        if type(owner_ref) is not str or _ABSOLUTE_REFERENCE.fullmatch(owner_ref) is None:
            raise HostError("invalid-owner", "Host owner must be an absolute reference")
        if type(initial_turn) is not int or initial_turn < 0:
            raise HostError("invalid-turn", "Initial host turn must be non-negative")
        self._lifecycle = lifecycle
        self._dispatcher = dispatcher
        self._owner_ref = owner_ref
        self._profile_version = dispatcher.profile_version
        self._authorization_resolver = authorization_resolver
        self._observer = observer or OperationObserver()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._request_ref_factory = request_ref_factory or (lambda: f"urn:uuid:{uuid.uuid4()}")
        self._turn = initial_turn
        self._turn_lock = asyncio.Lock()

    def _host_failure(
        self, code: _PublicErrorCode, operation: OperationName, next_action: str
    ) -> _StructuredError:
        request_ref = self._request_ref_factory()
        occurred_at = (
            self._clock().astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
        )
        stage = cast(
            _ErrorStage,
            {
                "discover": "discovery",
                "inspect": "inspection",
                "activate": "authorization",
                "execute": "execution",
            }[operation],
        )
        digest = hashlib.sha256(
            "\0".join((request_ref, operation, stage, code)).encode("utf-8")
        ).hexdigest()
        return cast(
            _StructuredError,
            {
                "contract": (
                    "https://schemas.autonomouslab.io/materials-mcp/"
                    f"{self._profile_version}/structured-error.schema.json"
                ),
                "profile_version": self._profile_version,
                "error_ref": f"urn:materials-mcp:error:{digest}",
                "code": code,
                "stage": stage,
                "cause": f"The {operation} operation was rejected by the trusted engine boundary.",
                "message": "The host operation failed closed.",
                "evidence": [
                    {
                        "kind": "policy" if operation in {"activate", "execute"} else "other",
                        "ref": request_ref,
                        "summary": "The host contained an internal engine failure.",
                    }
                ],
                "retryable": False,
                "next_action": next_action,
                "occurred_at": occurred_at,
            },
        )

    def _next_request(
        self, registration_ref: str, capability_id: str, payload: dict[str, object]
    ) -> DispatchRequest:
        self._turn += 1
        turn = self._turn
        occurred_at = self._clock()
        request_ref = self._request_ref_factory()
        return DispatchRequest(
            request_ref=request_ref,
            registration_ref=registration_ref,
            capability_id=capability_id,
            owner_ref=self._owner_ref,
            current_turn=turn,
            occurred_at=occurred_at,
            payload=payload,
        )

    def _observe(
        self,
        started_ns: int,
        *,
        operation: OperationName,
        outcome: OperationOutcome,
        capability_id: str | None = None,
        effect_tier: str | None = None,
        error_code: str | None = None,
    ) -> None:
        self._observer.finish(
            started_ns,
            operation=operation,
            outcome=outcome,
            effect_tier=effect_tier,
            error_code=error_code,
            subject_ref=capability_id,
        )

    def discover(self, query: str = "", limit: int | None = None) -> _DiscoverOutput:
        started = self._observer.begin()
        try:
            cards = self._lifecycle.discover(query, limit=limit)
            result: _DiscoverOutput = {
                "ok": True,
                "cards": [
                    {
                        "capability_id": card.capability_id,
                        "title": card.title,
                        "description": card.description,
                        "effect_tier": card.effect_tier,
                        "supports_async": card.supports_async,
                    }
                    for card in cards
                ],
            }
        except CommonsError as error:
            self._observe(started, operation="discover", outcome="failure", error_code=error.code)
            return {
                "ok": False,
                "error": self._host_failure(
                    "DISCOVERY_FAILED", "discover", "Correct the discovery request."
                ),
            }
        self._observe(started, operation="discover", outcome="success")
        return result

    def inspect(self, capability_id: str) -> _InspectOutput:
        started = self._observer.begin()
        try:
            detail = self._lifecycle.inspect(capability_id)
            capability = detail.capability
            result: _InspectOutput = {
                "ok": True,
                "registration_ref": detail.registration_ref,
                "plugin_id": detail.plugin_id,
                "plugin_version": detail.plugin_version,
                "capability_id": capability.capability_id,
                "input_schema": capability.input_schema,
                "result_schema": capability.result_schema,
                "error_schema": capability.error_schema,
                "effect_tier": capability.effect.tier,
                "supports_async": capability.supports_async,
            }
        except CommonsError as error:
            self._observe(
                started,
                operation="inspect",
                outcome="failure",
                capability_id=capability_id,
                error_code=error.code,
            )
            return {
                "ok": False,
                "error": self._host_failure(
                    "INSPECTION_FAILED", "inspect", "Discover a registered capability."
                ),
            }
        self._observe(started, operation="inspect", outcome="success", capability_id=capability_id)
        return result

    async def activate(self, capability_id: str, lease_turns: int | None = None) -> _ActivateOutput:
        started = self._observer.begin()
        try:
            async with self._turn_lock:
                self._turn += 1
                turn = self._turn
                activation = self._lifecycle.activate(
                    capability_id, current_turn=turn, lease_turns=lease_turns
                )
            result: _ActivateOutput = {
                "ok": True,
                "activation_ref": activation.activation_ref,
                "capability_id": activation.capability_id,
                "registration_ref": activation.registration_ref,
                "activated_at_turn": activation.activated_at_turn,
                "expires_at_turn": activation.expires_at_turn,
            }
        except CommonsError as error:
            self._observe(
                started,
                operation="activate",
                outcome="failure",
                capability_id=capability_id,
                error_code=error.code,
            )
            return {
                "ok": False,
                "error": self._host_failure(
                    "ACTIVATION_FAILED",
                    "activate",
                    "Inspect the capability and lease policy.",
                ),
            }
        self._observe(started, operation="activate", outcome="success", capability_id=capability_id)
        return result

    async def execute(
        self,
        registration_ref: str,
        capability_id: str,
        payload: dict[str, object],
    ) -> _ExecuteOutput:
        started = self._observer.begin()
        effect_tier: str | None = None
        try:
            async with self._turn_lock:
                target = self._lifecycle.resolve(capability_id, registration_ref).detail
                effect_tier = target.capability.effect.tier
                request = self._next_request(registration_ref, capability_id, payload)
                policy = None
                authorization = None
                if effect_tier != "R0" and self._authorization_resolver is not None:
                    policy, authorization = self._authorization_resolver(request, target)
                outcome = await self._dispatcher.dispatch_async(
                    request, policy=policy, authorization=authorization
                )
            if isinstance(outcome, DispatchFailure):
                document = outcome.to_document()
                code = cast(str, document["code"])
                self._observe(
                    started,
                    operation="execute",
                    outcome="failure",
                    capability_id=capability_id,
                    effect_tier=effect_tier,
                    error_code=code,
                )
                return {"ok": False, "error": cast(_StructuredError, document)}
            result: _ExecuteOutput = {
                "ok": True,
                "result": cast(dict[str, object], outcome.to_result()),
            }
        except CommonsError as error:
            self._observe(
                started,
                operation="execute",
                outcome="failure",
                capability_id=capability_id,
                effect_tier=effect_tier,
                error_code=error.code,
            )
            return {
                "ok": False,
                "error": self._host_failure(
                    "EXECUTION_FAILED",
                    "execute",
                    "Inspect, activate, and authorize the exact target.",
                ),
            }
        except Exception:
            self._observe(
                started,
                operation="execute",
                outcome="failure",
                capability_id=capability_id,
                effect_tier=effect_tier,
                error_code="authorization-resolver-failed",
            )
            return {
                "ok": False,
                "error": self._host_failure(
                    "AUTHORIZATION_RESOLVER_FAILED",
                    "execute",
                    "Inspect private operator diagnostics and repair the trusted resolver.",
                ),
            }
        self._observe(
            started,
            operation="execute",
            outcome="success",
            capability_id=capability_id,
            effect_tier=effect_tier,
        )
        return result

    def health(self) -> HostHealth:
        metrics = self._observer.snapshot().to_document()
        return HostHealth(
            status="ready",
            profile_version=self._profile_version,
            registrations=len(self._lifecycle.registrations()),
            bindings=len(self._dispatcher.bindings()),
            metrics=metrics,
        )

    @property
    def observer(self) -> OperationObserver:
        return self._observer


def create_mcp_server(host: EngineMCPHost) -> MCPServer[object]:
    """Create the optional official-SDK server without importing MCP from the core package."""
    try:
        from mcp.server.mcpserver import MCPServer
        from mcp.server.mcpserver.exceptions import ToolError
    except ModuleNotFoundError as error:  # pragma: no cover - exercised in a clean base install
        raise HostError(
            "mcp-sdk-unavailable",
            "Install the materials-mcp-commons[mcp-host] extra to create an MCP server",
        ) from error

    profile_version = host.health().profile_version

    class _ClosedInputMCPServer(MCPServer[object]):
        def finalize_contracts(self) -> None:
            """Publish the direct discriminated envelope instead of an SDK union wrapper."""
            for name in _TOOL_INPUTS:
                tool = self._tool_manager.get_tool(name)
                if tool is None or tool.fn_metadata.output_schema is None:
                    raise HostError("invalid-mcp-tool", f"MCP tool {name} has no output contract")
                generated = tool.fn_metadata.output_schema
                result_schema = cast(
                    dict[str, Any], cast(dict[str, Any], generated["properties"])["result"]
                )
                variants = cast(list[dict[str, Any]], result_schema["anyOf"])
                definitions = cast(dict[str, Any], generated.get("$defs", {}))
                structured_error = cast(dict[str, Any], definitions["_StructuredError"])
                error_properties = cast(dict[str, Any], structured_error["properties"])
                error_properties["profile_version"] = {
                    "const": profile_version,
                    "type": "string",
                }
                error_properties["contract"] = {
                    "const": (
                        "https://schemas.autonomouslab.io/materials-mcp/"
                        f"{profile_version}/structured-error.schema.json"
                    ),
                    "type": "string",
                }
                tool.fn_metadata.output_schema = {
                    "$defs": definitions,
                    "oneOf": variants,
                    "title": f"{name}Output",
                    "type": "object",
                }
                tool.fn_metadata.output_model = get_type_hints(tool.fn)["return"]
                tool.fn_metadata.wrap_output = False

        async def list_tools(self) -> list[Any]:
            tools = await super().list_tools()
            for tool in tools:
                if tool.name in _TOOL_INPUTS:
                    tool.input_schema["additionalProperties"] = False
            return tools

        async def call_tool(
            self, name: str, arguments: dict[str, Any], context: Any | None = None
        ) -> Any:
            allowed = _TOOL_INPUTS.get(name)
            if allowed is not None:
                unexpected = sorted(set(arguments) - allowed)
                if unexpected:
                    joined = ", ".join(unexpected)
                    raise ToolError(
                        f"Error executing tool {name}: unexpected top-level arguments: {joined}"
                    )
            return await super().call_tool(name, arguments, context)

    server: MCPServer[object] = _ClosedInputMCPServer(
        name="materials-mcp-commons",
        description="Plugin-agnostic materials capability engine host.",
        version=version("materials-mcp-commons"),
    )
    server.tool(
        name="materials_discover",
        description="Discover bounded capability cards by query.",
        structured_output=True,
    )(host.discover)
    server.tool(
        name="materials_inspect",
        description="Inspect one registered capability contract and effect declaration.",
        structured_output=True,
    )(host.inspect)
    server.tool(
        name="materials_activate",
        description="Activate or renew one bounded capability lease.",
        structured_output=True,
    )(host.activate)
    server.tool(
        name="materials_execute",
        description="Execute one exact active capability through the engine policy boundary.",
        structured_output=True,
    )(host.execute)
    server.finalize_contracts()
    return server
