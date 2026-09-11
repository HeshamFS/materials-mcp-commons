from __future__ import annotations

import pytest

from materials_mcp_commons import (
    LifecycleError,
    LifecyclePolicy,
    LifecycleRegistry,
    LoadedManifest,
)

DISCOVER = "https://schemas.autonomouslab.io/materials-mcp/engine/discover"
INSPECT = "https://schemas.autonomouslab.io/materials-mcp/engine/inspect"


def test_registration_is_exact_deterministic_and_idempotent(
    loaded_manifest: LoadedManifest,
) -> None:
    first_registry = LifecycleRegistry()
    first = first_registry.register(loaded_manifest)
    second = first_registry.register(loaded_manifest)
    independent = LifecycleRegistry().register(loaded_manifest)
    assert first == second == independent
    assert first.registration_ref.startswith("urn:materials-mcp:registration:")
    assert first_registry.registrations() == (first,)


def test_discovery_is_bounded_ranked_and_deterministic(
    loaded_manifest: LoadedManifest,
) -> None:
    registry = LifecycleRegistry()
    registry.register(loaded_manifest)
    all_cards = registry.discover()
    assert [card.capability_id for card in all_cards] == [DISCOVER, INSPECT]
    assert registry.discover("inspection metadata")[0].capability_id == INSPECT
    assert registry.discover("zzqv") == ()
    assert registry.discover(limit=1) == (all_cards[0],)
    with pytest.raises(LifecycleError, match="exceeds policy") as failure:
        registry.discover(limit=6)
    assert failure.value.code == "invalid-discovery-limit"


def test_inspection_returns_the_exact_immutable_snapshot(
    loaded_manifest: LoadedManifest,
) -> None:
    registry = LifecycleRegistry()
    registration = registry.register(loaded_manifest)
    detail = registry.inspect(INSPECT)
    assert detail.registration_ref == registration.registration_ref
    assert detail.plugin_id == loaded_manifest.plugin_id
    assert detail.capability == loaded_manifest.capabilities[1]
    with pytest.raises(LifecycleError) as failure:
        registry.inspect("https://invalid.example/negative/missing")
    assert failure.value.code == "capability-not-found"


def test_activation_renews_expires_and_evicts_deterministically(
    loaded_manifest: LoadedManifest,
) -> None:
    policy = LifecyclePolicy(
        max_discovery_cards=2,
        max_active_capabilities=1,
        default_lease_turns=3,
        max_lease_turns=5,
    )
    registry = LifecycleRegistry(policy)
    registry.register(loaded_manifest)
    discover = registry.activate(DISCOVER, current_turn=1)
    assert discover.expires_at_turn == 4

    inspect = registry.activate(INSPECT, current_turn=2, lease_turns=3)
    assert registry.active(current_turn=2) == (inspect,)
    renewed = registry.activate(INSPECT, current_turn=3, lease_turns=2)
    assert renewed.expires_at_turn == 5
    assert renewed.activation_ref != inspect.activation_ref
    assert registry.active(current_turn=5) == ()
    with pytest.raises(LifecycleError) as failure:
        registry.active(current_turn=4)
    assert failure.value.code == "turn-regression"


def test_active_capability_must_be_deactivated_before_unregistration(
    loaded_manifest: LoadedManifest,
) -> None:
    registry = LifecycleRegistry()
    registration = registry.register(loaded_manifest)
    activation = registry.activate(DISCOVER, current_turn=0)
    with pytest.raises(LifecycleError) as failure:
        registry.unregister(loaded_manifest.plugin_id)
    assert failure.value.code == "plugin-active"
    assert registry.deactivate(DISCOVER, current_turn=1) == activation
    assert registry.unregister(loaded_manifest.plugin_id) == registration
    assert registry.registrations() == ()
