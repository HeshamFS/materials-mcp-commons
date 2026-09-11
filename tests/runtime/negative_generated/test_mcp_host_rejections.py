from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from materials_mcp_commons import (
    DISCOVER_CAPABILITY_ID,
    ContractRegistry,
    Dispatcher,
    Effect,
    EngineMCPHost,
    HandlerRequest,
    HostError,
    LifecycleRegistry,
    LoadedManifest,
    OperationEvent,
    OperationObserver,
)


def test_generated_observer_sink_failure_is_isolated_and_counted(
    loaded_manifest: LoadedManifest,
    contract_registry: ContractRegistry,
) -> None:
    def rejected_sink(_: OperationEvent) -> None:
        raise RuntimeError("generated sink boundary failure")

    lifecycle = LifecycleRegistry()
    lifecycle.register(loaded_manifest)
    dispatcher = Dispatcher(lifecycle, contract_registry)
    observer = OperationObserver(rejected_sink)
    host = EngineMCPHost(
        lifecycle,
        dispatcher,
        owner_ref="urn:materials-mcp:owner:sink-boundary-test",
        observer=observer,
    )

    result = host.inspect(DISCOVER_CAPABILITY_ID)
    assert result["ok"] is True
    snapshot = observer.snapshot()
    assert snapshot.dropped_sink_events == 1
    assert snapshot.events[0].count == 1


def test_generated_effectful_tool_input_cannot_supply_authority(
    loaded_manifest: LoadedManifest,
    contract_registry: ContractRegistry,
) -> None:
    invoked = False

    def handler(_: HandlerRequest) -> object:
        nonlocal invoked
        invoked = True
        return {"cards": []}

    changed = replace(
        loaded_manifest.capabilities[0],
        effect=Effect(
            tier="R1",
            category="bounded-local",
            description="Generated effect used only to prove the host authorization boundary.",
            plan_required=False,
            approval_required=False,
            strong_confirmation_required=False,
        ),
    )
    manifest = replace(loaded_manifest, capabilities=(changed, *loaded_manifest.capabilities[1:]))
    lifecycle = LifecycleRegistry()
    registration = lifecycle.register(manifest)
    dispatcher = Dispatcher(lifecycle, contract_registry)
    dispatcher.bind(registration.registration_ref, DISCOVER_CAPABILITY_ID, handler)
    host = EngineMCPHost(
        lifecycle,
        dispatcher,
        owner_ref="urn:materials-mcp:owner:effect-boundary-test",
    )

    async def exercise() -> dict[str, object]:
        activated = await host.activate(DISCOVER_CAPABILITY_ID)
        assert activated["ok"] is True
        return await host.execute(
            registration.registration_ref,
            DISCOVER_CAPABILITY_ID,
            {"query": "generated-authority-input", "authorization": {"allow": True}},
        )

    result = asyncio.run(exercise())
    error = result["error"]
    assert isinstance(error, dict)
    assert error["code"] == "EFFECT_POLICY_REQUIRED"
    assert invoked is False


def test_generated_invalid_host_owner_is_rejected(
    loaded_manifest: LoadedManifest,
    contract_registry: ContractRegistry,
) -> None:
    lifecycle = LifecycleRegistry()
    lifecycle.register(loaded_manifest)
    dispatcher = Dispatcher(lifecycle, contract_registry)
    with pytest.raises(HostError) as failure:
        EngineMCPHost(lifecycle, dispatcher, owner_ref="not an absolute reference")
    assert failure.value.code == "invalid-owner"
