from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import version
from typing import TYPE_CHECKING, Protocol, cast

from .dispatch import Dispatcher, DispatchFailure, DispatchRequest
from .errors import CommonsError, HostError
from .lifecycle import CapabilityDetail, LifecycleRegistry
from .operations import OperationName, OperationObserver, OperationOutcome
from .policy import AuthorizationReceipt, PolicySnapshot

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

_ABSOLUTE_REFERENCE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s]+$")


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


def _host_failure(code: str, operation: OperationName, next_action: str) -> dict[str, object]:
    return {
        "ok": False,
        "error": {
            "code": code,
            "stage": "internal" if operation != "execute" else "execution",
            "message": "The host operation failed closed.",
            "retryable": False,
            "next_action": next_action,
        },
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

    def discover(self, query: str = "", limit: int | None = None) -> dict[str, object]:
        started = self._observer.begin()
        try:
            cards = self._lifecycle.discover(query, limit=limit)
            result: dict[str, object] = {
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
            return _host_failure(error.code, "discover", "Correct the discovery request.")
        self._observe(started, operation="discover", outcome="success")
        return result

    def inspect(self, capability_id: str) -> dict[str, object]:
        started = self._observer.begin()
        try:
            detail = self._lifecycle.inspect(capability_id)
            capability = detail.capability
            result: dict[str, object] = {
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
            return _host_failure(error.code, "inspect", "Discover a registered capability.")
        self._observe(started, operation="inspect", outcome="success", capability_id=capability_id)
        return result

    async def activate(
        self, capability_id: str, lease_turns: int | None = None
    ) -> dict[str, object]:
        started = self._observer.begin()
        try:
            async with self._turn_lock:
                self._turn += 1
                turn = self._turn
                activation = self._lifecycle.activate(
                    capability_id, current_turn=turn, lease_turns=lease_turns
                )
            result: dict[str, object] = {
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
            return _host_failure(error.code, "activate", "Inspect the capability and lease policy.")
        self._observe(started, operation="activate", outcome="success", capability_id=capability_id)
        return result

    async def execute(
        self,
        registration_ref: str,
        capability_id: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
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
                return {"ok": False, "error": document}
            result = {"ok": True, "result": outcome.to_result()}
        except CommonsError as error:
            self._observe(
                started,
                operation="execute",
                outcome="failure",
                capability_id=capability_id,
                effect_tier=effect_tier,
                error_code=error.code,
            )
            return _host_failure(
                error.code, "execute", "Inspect, activate, and authorize the exact target."
            )
        except Exception:
            self._observe(
                started,
                operation="execute",
                outcome="failure",
                capability_id=capability_id,
                effect_tier=effect_tier,
                error_code="authorization-resolver-failed",
            )
            return _host_failure(
                "authorization-resolver-failed",
                "execute",
                "Inspect private operator diagnostics and repair the trusted resolver.",
            )
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
    except ModuleNotFoundError as error:  # pragma: no cover - exercised in a clean base install
        raise HostError(
            "mcp-sdk-unavailable",
            "Install the materials-mcp-commons[mcp-host] extra to create an MCP server",
        ) from error

    server: MCPServer[object] = MCPServer(
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
    return server
