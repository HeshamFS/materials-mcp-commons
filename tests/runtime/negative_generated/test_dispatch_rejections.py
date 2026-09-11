from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

import pytest

from materials_mcp_commons import (
    DISCOVER_CAPABILITY_ID,
    ContractRegistry,
    Dispatcher,
    DispatchError,
    DispatchFailure,
    DispatchRequest,
    DispatchSuccess,
    Effect,
    HandlerRequest,
    LifecycleRegistry,
    LoadedManifest,
)

NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)


def _request(
    registration_ref: str,
    payload: dict[str, object],
    *,
    turn: int = 1,
) -> DispatchRequest:
    return DispatchRequest(
        request_ref=f"urn:materials-mcp:negative-request:{turn:064x}",
        registration_ref=registration_ref,
        capability_id=DISCOVER_CAPABILITY_ID,
        current_turn=turn,
        occurred_at=NOW,
        payload=payload,
    )


def _active_dispatcher(
    manifest: LoadedManifest,
    contracts: ContractRegistry,
    handler: Callable[[HandlerRequest], object],
) -> tuple[Dispatcher, str]:
    lifecycle = LifecycleRegistry()
    registration = lifecycle.register(manifest)
    dispatcher = Dispatcher(lifecycle, contracts)
    dispatcher.bind(registration.registration_ref, DISCOVER_CAPABILITY_ID, handler)
    lifecycle.activate(DISCOVER_CAPABILITY_ID, current_turn=0)
    return dispatcher, registration.registration_ref


def _valid_result(_: HandlerRequest) -> object:
    return {"cards": []}


def test_generated_request_rejects_mutable_non_json_and_implicit_time() -> None:
    with pytest.raises(DispatchError) as non_object:
        DispatchRequest(
            request_ref="urn:materials-mcp:negative-request:shape",
            registration_ref="urn:materials-mcp:registration:shape",
            capability_id=DISCOVER_CAPABILITY_ID,
            current_turn=0,
            occurred_at=NOW,
            payload=cast(dict[str, object], []),
        )
    assert non_object.value.code == "invalid-json-value"
    with pytest.raises(DispatchError) as non_finite:
        DispatchRequest(
            request_ref="urn:materials-mcp:negative-request:shape",
            registration_ref="urn:materials-mcp:registration:shape",
            capability_id=DISCOVER_CAPABILITY_ID,
            current_turn=0,
            occurred_at=NOW,
            payload={"value": float("nan")},
        )
    assert non_finite.value.code == "invalid-json-value"
    with pytest.raises(DispatchError) as naive_time:
        DispatchRequest(
            request_ref="urn:materials-mcp:negative-request:shape",
            registration_ref="urn:materials-mcp:registration:shape",
            capability_id=DISCOVER_CAPABILITY_ID,
            current_turn=0,
            occurred_at=datetime(2026, 9, 11),
            payload={},
        )
    assert naive_time.value.code == "invalid-time"


def test_generated_binding_ownership_duplicate_and_unbind_fail_closed(
    loaded_manifest: LoadedManifest,
    contract_registry: ContractRegistry,
) -> None:
    lifecycle = LifecycleRegistry()
    registration = lifecycle.register(loaded_manifest)
    dispatcher = Dispatcher(lifecycle, contract_registry)
    with pytest.raises(DispatchError) as mismatch:
        dispatcher.bind(
            "urn:materials-mcp:registration:wrong",
            DISCOVER_CAPABILITY_ID,
            _valid_result,
        )
    assert mismatch.value.code == "registration-mismatch"
    binding = dispatcher.bind(registration.registration_ref, DISCOVER_CAPABILITY_ID, _valid_result)
    with pytest.raises(DispatchError) as duplicate:
        dispatcher.bind(registration.registration_ref, DISCOVER_CAPABILITY_ID, _valid_result)
    assert duplicate.value.code == "handler-already-bound"
    assert dispatcher.unbind(registration.registration_ref, DISCOVER_CAPABILITY_ID) == binding
    with pytest.raises(DispatchError) as absent:
        dispatcher.unbind(registration.registration_ref, DISCOVER_CAPABILITY_ID)
    assert absent.value.code == "handler-not-bound"


def test_generated_inactive_expired_and_mismatched_targets_never_invoke_handler(
    loaded_manifest: LoadedManifest,
    contract_registry: ContractRegistry,
) -> None:
    invoked = 0

    def handler(_: HandlerRequest) -> object:
        nonlocal invoked
        invoked += 1
        return {"cards": []}

    lifecycle = LifecycleRegistry()
    registration = lifecycle.register(loaded_manifest)
    dispatcher = Dispatcher(lifecycle, contract_registry)
    dispatcher.bind(registration.registration_ref, DISCOVER_CAPABILITY_ID, handler)
    inactive = dispatcher.dispatch(_request(registration.registration_ref, {}, turn=0))
    lifecycle.activate(DISCOVER_CAPABILITY_ID, current_turn=0, lease_turns=1)
    expired = dispatcher.dispatch(_request(registration.registration_ref, {}, turn=1))
    mismatched = dispatcher.dispatch(_request("urn:materials-mcp:registration:wrong", {}, turn=1))
    codes = [
        cast(DispatchFailure, item).to_document()["code"]
        for item in (inactive, expired, mismatched)
    ]
    assert codes == [
        "TARGET_UNAVAILABLE",
        "TARGET_UNAVAILABLE",
        "TARGET_UNAVAILABLE",
    ]
    assert invoked == 0


def test_generated_input_and_result_schema_failures_withhold_values(
    loaded_manifest: LoadedManifest,
    contract_registry: ContractRegistry,
) -> None:
    dispatcher, registration_ref = _active_dispatcher(
        loaded_manifest, contract_registry, lambda _: {"not_cards": "private"}
    )
    bad_input = dispatcher.dispatch(_request(registration_ref, {"unknown": "private"}))
    bad_result = dispatcher.dispatch(_request(registration_ref, {}))
    assert isinstance(bad_input, DispatchFailure)
    assert bad_input.to_document()["code"] == "INPUT_SCHEMA_REJECTED"
    assert "private" not in str(bad_input.to_document())
    assert isinstance(bad_result, DispatchFailure)
    assert bad_result.to_document()["code"] == "RESULT_SCHEMA_REJECTED"
    assert "private" not in str(bad_result.to_document())


def test_generated_handler_exceptions_are_sanitized(
    loaded_manifest: LoadedManifest,
    contract_registry: ContractRegistry,
) -> None:
    def handler(_: HandlerRequest) -> object:
        raise RuntimeError("private-secret-token")

    dispatcher, registration_ref = _active_dispatcher(loaded_manifest, contract_registry, handler)
    outcome = dispatcher.dispatch(_request(registration_ref, {}))
    assert isinstance(outcome, DispatchFailure)
    document = outcome.to_document()
    assert document["code"] == "HANDLER_FAILED"
    assert "private-secret-token" not in str(document)


def test_generated_non_r0_capability_is_denied_before_handler(
    loaded_manifest: LoadedManifest,
    contract_registry: ContractRegistry,
) -> None:
    invoked = False

    def handler(_: HandlerRequest) -> object:
        nonlocal invoked
        invoked = True
        return {"cards": []}

    capability = loaded_manifest.capabilities[0]
    denied = replace(
        capability,
        effect=Effect(
            tier="R1",
            category="bounded-local",
            description="Generated negative effect-policy boundary.",
            plan_required=False,
            approval_required=False,
            strong_confirmation_required=False,
        ),
    )
    manifest = replace(
        loaded_manifest,
        capabilities=(denied, *loaded_manifest.capabilities[1:]),
    )
    dispatcher, registration_ref = _active_dispatcher(manifest, contract_registry, handler)
    outcome = dispatcher.dispatch(_request(registration_ref, {}))
    assert isinstance(outcome, DispatchFailure)
    assert outcome.to_document()["code"] == "EFFECT_POLICY_REQUIRED"
    assert not invoked


def test_generated_incompatible_error_contract_is_rejected_at_binding(
    loaded_manifest: LoadedManifest,
    contract_registry: ContractRegistry,
) -> None:
    capability = loaded_manifest.capabilities[0]
    incompatible = replace(capability, error_schema=capability.result_schema)
    manifest = replace(
        loaded_manifest,
        capabilities=(incompatible, *loaded_manifest.capabilities[1:]),
    )
    lifecycle = LifecycleRegistry()
    registration = lifecycle.register(manifest)
    dispatcher = Dispatcher(lifecycle, contract_registry)
    with pytest.raises(DispatchError) as failure:
        dispatcher.bind(registration.registration_ref, DISCOVER_CAPABILITY_ID, _valid_result)
    assert failure.value.code == "incompatible-error-schema"


def test_generated_sync_async_contract_mismatches_fail_closed(
    loaded_manifest: LoadedManifest,
    contract_registry: ContractRegistry,
) -> None:
    async def async_handler(_: HandlerRequest) -> object:
        return {"cards": []}

    sync_dispatcher, sync_ref = _active_dispatcher(
        loaded_manifest, contract_registry, async_handler
    )
    sync_outcome = sync_dispatcher.dispatch(_request(sync_ref, {}))
    assert isinstance(sync_outcome, DispatchFailure)
    assert sync_outcome.to_document()["code"] == "HANDLER_MODE_MISMATCH"

    async_capability = replace(loaded_manifest.capabilities[0], supports_async=True)
    async_manifest = replace(
        loaded_manifest,
        capabilities=(async_capability, *loaded_manifest.capabilities[1:]),
    )
    declared_async, async_ref = _active_dispatcher(async_manifest, contract_registry, _valid_result)
    wrong_entrypoint = declared_async.dispatch(_request(async_ref, {}))
    wrong_handler = asyncio.run(declared_async.dispatch_async(_request(async_ref, {})))
    assert isinstance(wrong_entrypoint, DispatchFailure)
    assert wrong_entrypoint.to_document()["code"] == "ASYNC_DISPATCH_REQUIRED"
    assert isinstance(wrong_handler, DispatchFailure)
    assert wrong_handler.to_document()["code"] == "HANDLER_MODE_MISMATCH"


def test_generated_declared_async_handler_dispatches_only_via_async_entrypoint(
    loaded_manifest: LoadedManifest,
    contract_registry: ContractRegistry,
) -> None:
    async def handler(_: HandlerRequest) -> object:
        return {"cards": []}

    async_capability = replace(loaded_manifest.capabilities[0], supports_async=True)
    manifest = replace(
        loaded_manifest,
        capabilities=(async_capability, *loaded_manifest.capabilities[1:]),
    )
    dispatcher, registration_ref = _active_dispatcher(manifest, contract_registry, handler)
    outcome = asyncio.run(dispatcher.dispatch_async(_request(registration_ref, {})))
    assert isinstance(outcome, DispatchSuccess)
    assert outcome.to_result() == {"cards": []}
