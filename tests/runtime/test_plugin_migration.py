from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from materials_mcp_commons import (
    DISCOVER_CAPABILITY_ID,
    ContractRegistry,
    Dispatcher,
    DispatchRequest,
    DispatchSuccess,
    EngineControlHandlers,
    LifecycleRegistry,
    ManifestLoader,
    assess_plugin_migration,
)
from materials_mcp_commons.contracts import load_json_object

PUBLIC_ROOT = Path(__file__).parents[2]
SOURCE_PACKAGE = PUBLIC_ROOT / "tests/runtime/positive-project/engine-lifecycle-profile-0.1.0"
TARGET_PACKAGE = PUBLIC_ROOT / "tests/runtime/positive-project/engine-lifecycle"


def test_profile_0_1_package_dispatches_actual_engine_control_behavior() -> None:
    contracts = ContractRegistry.from_directory(PUBLIC_ROOT / "schemas/0.1.0", "0.1.0")
    manifest = ManifestLoader(contracts).load(SOURCE_PACKAGE)
    lifecycle = LifecycleRegistry()
    registration = lifecycle.register(manifest)
    controls = EngineControlHandlers(lifecycle)
    dispatcher = Dispatcher(lifecycle, contracts)
    dispatcher.bind(registration.registration_ref, DISCOVER_CAPABILITY_ID, controls.discover)
    lifecycle.activate(DISCOVER_CAPABILITY_ID, current_turn=0)

    result = dispatcher.dispatch(
        DispatchRequest(
            request_ref="urn:materials-mcp:request:profile-0.1.0-discovery",
            registration_ref=registration.registration_ref,
            capability_id=DISCOVER_CAPABILITY_ID,
            owner_ref="urn:materials-mcp:owner:conformance",
            current_turn=1,
            occurred_at=datetime(2026, 9, 11, 12, 0, tzinfo=UTC),
            payload={"limit": 1},
        )
    )
    assert isinstance(result, DispatchSuccess)
    document = cast(dict[str, object], result.to_result())
    cards = cast(list[dict[str, object]], document["cards"])
    assert cards[0]["capability_id"] == DISCOVER_CAPABILITY_ID


def test_actual_engine_control_profile_migration_passes() -> None:
    source_contracts = ContractRegistry.from_directory(PUBLIC_ROOT / "schemas/0.1.0", "0.1.0")
    target_contracts = ContractRegistry.from_directory(PUBLIC_ROOT / "schemas/0.2.0", "0.2.0")
    compatibility = load_json_object(
        PUBLIC_ROOT / "tests/contracts/profile-0.2.0/profile-compatibility.json"
    )
    first = assess_plugin_migration(
        source_package_root=SOURCE_PACKAGE,
        target_package_root=TARGET_PACKAGE,
        source_contracts=source_contracts,
        target_contracts=target_contracts,
        compatibility_document=compatibility,
    )
    second = assess_plugin_migration(
        source_package_root=SOURCE_PACKAGE,
        target_package_root=TARGET_PACKAGE,
        source_contracts=source_contracts,
        target_contracts=target_contracts,
        compatibility_document=compatibility,
    )
    assert first.result == "pass"
    assert first.to_json() == second.to_json()
    assert all(cast(dict[str, bool], first.to_document()["checks"]).values())
