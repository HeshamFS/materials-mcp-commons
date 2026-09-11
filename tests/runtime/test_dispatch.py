from __future__ import annotations

from datetime import UTC, datetime
from types import MappingProxyType
from typing import cast

import pytest

from materials_mcp_commons import (
    DISCOVER_CAPABILITY_ID,
    INSPECT_CAPABILITY_ID,
    ContractRegistry,
    Dispatcher,
    DispatchFailure,
    DispatchRequest,
    DispatchSuccess,
    EngineControlHandlers,
    LifecycleRegistry,
    LoadedManifest,
)

NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)


def _request(
    registration_ref: str,
    capability_id: str,
    payload: dict[str, object],
    *,
    turn: int,
) -> DispatchRequest:
    return DispatchRequest(
        request_ref=f"urn:materials-mcp:request:{turn:064x}",
        registration_ref=registration_ref,
        capability_id=capability_id,
        owner_ref="urn:materials-mcp:owner:runtime-tests",
        current_turn=turn,
        occurred_at=NOW,
        payload=payload,
    )


def test_actual_engine_control_behaviors_dispatch_through_exact_contracts(
    loaded_manifest: LoadedManifest,
    contract_registry: ContractRegistry,
) -> None:
    lifecycle = LifecycleRegistry()
    registration = lifecycle.register(loaded_manifest)
    controls = EngineControlHandlers(lifecycle)
    dispatcher = Dispatcher(lifecycle, contract_registry)
    discover_binding = dispatcher.bind(
        registration.registration_ref, DISCOVER_CAPABILITY_ID, controls.discover
    )
    inspect_binding = dispatcher.bind(
        registration.registration_ref, INSPECT_CAPABILITY_ID, controls.inspect
    )
    lifecycle.activate(DISCOVER_CAPABILITY_ID, current_turn=0)
    lifecycle.activate(INSPECT_CAPABILITY_ID, current_turn=0)

    discovery = dispatcher.dispatch(
        _request(
            registration.registration_ref,
            DISCOVER_CAPABILITY_ID,
            {"limit": 2},
            turn=1,
        )
    )
    assert isinstance(discovery, DispatchSuccess)
    discovery_result = cast(dict[str, object], discovery.to_result())
    cards = cast(list[dict[str, object]], discovery_result["cards"])
    assert [card["capability_id"] for card in cards] == [
        DISCOVER_CAPABILITY_ID,
        INSPECT_CAPABILITY_ID,
    ]

    inspection = dispatcher.dispatch(
        _request(
            registration.registration_ref,
            INSPECT_CAPABILITY_ID,
            {"capability_id": DISCOVER_CAPABILITY_ID},
            turn=2,
        )
    )
    assert isinstance(inspection, DispatchSuccess)
    inspection_result = cast(dict[str, object], inspection.to_result())
    assert inspection_result["registration_ref"] == registration.registration_ref
    assert inspection_result["capability_id"] == DISCOVER_CAPABILITY_ID
    assert dispatcher.bindings() == (discover_binding, inspect_binding)


def test_request_and_success_snapshots_are_immutable_and_detached(
    loaded_manifest: LoadedManifest,
    contract_registry: ContractRegistry,
) -> None:
    lifecycle = LifecycleRegistry()
    registration = lifecycle.register(loaded_manifest)
    controls = EngineControlHandlers(lifecycle)
    dispatcher = Dispatcher(lifecycle, contract_registry)
    dispatcher.bind(registration.registration_ref, DISCOVER_CAPABILITY_ID, controls.discover)
    lifecycle.activate(DISCOVER_CAPABILITY_ID, current_turn=0)
    payload: dict[str, object] = {"query": "discover", "limit": 1}
    request = _request(registration.registration_ref, DISCOVER_CAPABILITY_ID, payload, turn=1)
    payload["limit"] = 2

    assert request.payload["limit"] == 1
    assert isinstance(request.payload, MappingProxyType)
    with pytest.raises(TypeError):
        request.payload["limit"] = 2  # type: ignore[index]

    outcome = dispatcher.dispatch(request)
    assert isinstance(outcome, DispatchSuccess)
    assert isinstance(outcome.result, MappingProxyType)
    first = cast(dict[str, object], outcome.to_result())
    cast(list[object], first["cards"]).clear()
    second = cast(dict[str, object], outcome.to_result())
    assert len(cast(list[object], second["cards"])) == 1


def test_structured_failure_is_deterministic_valid_and_detached(
    loaded_manifest: LoadedManifest,
    contract_registry: ContractRegistry,
) -> None:
    lifecycle = LifecycleRegistry()
    registration = lifecycle.register(loaded_manifest)
    request = _request(registration.registration_ref, DISCOVER_CAPABILITY_ID, {}, turn=0)
    dispatcher = Dispatcher(lifecycle, contract_registry)

    first = dispatcher.dispatch(request)
    second = dispatcher.dispatch(request)
    assert isinstance(first, DispatchFailure)
    assert isinstance(second, DispatchFailure)
    first_document = first.to_document()
    second_document = second.to_document()
    assert first_document == second_document
    assert first_document["code"] == "TARGET_UNAVAILABLE"
    assert first_document["occurred_at"] == "2026-09-11T12:00:00.000000Z"
    contract_registry.validate(cast(str, first_document["contract"]), first_document)
    cast(list[object], first_document["evidence"]).clear()
    assert len(cast(list[object], second.to_document()["evidence"])) == 1
