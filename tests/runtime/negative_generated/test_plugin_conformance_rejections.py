from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, cast

import pytest

from materials_mcp_commons import (
    ContractRegistry,
    ManifestLoader,
    PackageCase,
    PluginConformanceError,
    PluginConformanceRunner,
    ProfileCase,
    assess_plugin_migration,
    build_versioned_matrix,
    render_capability_reference,
)
from materials_mcp_commons.contracts import load_json_object

PUBLIC_ROOT = Path(__file__).parents[3]
ENGINE_PACKAGE = PUBLIC_ROOT / "tests/runtime/positive-project/engine-lifecycle"
SOURCE_PACKAGE = PUBLIC_ROOT / "tests/runtime/positive-project/engine-lifecycle-profile-0.1.0"


def _json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _refresh_digest(package: Path, relative_path: str) -> None:
    manifest = _json(package / "manifest.json")
    resources = cast(list[dict[str, object]], manifest["schema_resources"])
    resource = next(item for item in resources if item["path"] == relative_path)
    resource["sha256"] = hashlib.sha256((package / relative_path).read_bytes()).hexdigest()
    _write_json(package / "manifest.json", manifest)


def _assessment(
    source: Path,
    target: Path,
    source_contracts: ContractRegistry,
    target_contracts: ContractRegistry,
    compatibility: dict[str, object],
) -> dict[str, bool]:
    result = assess_plugin_migration(
        source_package_root=source,
        target_package_root=target,
        source_contracts=source_contracts,
        target_contracts=target_contracts,
        compatibility_document=compatibility,
    )
    assert result.result == "fail"
    return cast(dict[str, bool], result.to_document()["checks"])


def _add_generated_extension(package: Path, label: str) -> None:
    schema_id = "https://schemas.autonomouslab.io/materials-mcp/test/extension.schema.json"
    relative_path = "schemas/generated-extension.schema.json"
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": schema_id,
        "type": "object",
        "required": ["label"],
        "properties": {"label": {"type": "string"}},
        "additionalProperties": False,
    }
    _write_json(package / relative_path, schema)
    manifest = _json(package / "manifest.json")
    cast(list[object], manifest["schema_resources"]).append(
        {
            "schema_id": schema_id,
            "path": relative_path,
            "sha256": hashlib.sha256((package / relative_path).read_bytes()).hexdigest(),
            "media_type": "application/schema+json",
            "role": "extension",
        }
    )
    cast(list[object], manifest["extension_declarations"]).append(
        {
            "schema_id": schema_id,
            "applies_to": [cast(str, manifest["contract"])],
        }
    )
    manifest["extensions"] = {schema_id: {"label": label}}
    _write_json(package / "manifest.json", manifest)


def _registries() -> tuple[ContractRegistry, ContractRegistry, dict[str, object]]:
    source = ContractRegistry.from_directory(PUBLIC_ROOT / "schemas/0.1.0", "0.1.0")
    target = ContractRegistry.from_directory(PUBLIC_ROOT / "schemas/0.2.0", "0.2.0")
    compatibility = load_json_object(
        PUBLIC_ROOT / "tests/contracts/profile-0.2.0/profile-compatibility.json"
    )
    return source, target, compatibility


def test_generated_invalid_package_and_implicit_profile_selection_fail_closed(
    tmp_path: Path,
) -> None:
    _, target, compatibility = _registries()
    invalid = tmp_path / "invalid"
    shutil.copytree(ENGINE_PACKAGE, invalid)
    manifest = _json(invalid / "manifest.json")
    manifest.pop("name")
    _write_json(invalid / "manifest.json", manifest)
    with pytest.raises(PluginConformanceError) as rejected:
        PluginConformanceRunner(target).evaluate(invalid)
    assert rejected.value.code == "package-conformance-failed"

    with pytest.raises(PluginConformanceError) as missing_profile:
        build_versioned_matrix(
            (ProfileCase("0.1.0", PUBLIC_ROOT / "schemas/0.1.0"),),
            (PackageCase("target", ENGINE_PACKAGE),),
            (compatibility,),
        )
    assert missing_profile.value.code == "missing-profile"

    incomplete_partition = dict(compatibility)
    incomplete_partition["added_resources"] = [
        "compact-result.schema.json",
        "context-manifest.schema.json",
        "unregistered.schema.json",
    ]
    matrix = build_versioned_matrix(
        (
            ProfileCase("0.1.0", PUBLIC_ROOT / "schemas/0.1.0"),
            ProfileCase("0.2.0", PUBLIC_ROOT / "schemas/0.2.0"),
        ),
        (),
        (incomplete_partition,),
    )
    assert matrix.to_document()["result"] == "fail"
    compatibility_checks = cast(
        dict[str, bool],
        cast(list[dict[str, object]], matrix.to_document()["compatibility"])[0]["checks"],
    )
    assert not compatibility_checks["resource-partition"]


def test_generated_migration_identity_and_semantic_drift_are_reported(
    tmp_path: Path,
) -> None:
    source_contracts, target_contracts, compatibility = _registries()
    target = tmp_path / "target"
    shutil.copytree(ENGINE_PACKAGE, target)
    manifest = _json(target / "manifest.json")
    manifest["plugin_id"] = "https://schemas.autonomouslab.io/materials-mcp/engine-changed"
    manifest["description"] = f"{manifest['description']} changed"
    _write_json(target / "manifest.json", manifest)
    assessment = assess_plugin_migration(
        source_package_root=SOURCE_PACKAGE,
        target_package_root=target,
        source_contracts=source_contracts,
        target_contracts=target_contracts,
        compatibility_document=compatibility,
    )
    checks = cast(dict[str, bool], assessment.to_document()["checks"])
    assert assessment.result == "fail"
    assert not checks["plugin-identity"]
    assert not checks["manifest-semantics"]

    invalid_compatibility = dict(compatibility)
    invalid_compatibility["from_profile"] = "9.9.9"
    with pytest.raises(PluginConformanceError) as rejected:
        assess_plugin_migration(
            source_package_root=SOURCE_PACKAGE,
            target_package_root=ENGINE_PACKAGE,
            source_contracts=source_contracts,
            target_contracts=target_contracts,
            compatibility_document=invalid_compatibility,
        )
    assert rejected.value.code == "migration-input-invalid"


def test_generated_migration_capability_effect_and_resource_drift_are_reported(
    tmp_path: Path,
) -> None:
    source_contracts, target_contracts, compatibility = _registries()

    capability_target = tmp_path / "capability-target"
    shutil.copytree(ENGINE_PACKAGE, capability_target)
    manifest = _json(capability_target / "manifest.json")
    capability = cast(list[dict[str, object]], manifest["capabilities"])[0]
    capability["capability_id"] = f"{capability['capability_id']}-changed"
    _write_json(capability_target / "manifest.json", manifest)
    capability_checks = _assessment(
        SOURCE_PACKAGE,
        capability_target,
        source_contracts,
        target_contracts,
        compatibility,
    )
    assert not capability_checks["capability-identities"]

    effect_target = tmp_path / "effect-target"
    shutil.copytree(ENGINE_PACKAGE, effect_target)
    manifest = _json(effect_target / "manifest.json")
    effect = cast(
        dict[str, object], cast(list[dict[str, object]], manifest["capabilities"])[0]["effect"]
    )
    effect.update({"tier": "R1", "category": "bounded-local"})
    _write_json(effect_target / "manifest.json", manifest)
    effect_checks = _assessment(
        SOURCE_PACKAGE, effect_target, source_contracts, target_contracts, compatibility
    )
    assert not effect_checks["manifest-semantics"]

    resource_target = tmp_path / "resource-target"
    shutil.copytree(ENGINE_PACKAGE, resource_target)
    manifest = _json(resource_target / "manifest.json")
    resource = cast(list[dict[str, object]], manifest["schema_resources"])[0]
    old_relative = cast(str, resource["path"])
    new_relative = "schemas/discovery-input-renamed.schema.json"
    (resource_target / old_relative).rename(resource_target / new_relative)
    resource["path"] = new_relative
    _write_json(resource_target / "manifest.json", manifest)
    resource_checks = _assessment(
        SOURCE_PACKAGE,
        resource_target,
        source_contracts,
        target_contracts,
        compatibility,
    )
    assert not resource_checks["resource-descriptors"]


def test_generated_migration_schema_and_extension_drift_are_reported(tmp_path: Path) -> None:
    source_contracts, target_contracts, compatibility = _registries()

    schema_target = tmp_path / "schema-target"
    shutil.copytree(ENGINE_PACKAGE, schema_target)
    relative_path = "schemas/discovery-input.schema.json"
    schema = _json(schema_target / relative_path)
    limit = cast(dict[str, object], cast(dict[str, object], schema["properties"])["limit"])
    limit["maximum"] = 4
    _write_json(schema_target / relative_path, schema)
    _refresh_digest(schema_target, relative_path)
    schema_checks = _assessment(
        SOURCE_PACKAGE, schema_target, source_contracts, target_contracts, compatibility
    )
    assert schema_checks["manifest-semantics"]
    assert not schema_checks["schema-semantics"]

    extension_source = tmp_path / "extension-source"
    shutil.copytree(SOURCE_PACKAGE, extension_source)
    extension_target = tmp_path / "extension-target"
    shutil.copytree(ENGINE_PACKAGE, extension_target)
    _add_generated_extension(extension_source, "source")
    _add_generated_extension(extension_target, "target")
    extension_checks = _assessment(
        extension_source,
        extension_target,
        source_contracts,
        target_contracts,
        compatibility,
    )
    assert not extension_checks["manifest-semantics"]


def test_generated_capability_reference_escapes_manifest_markdown(tmp_path: Path) -> None:
    _, contracts, _ = _registries()
    package = tmp_path / "escaped"
    shutil.copytree(ENGINE_PACKAGE, package)
    manifest = _json(package / "manifest.json")
    manifest["name"] = "<script>*unsafe*</script>"
    _write_json(package / "manifest.json", manifest)
    loaded = ManifestLoader(contracts).load(package)
    reference = render_capability_reference(loaded)
    assert "<script>" not in reference
    assert "&lt;script&gt;" in reference
    assert "\\*unsafe\\*" in reference
