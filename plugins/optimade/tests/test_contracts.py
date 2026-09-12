from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, cast

import pytest
from materials_mcp_commons import ContractError, ContractRegistry, ManifestLoader
from optimade.filterparser import LarkParser  # pyright: ignore[reportMissingTypeStubs]

from materials_mcp_optimade import (
    CAPABILITY_IDS,
    PLUGIN_ID,
    PLUGIN_VERSION,
    PROFILE_VERSION,
    SCHEMA_BASE,
    declarative_package_root,
    load_declarative_manifest,
)
from materials_mcp_optimade.client import _scientific_value  # pyright: ignore[reportPrivateUsage]
from materials_mcp_optimade.contracts import OPTIMADE_CONTRACT_LINE, is_supported_api_version
from tools.build_conformance import build_reference, build_report
from tools.build_declarative_package import build
from tools.build_dependency_inventory import build_inventory

PLUGIN_ROOT = Path(__file__).parents[1]
PUBLIC_ROOT = PLUGIN_ROOT.parents[1]
PROFILE_ROOT = PUBLIC_ROOT / "schemas" / PROFILE_VERSION
CONFORMANCE_REPORT = PLUGIN_ROOT / "conformance" / "structural-report.json"
CAPABILITY_REFERENCE = PLUGIN_ROOT / "conformance" / "capabilities.md"


def test_api_patch_compatibility_and_periodicity_projection_are_explicit() -> None:
    assert OPTIMADE_CONTRACT_LINE == "1.2"
    assert is_supported_api_version("1.2.0")
    assert is_supported_api_version("1.2.17")
    for unsupported in ("1.2.0-develop", "1.2.01", "1.1.9", "1.3.0", 1):
        assert not is_supported_api_version(unsupported)

    assert _scientific_value("dimension_types", [1, 1, 1]) is None
    assert _scientific_value("elements_ratios", [0.5, 0.5]) == {
        "value_type": "number-array",
        "value": [0.5, 0.5],
        "unit": {"system": "UCUM", "identifier": "1", "symbol": "1"},
    }


def _file_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    }


def test_declarative_manifest_is_exact_and_engine_loadable() -> None:
    loaded = load_declarative_manifest(PROFILE_ROOT)

    assert loaded.plugin_id == PLUGIN_ID
    assert loaded.plugin_version == PLUGIN_VERSION
    assert loaded.profile_version == PROFILE_VERSION
    assert loaded.publisher_name == "Hesham Salama"
    assert loaded.license_expression == "Apache-2.0"
    assert [item.capability_id for item in loaded.capabilities] == list(CAPABILITY_IDS.values())
    assert [item.effect.tier for item in loaded.capabilities] == [
        "R0",
        "R0",
        "R0",
        "R0",
        "R0",
        "R0",
        "R1",
    ]
    assert len(loaded.schema_resources) == 10


def test_declarative_package_rebuilds_byte_for_byte(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"

    first_digest = build(first)
    second_digest = build(second)

    assert first_digest == second_digest
    assert _file_bytes(first) == _file_bytes(second)
    assert _file_bytes(first) == _file_bytes(declarative_package_root())


def test_structural_conformance_evidence_is_current_and_deterministic() -> None:
    assert build_report() == CONFORMANCE_REPORT.read_text(encoding="utf-8")
    assert build_reference() == CAPABILITY_REFERENCE.read_text(encoding="utf-8")


def test_frozen_inputs_reject_unreviewed_execution_authority() -> None:
    manifest = ManifestLoader(ContractRegistry.from_directory(PROFILE_ROOT, PROFILE_VERSION)).load(
        declarative_package_root()
    )
    search_schema = f"{SCHEMA_BASE}search-input.schema.json"
    get_schema = f"{SCHEMA_BASE}get-input.schema.json"
    valid_search = {
        "providers": ["mp", "nmd"],
        "filter": 'elements HAS ALL "Si", "O"',
        "response_fields": ["chemical_formula_reduced", "elements", "nelements"],
        "sort": ["chemical_formula_reduced"],
        "include": [],
        "page_limit": 2,
        "max_pages_per_provider": 2,
        "max_results": 8,
    }
    manifest.validate(search_schema, valid_search)
    manifest.validate(
        get_schema,
        {
            "provider_id": "nmd",
            "database_id": "nmd",
            "entry_id": "C1Si1F6",
            "response_fields": ["chemical_formula_reduced", "elements", "nelements"],
            "include": [],
        },
    )

    with pytest.raises(ContractError) as unreviewed_provider:
        manifest.validate(search_schema, {**valid_search, "providers": ["unreviewed"]})
    assert unreviewed_provider.value.code == "schema-validation"
    with pytest.raises(ContractError) as arbitrary_endpoint:
        manifest.validate(
            get_schema,
            {
                "provider_id": "nmd",
                "database_id": "nmd",
                "entry_id": "C1Si1F6",
                "response_fields": ["chemical_formula_reduced"],
                "include": [],
                "base_url": "https://example.invalid/optimade",
            },
        )
    assert arbitrary_endpoint.value.code == "schema-validation"


def test_official_optimade_12_parser_accepts_reviewed_live_filter() -> None:
    parser = cast(Any, LarkParser(version=(1, 2, 0)))
    tree = parser.parse('elements HAS ALL "Si", "O"')

    assert tree.data == "filter"


def test_engine_source_has_no_optimade_dependency_or_branch() -> None:
    engine_source = PUBLIC_ROOT / "src" / "materials_mcp_commons"
    for path in sorted(engine_source.glob("*.py")):
        assert "optimade" not in path.read_text(encoding="utf-8").lower()


def test_checked_in_py312_dependency_inventory_is_current() -> None:
    if sys.version_info[:2] != (3, 12):
        pytest.skip("Dependency inventories are checked for CPython 3.12")
    platform_name = {"win32": "windows", "linux": "linux"}.get(sys.platform)
    if platform_name is None:
        pytest.skip("No dependency inventory is declared for this operating system")
    dependency_inventory = (
        PLUGIN_ROOT / f"conformance/dependency-inventory-{platform_name}-py312.json"
    )
    expected = json.loads(dependency_inventory.read_text(encoding="utf-8"))

    assert build_inventory() == expected
