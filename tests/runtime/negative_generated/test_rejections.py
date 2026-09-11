from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from materials_mcp_commons import (
    ContractError,
    ContractRegistry,
    LifecycleError,
    LifecyclePolicy,
    LifecycleRegistry,
    LoadedManifest,
    ManifestLoader,
)
from materials_mcp_commons.contracts import sha256_file
from tests.runtime.conftest import PACKAGE_ROOT


def _generated_package(tmp_path: Path) -> Path:
    target = tmp_path / "generated-negative-package"
    shutil.copytree(PACKAGE_ROOT, target)
    return target


def _rewrite_manifest(package: Path, mutation: Callable[[dict[str, object]], None]) -> None:
    path = package / "manifest.json"
    parsed: object = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)
    value = cast(dict[str, object], parsed)
    mutation(value)
    path.write_text(json.dumps(value), encoding="utf-8")


def _rewrite_schema(
    package: Path,
    schema_name: str,
    mutation: Callable[[dict[str, object]], None],
) -> None:
    schema_path = package / "schemas" / schema_name
    parsed: object = json.loads(schema_path.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)
    schema = cast(dict[str, object], parsed)
    mutation(schema)
    schema_path.write_text(json.dumps(schema), encoding="utf-8")

    def update_digest(manifest: dict[str, object]) -> None:
        resources = manifest["schema_resources"]
        assert isinstance(resources, list)
        for item in cast(list[object], resources):
            assert isinstance(item, dict)
            resource = cast(dict[str, object], item)
            if resource["path"] == f"schemas/{schema_name}":
                resource["sha256"] = sha256_file(schema_path)

    _rewrite_manifest(package, update_digest)


def test_generated_digest_mismatch_is_rejected(
    tmp_path: Path, contract_registry: ContractRegistry
) -> None:
    package = _generated_package(tmp_path)

    def mutate(value: dict[str, object]) -> None:
        resources = value["schema_resources"]
        assert isinstance(resources, list) and isinstance(resources[0], dict)
        resources[0]["sha256"] = "0" * 64

    _rewrite_manifest(package, mutate)
    with pytest.raises(ContractError) as failure:
        ManifestLoader(contract_registry).load(package)
    assert failure.value.code == "package-schema-digest-mismatch"


def test_generated_duplicate_json_member_is_rejected(
    tmp_path: Path, contract_registry: ContractRegistry
) -> None:
    package = _generated_package(tmp_path)
    (package / "manifest.json").write_text(
        '{"contract":"first","contract":"second"}', encoding="utf-8"
    )
    with pytest.raises(ContractError) as failure:
        ManifestLoader(contract_registry).load(package)
    assert failure.value.code == "duplicate-key"


def test_generated_traversal_and_oversize_requests_are_rejected(
    contract_registry: ContractRegistry,
) -> None:
    loader = ManifestLoader(contract_registry)
    with pytest.raises(ContractError) as traversal:
        loader.load(PACKAGE_ROOT, "../manifest.json")
    assert traversal.value.code == "unsafe-path"
    with pytest.raises(ContractError) as oversized:
        ManifestLoader(contract_registry, max_manifest_bytes=1).load(PACKAGE_ROOT)
    assert oversized.value.code == "document-too-large"


def test_generated_manifest_profile_mismatch_is_rejected(
    tmp_path: Path, contract_registry: ContractRegistry
) -> None:
    package = _generated_package(tmp_path)

    def mutate(value: dict[str, object]) -> None:
        value["profile_version"] = "0.1.0"

    _rewrite_manifest(package, mutate)
    with pytest.raises(ContractError) as failure:
        ManifestLoader(contract_registry).load(package)
    assert failure.value.code == "schema-validation"


def test_generated_package_schema_identity_mismatch_is_rejected(
    tmp_path: Path, contract_registry: ContractRegistry
) -> None:
    package = _generated_package(tmp_path)

    def mutate(schema: dict[str, object]) -> None:
        schema["$id"] = "https://invalid.example/negative/schema.json"

    _rewrite_schema(package, "discovery-input.schema.json", mutate)
    with pytest.raises(ContractError) as failure:
        ManifestLoader(contract_registry).load(package)
    assert failure.value.code == "package-schema-identity-mismatch"


def test_generated_unresolved_package_reference_is_rejected(
    tmp_path: Path, contract_registry: ContractRegistry
) -> None:
    package = _generated_package(tmp_path)

    def mutate(schema: dict[str, object]) -> None:
        properties = schema["properties"]
        assert isinstance(properties, dict)
        properties["unresolvable"] = {"$ref": "https://invalid.example/negative/missing"}

    _rewrite_schema(package, "discovery-input.schema.json", mutate)
    with pytest.raises(ContractError) as failure:
        ManifestLoader(contract_registry).load(package)
    assert failure.value.code == "unresolved-package-reference"


def test_generated_capability_schema_role_mismatch_is_rejected(
    tmp_path: Path, contract_registry: ContractRegistry
) -> None:
    package = _generated_package(tmp_path)

    def mutate(value: dict[str, object]) -> None:
        resources = value["schema_resources"]
        assert isinstance(resources, list) and isinstance(resources[0], dict)
        resources[0]["role"] = "result"

    _rewrite_manifest(package, mutate)
    with pytest.raises(ContractError) as failure:
        ManifestLoader(contract_registry).load(package)
    assert failure.value.code == "capability-schema-role-mismatch"


def test_generated_symlinked_package_resource_is_rejected(
    tmp_path: Path, contract_registry: ContractRegistry
) -> None:
    package = _generated_package(tmp_path)
    resource = package / "schemas" / "discovery-input.schema.json"
    resource.unlink()
    try:
        os.symlink(
            PACKAGE_ROOT / "schemas" / "discovery-input.schema.json",
            resource,
        )
    except OSError as error:
        pytest.skip(f"File symlink creation unavailable: {error.winerror}")
    with pytest.raises(ContractError) as failure:
        ManifestLoader(contract_registry).load(package)
    assert failure.value.code == "unsafe-path"


def test_generated_registration_conflicts_fail_closed(
    loaded_manifest: LoadedManifest,
) -> None:
    registry = LifecycleRegistry()
    registry.register(loaded_manifest)
    changed = replace(loaded_manifest, plugin_version="0.1.0-alpha.2")
    with pytest.raises(LifecycleError) as failure:
        registry.register(changed)
    assert failure.value.code == "plugin-already-registered"

    second_identity = replace(
        loaded_manifest, plugin_id="https://invalid.example/negative/identity"
    )
    with pytest.raises(LifecycleError) as collision:
        registry.register(second_identity)
    assert collision.value.code == "capability-id-conflict"


@pytest.mark.parametrize(
    "policy",
    [
        LifecyclePolicy(max_discovery_cards=1),
        LifecyclePolicy(max_active_capabilities=1),
        LifecyclePolicy(default_lease_turns=1, max_lease_turns=1),
    ],
)
def test_generated_policy_boundaries_remain_constructible(policy: LifecyclePolicy) -> None:
    assert isinstance(policy, LifecyclePolicy)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_discovery_cards": 6},
        {"max_active_capabilities": 9},
        {"default_lease_turns": 5, "max_lease_turns": 4},
    ],
)
def test_generated_invalid_policies_are_rejected(kwargs: dict[str, int]) -> None:
    with pytest.raises(LifecycleError) as failure:
        LifecyclePolicy(**kwargs)
    assert failure.value.code == "invalid-policy"


@pytest.mark.parametrize(
    ("method", "kwargs", "code"),
    [
        ("discover", {"limit": True}, "invalid-discovery-limit"),
        ("activate", {"capability_id": "missing", "current_turn": True}, "invalid-turn"),
        ("active", {"current_turn": -1}, "invalid-turn"),
        ("deactivate", {"capability_id": "missing", "current_turn": -1}, "invalid-turn"),
    ],
)
def test_generated_non_integer_lifecycle_inputs_fail_closed(
    method: str, kwargs: dict[str, object], code: str
) -> None:
    registry = LifecycleRegistry()
    with pytest.raises(LifecycleError) as failure:
        getattr(registry, method)(**kwargs)
    assert failure.value.code == code
