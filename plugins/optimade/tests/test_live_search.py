from __future__ import annotations

import os
from pathlib import Path
from typing import cast

import pytest

from materials_mcp_optimade import PROFILE_VERSION, SCHEMA_BASE, OptimadeClient
from materials_mcp_optimade.contracts import load_declarative_manifest

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


def _validate(result: dict[str, object]) -> None:
    manifest = load_declarative_manifest(PROFILE_ROOT)
    manifest.validate(f"{SCHEMA_BASE}search-result.schema.json", result)


def _structure_query() -> dict[str, object]:
    return {
        "providers": ["mp", "nmd"],
        "filter": 'elements HAS ALL "Si", "O"',
        "response_fields": ["chemical_formula_reduced", "elements", "nelements"],
        "sort": [],
        "include": [],
        "page_limit": 2,
        "max_pages_per_provider": 1,
        "max_results": 4,
    }


def test_live_two_provider_structure_search() -> None:
    result = OptimadeClient().search_structures(_structure_query())
    _validate(result)

    providers = cast(list[dict[str, object]], result["providers"])
    assert result["status"] == "complete"
    assert result["total_returned"] == 4
    assert [(item["provider_id"], item["outcome"]) for item in providers] == [
        ("mp", "success"),
        ("nmd", "success"),
    ]


def test_live_reference_search_preserves_real_empty_provider() -> None:
    result = OptimadeClient().search_references(
        {
            "providers": ["mp", "nmd"],
            "filter": "",
            "response_fields": ["title", "year", "doi"],
            "sort": [],
            "include": [],
            "page_limit": 1,
            "max_pages_per_provider": 1,
            "max_results": 2,
        }
    )
    _validate(result)

    providers = cast(list[dict[str, object]], result["providers"])
    assert result["status"] == "complete"
    assert providers[0]["provider_id"] == "mp"
    assert providers[0]["outcome"] in {"success", "empty"}
    assert providers[1]["provider_id"] == "nmd"
    assert providers[1]["outcome"] in {"success", "empty"}


def test_live_zero_match_preserves_nomad_failure_without_placeholder_data() -> None:
    result = OptimadeClient().search_structures(
        {
            "providers": ["mp", "nmd"],
            "filter": 'id="materials-mcp-commons-no-match-20260912"',
            "response_fields": ["chemical_formula_reduced"],
            "sort": [],
            "include": [],
            "page_limit": 1,
            "max_pages_per_provider": 1,
            "max_results": 2,
        }
    )
    _validate(result)

    providers = cast(list[dict[str, object]], result["providers"])
    assert result["status"] == "partial"
    assert result["total_returned"] == 0
    assert result["hits"] == []
    assert providers[0]["outcome"] == "empty"
    assert providers[1]["outcome"] == "failed"
    assert cast(dict[str, object], providers[1]["failure"])["http_status"] == 500


def test_live_continuation_reconstructs_provider_offsets() -> None:
    query = _structure_query()
    query.update(
        {
            "response_fields": ["chemical_formula_reduced"],
            "page_limit": 1,
            "max_results": 2,
        }
    )
    client = OptimadeClient()
    first = client.search_structures(query)
    second = client.search_structures(
        {**query, "continuation": cast(dict[str, str], first["continuation"])}
    )
    _validate(first)
    _validate(second)

    first_ids = {
        cast(dict[str, object], hit["identity"])["entry_id"]
        for hit in cast(list[dict[str, object]], first["hits"])
    }
    second_ids = {
        cast(dict[str, object], hit["identity"])["entry_id"]
        for hit in cast(list[dict[str, object]], second["hits"])
    }
    assert first["total_returned"] == 2
    assert second["total_returned"] == 2
    assert first_ids.isdisjoint(second_ids)
