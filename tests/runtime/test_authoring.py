from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any, cast

import pytest

from materials_mcp_commons import (
    ENGINE_REQUIREMENT,
    CapabilitySpec,
    ContractRegistry,
    EffectSpec,
    ExtensionSpec,
    LifecycleRegistry,
    ManifestLoader,
    PluginPackageBuilder,
    PluginPackageSpec,
    SchemaSpec,
    WorkspaceSpec,
    plugin_conformance_main,
    scaffold_workspace,
)
from materials_mcp_commons.authoring import scaffold_main
from tools.build_engine_control_package import main as build_engine_control_main

PUBLIC_ROOT = Path(__file__).parents[2]
ENGINE_PACKAGE = PUBLIC_ROOT / "tests/runtime/positive-project/engine-lifecycle"


def _json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _engine_package_spec() -> PluginPackageSpec:
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
    declarations = tuple(
        ExtensionSpec(
            schema_id=cast(str, item["schema_id"]),
            applies_to=tuple(cast(list[str], item["applies_to"])),
        )
        for item in cast(list[dict[str, object]], document["extension_declarations"])
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
        publisher_uri=cast(str | None, publisher.get("uri")),
        license_expression=cast(str, license_record["expression"]),
        rights_uri=cast(str, license_record["rights_uri"]),
        capabilities=capabilities,
        schemas=schemas,
        extension_declarations=declarations,
        extensions=cast(dict[str, object], document.get("extensions", {})),
    )


def _file_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    }


def test_scaffold_api_and_cli_create_the_same_empty_workspace(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    spec = WorkspaceSpec(
        distribution_name="materials-research-package",
        import_name="materials_research_package",
        display_name="Materials Research Package",
        publisher_name="Hesham Salama",
        license_expression="Apache-2.0",
    )
    first = tmp_path / "first"
    second = tmp_path / "second"
    cli = tmp_path / "cli"
    first_receipt = scaffold_workspace(spec, first)
    second_receipt = scaffold_workspace(spec, second)

    assert _file_bytes(first) == _file_bytes(second)
    assert first_receipt.files == second_receipt.files
    assert first_receipt.engine_requirement == ENGINE_REQUIREMENT
    assert sorted(_file_bytes(first)) == [
        ".gitignore",
        "README.md",
        "pyproject.toml",
        "schemas/README.md",
        "src/materials_research_package/__init__.py",
        "tests/README.md",
    ]
    assert not (first / "manifest.json").exists()
    metadata = tomllib.loads((first / "pyproject.toml").read_text(encoding="utf-8"))
    project = cast(dict[str, Any], metadata["project"])
    assert project["dependencies"] == [ENGINE_REQUIREMENT]
    assert project["authors"] == [{"name": "Hesham Salama"}]

    assert (
        scaffold_main(
            [
                str(cli),
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
        == 0
    )
    assert capsys.readouterr().err == ""
    assert _file_bytes(first) == _file_bytes(cli)


def test_builder_reconstructs_actual_engine_package_deterministically(
    tmp_path: Path,
    contract_registry: ContractRegistry,
) -> None:
    spec = _engine_package_spec()
    builder = PluginPackageBuilder(contract_registry)
    first = tmp_path / "first-package"
    second = tmp_path / "second-package"
    first_receipt = builder.build(
        spec,
        schema_source_root=ENGINE_PACKAGE,
        destination=first,
    )
    second_receipt = builder.build(
        spec,
        schema_source_root=ENGINE_PACKAGE,
        destination=second,
    )

    assert _file_bytes(first) == _file_bytes(second)
    assert first_receipt.files == second_receipt.files
    assert first_receipt.manifest_sha256 == second_receipt.manifest_sha256
    assert first_receipt.registration_identity == (spec.plugin_id, spec.plugin_version)
    assert first_receipt.manifest.capabilities == second_receipt.manifest.capabilities
    for schema in spec.schemas:
        assert (first / schema.package_path).read_bytes() == (
            ENGINE_PACKAGE / schema.source_path
        ).read_bytes()
    manifest = _json(first / "manifest.json")
    assert manifest == _json(ENGINE_PACKAGE / "manifest.json")
    for resource in cast(list[dict[str, object]], manifest["schema_resources"]):
        package_path = cast(str, resource["path"])
        expected_hash = dict(first_receipt.files)[package_path]
        assert resource["sha256"] == expected_hash
    loaded = ManifestLoader(contract_registry).load(first)
    registration = LifecycleRegistry().register(loaded)
    assert registration.manifest_sha256 == first_receipt.manifest_sha256


def test_documented_engine_control_builder_example_is_executable(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    destination = tmp_path / "rebuilt-engine-control"
    assert build_engine_control_main([str(destination)]) == 0
    assert capsys.readouterr().err == ""
    assert _json(destination / "manifest.json") == _json(ENGINE_PACKAGE / "manifest.json")
    assert {
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_file()
    } == {
        "manifest.json",
        "schemas/discovery-input.schema.json",
        "schemas/discovery-result.schema.json",
        "schemas/inspection-input.schema.json",
        "schemas/inspection-result.schema.json",
    }
    for schema in (destination / "schemas").iterdir():
        assert schema.read_bytes() == (ENGINE_PACKAGE / "schemas" / schema.name).read_bytes()


def test_installed_conformance_cli_checks_actual_engine_package(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "report.json"
    assert (
        plugin_conformance_main(
            [
                "--profile-root",
                str(PUBLIC_ROOT / "schemas/0.2.0"),
                "--profile-version",
                "0.2.0",
                "--package",
                str(ENGINE_PACKAGE),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert capsys.readouterr() == ("", "")
    assert output.read_text(encoding="utf-8") == (
        PUBLIC_ROOT / "conformance/engine-plugin-report.json"
    ).read_text(encoding="utf-8")
