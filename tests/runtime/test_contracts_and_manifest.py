from __future__ import annotations

import hashlib
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from materials_mcp_commons import ContractRegistry, LifecyclePolicy, LoadedManifest
from tests.contracts.support import load_json
from tests.runtime.conftest import PACKAGE_ROOT, PROFILE_ROOT, PUBLIC_ROOT


def test_exact_profile_registry_is_complete_and_offline(
    contract_registry: ContractRegistry,
) -> None:
    assert contract_registry.profile_version == "0.2.0"
    assert contract_registry.canonical_base.endswith("/0.2.0/")
    assert len(contract_registry.schema_ids) == 19
    context = load_json(
        PUBLIC_ROOT / "tests" / "contracts" / "profile-0.2.0" / "context-manifest.json"
    )
    contract_registry.validate(str(context["contract"]), context)
    policy = LifecyclePolicy.from_context_manifest(context)
    assert policy == LifecyclePolicy(
        max_discovery_cards=5,
        max_active_capabilities=8,
        default_lease_turns=20,
        max_lease_turns=100,
    )


def test_real_engine_manifest_loads_as_an_immutable_snapshot(
    loaded_manifest: LoadedManifest,
) -> None:
    assert loaded_manifest.plugin_id == "https://schemas.autonomouslab.io/materials-mcp/engine"
    assert loaded_manifest.plugin_version == "0.1.0-alpha.5"
    assert loaded_manifest.publisher_name == "Hesham Salama"
    assert loaded_manifest.license_expression == "Apache-2.0"
    assert len(loaded_manifest.capabilities) == 2
    assert len(loaded_manifest.schema_resources) == 4
    assert (
        loaded_manifest.manifest_sha256
        == hashlib.sha256((PACKAGE_ROOT / "manifest.json").read_bytes()).hexdigest()
    )
    with pytest.raises(FrozenInstanceError):
        loaded_manifest.name = "changed"  # type: ignore[misc]


def test_manifest_declares_only_actual_engine_control_behavior(
    loaded_manifest: LoadedManifest,
) -> None:
    assert [
        capability.capability_id.rsplit("/", 1)[-1] for capability in loaded_manifest.capabilities
    ] == [
        "discover",
        "inspect",
    ]
    assert all(capability.effect.tier == "R0" for capability in loaded_manifest.capabilities)
    assert all(not capability.supports_async for capability in loaded_manifest.capabilities)
    assert {resource.role for resource in loaded_manifest.schema_resources} == {"input", "result"}


def test_profile_and_manifest_sources_are_regular_files() -> None:
    assert PROFILE_ROOT.is_dir() and not PROFILE_ROOT.is_symlink()
    assert PACKAGE_ROOT.is_dir() and not PACKAGE_ROOT.is_symlink()
    assert all(not path.is_symlink() for path in PROFILE_ROOT.rglob("*"))
    assert all(not path.is_symlink() for path in PACKAGE_ROOT.rglob("*"))
    assert isinstance(Path(PACKAGE_ROOT), Path)
