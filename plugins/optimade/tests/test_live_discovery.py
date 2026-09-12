from __future__ import annotations

import os
from pathlib import Path
from typing import cast

import pytest

from materials_mcp_optimade import PROFILE_VERSION, SCHEMA_BASE, OptimadeClient
from materials_mcp_optimade.contracts import is_supported_api_version, load_declarative_manifest

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("MATERIALS_MCP_LIVE") != "1",
        reason="Set MATERIALS_MCP_LIVE=1 to run fixed-provider live evidence",
    ),
]

PLUGIN_ROOT = Path(__file__).parents[1]
PUBLIC_ROOT = PLUGIN_ROOT.parents[1]
PROFILE_ROOT = PUBLIC_ROOT / "schemas" / PROFILE_VERSION


def test_live_registry_and_reviewed_index_resolution() -> None:
    result = OptimadeClient().list_providers()
    manifest = load_declarative_manifest(PROFILE_ROOT)

    manifest.validate(f"{SCHEMA_BASE}provider-list-result.schema.json", result)
    providers = cast(list[dict[str, object]], result["providers"])
    selected: dict[str, dict[str, object]] = {}
    for item in providers:
        provider_id = cast(str, item["provider_id"])
        if provider_id in {"mp", "nmd"}:
            selected[provider_id] = item
    assert selected["mp"]["support_status"] == "supported"
    assert selected["nmd"]["support_status"] == "supported"


def test_live_registry_request_can_exclude_unreviewed_entries() -> None:
    result = OptimadeClient().list_providers(
        {"include_registry_only": False, "registry_entry_limit": 2}
    )
    load_declarative_manifest(PROFILE_ROOT).validate(
        f"{SCHEMA_BASE}provider-list-result.schema.json", result
    )

    providers = cast(list[dict[str, object]], result["providers"])
    assert [item["provider_id"] for item in providers] == ["mp", "nmd"]


@pytest.mark.parametrize("provider_id", ["mp", "nmd"])
def test_live_provider_inspection(provider_id: str) -> None:
    result = OptimadeClient().inspect_provider(provider_id)
    manifest = load_declarative_manifest(PROFILE_ROOT)

    manifest.validate(f"{SCHEMA_BASE}provider-inspect-result.schema.json", result)
    negotiation = cast(dict[str, object], result["negotiation"])
    entry_types = cast(list[dict[str, object]], result["entry_types"])
    assert is_supported_api_version(negotiation["reported_api_version"])
    assert negotiation["supported"] is True
    assert [item["entry_type"] for item in entry_types] == [
        "structures",
        "references",
    ]


def test_live_provider_inspection_honors_projection_controls() -> None:
    result = OptimadeClient().inspect_provider(
        {
            "provider_id": "nmd",
            "entry_types": ["structures"],
            "include_property_definitions": False,
            "property_limit": 1,
        }
    )
    load_declarative_manifest(PROFILE_ROOT).validate(
        f"{SCHEMA_BASE}provider-inspect-result.schema.json", result
    )

    entry_types = cast(list[dict[str, object]], result["entry_types"])
    assert len(entry_types) == 1
    assert entry_types[0]["entry_type"] == "structures"
    assert entry_types[0]["returned_property_count"] == 0
    assert cast(int, entry_types[0]["omitted_property_count"]) > 0
