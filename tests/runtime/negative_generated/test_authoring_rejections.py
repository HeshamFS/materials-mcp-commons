from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from materials_mcp_commons import (
    AuthoringError,
    CapabilitySpec,
    ContractRegistry,
    EffectSpec,
    PluginPackageBuilder,
    PluginPackageSpec,
    SchemaSpec,
    WorkspaceSpec,
    scaffold_workspace,
)
from materials_mcp_commons.authoring import scaffold_main

PUBLIC_ROOT = Path(__file__).parents[3]
ENGINE_PACKAGE = PUBLIC_ROOT / "tests/runtime/positive-project/engine-lifecycle"


def _json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _spec() -> PluginPackageSpec:
    document = _json(ENGINE_PACKAGE / "manifest.json")
    capabilities = tuple(
        CapabilitySpec(
            capability_id=cast(str, item["capability_id"]),
            title=cast(str, item["title"]),
            description=cast(str, item["description"]),
            effect=EffectSpec(**cast(dict[str, Any], item["effect"])),
            input_schema=cast(str, item["input_schema"]),
            result_schema=cast(str, item["result_schema"]),
            error_schema=cast(str, item["error_schema"]),
            supports_async=cast(bool, item["supports_async"]),
        )
        for item in cast(list[dict[str, object]], document["capabilities"])
    )
    schemas = tuple(
        SchemaSpec(
            schema_id=cast(str, item["schema_id"]),
            source_path=cast(str, item["path"]),
            package_path=cast(str, item["path"]),
            role=cast(str, item["role"]),
        )
        for item in cast(list[dict[str, object]], document["schema_resources"])
    )
    publisher = cast(dict[str, object], document["publisher"])
    license_record = cast(dict[str, object], document["license"])
    return PluginPackageSpec(
        profile_version=cast(str, document["profile_version"]),
        plugin_id=cast(str, document["plugin_id"]),
        plugin_version=cast(str, document["plugin_version"]),
        name=cast(str, document["name"]),
        description=cast(str, document["description"]),
        publisher_name=cast(str, publisher["name"]),
        license_expression=cast(str, license_record["expression"]),
        rights_uri=cast(str, license_record["rights_uri"]),
        capabilities=capabilities,
        schemas=schemas,
    )


def test_generated_scaffold_names_paths_and_existing_destination_fail_closed(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(AuthoringError) as bad_distribution:
        WorkspaceSpec("Bad Name", "valid_name", "Name", "Publisher", "Apache-2.0")
    assert bad_distribution.value.code == "invalid-workspace-name"
    with pytest.raises(AuthoringError):
        WorkspaceSpec("valid-name", "../escape", "Name", "Publisher", "Apache-2.0")
    with pytest.raises(AuthoringError):
        WorkspaceSpec("valid-name", "valid_name", "Name", "Publisher", "bad/license")

    spec = WorkspaceSpec("valid-name", "valid_name", "Name", "Publisher", "Apache-2.0")
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(AuthoringError) as rejected:
        scaffold_workspace(spec, existing)
    assert rejected.value.code == "destination-exists"
    with pytest.raises(AuthoringError) as relative:
        scaffold_workspace(spec, Path("relative"))
    assert relative.value.code == "unsafe-destination"

    target = tmp_path / "cli"
    target.mkdir()
    assert (
        scaffold_main(
            [
                str(target),
                "--distribution-name",
                spec.distribution_name,
                "--import-name",
                spec.import_name,
                "--display-name",
                spec.display_name,
                "--publisher-name",
                spec.publisher_name,
                "--license-expression",
                spec.license_expression,
            ]
        )
        == 2
    )
    assert "destination-exists" in capsys.readouterr().err


def test_generated_schema_paths_and_spec_collisions_are_rejected() -> None:
    with pytest.raises(AuthoringError) as traversal:
        SchemaSpec("https://example.invalid/schema", "../schema.json", "schema.json", "input")
    assert traversal.value.code == "unsafe-authoring-path"
    with pytest.raises(AuthoringError):
        SchemaSpec("https://example.invalid/schema", "schema.json", "manifest.json", "input")
    with pytest.raises(AuthoringError):
        SchemaSpec("https://example.invalid/schema", "schema.json", "schema.json", "unknown")

    spec = _spec()
    with pytest.raises(AuthoringError) as collision:
        replace(spec, schemas=(spec.schemas[0], spec.schemas[0]))
    assert collision.value.code in {"duplicate-schema-id", "path-collision"}


def test_generated_builder_rejects_profile_overlap_missing_and_invalid_schema(
    tmp_path: Path,
    contract_registry: ContractRegistry,
) -> None:
    builder = PluginPackageBuilder(contract_registry)
    spec = _spec()
    with pytest.raises(AuthoringError) as mismatch:
        builder.build(
            replace(spec, profile_version="0.1.0"),
            schema_source_root=ENGINE_PACKAGE,
            destination=tmp_path / "mismatch",
        )
    assert mismatch.value.code == "profile-mismatch"

    with pytest.raises(AuthoringError) as overlap:
        builder.build(
            spec,
            schema_source_root=ENGINE_PACKAGE,
            destination=ENGINE_PACKAGE / "generated-output",
        )
    assert overlap.value.code == "overlapping-roots"

    missing_schema = replace(spec.schemas[0], source_path="schemas/missing.schema.json")
    with pytest.raises(AuthoringError) as missing:
        builder.build(
            replace(spec, schemas=(missing_schema, *spec.schemas[1:])),
            schema_source_root=ENGINE_PACKAGE,
            destination=tmp_path / "missing",
        )
    assert missing.value.code == "invalid-schema-source"
    assert not (tmp_path / "missing").exists()

    invalid_root = tmp_path / "invalid-source"
    invalid_root.mkdir()
    for schema in spec.schemas:
        content = (ENGINE_PACKAGE / schema.source_path).read_bytes()
        target = invalid_root / schema.source_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    first = spec.schemas[0]
    (invalid_root / first.source_path).write_text("{}\n", encoding="utf-8")
    destination = tmp_path / "invalid-package"
    with pytest.raises(AuthoringError) as invalid:
        builder.build(spec, schema_source_root=invalid_root, destination=destination)
    assert invalid.value.code == "package-validation-failed"
    assert not destination.exists()
    assert not list(tmp_path.glob(".invalid-package.staging-*"))


def test_generated_invalid_effect_is_rejected_by_exact_manifest_contract(
    tmp_path: Path,
    contract_registry: ContractRegistry,
) -> None:
    spec = _spec()
    invalid_effect = replace(spec.capabilities[0].effect, tier="R9")
    invalid_capability = replace(spec.capabilities[0], effect=invalid_effect)
    destination = tmp_path / "invalid-effect"
    with pytest.raises(AuthoringError) as rejected:
        PluginPackageBuilder(contract_registry).build(
            replace(spec, capabilities=(invalid_capability, *spec.capabilities[1:])),
            schema_source_root=ENGINE_PACKAGE,
            destination=destination,
        )
    assert rejected.value.code == "package-validation-failed"
    assert not destination.exists()
