from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from materials_mcp_commons import (
    ContextGateway,
    ContextPolicy,
    ContractRegistry,
)
from materials_mcp_commons.contracts import load_json_object

from materials_mcp_optimade import PROFILE_VERSION, OptimadeClient
from materials_mcp_optimade.client import _search_encoding  # pyright: ignore[reportPrivateUsage]
from materials_mcp_optimade.errors import ProviderProtocolError
from materials_mcp_optimade.transport import BoundedHttpsTransport

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
RESULT_BUNDLE_SCHEMA = (
    "https://schemas.autonomouslab.io/materials-mcp/0.2.0/result-bundle.schema.json"
)
TOKENIZER_REF = "https://github.com/openai/tiktoken/tree/0.14.0#o200k_base"


def _validate(result: dict[str, object]) -> None:
    ContractRegistry.from_directory(PROFILE_ROOT, PROFILE_VERSION).validate(
        RESULT_BUNDLE_SCHEMA, result
    )


@pytest.mark.parametrize(
    ("provider_id", "database_id", "entry_id"),
    [
        ("mp", "mp", "mp-733539"),
        ("nmd", "nmd", "C1YUj8LENValWcMQ3Y0aUH5acDmX"),
    ],
)
def test_live_structure_get_preserves_exact_source_evidence(
    provider_id: str, database_id: str, entry_id: str
) -> None:
    result = OptimadeClient().get_structure(
        {
            "provider_id": provider_id,
            "database_id": database_id,
            "entry_id": entry_id,
            "response_fields": ["chemical_formula_reduced", "elements", "nelements"],
            "include": [],
        }
    )
    _validate(result)

    entity = cast(list[dict[str, object]], result["entities"])[0]
    artifact = cast(list[dict[str, object]], result["artifacts"])[0]
    identifiers = cast(list[dict[str, object]], entity["identifiers"])
    identifier_values = {(item["scheme"], item["value"]) for item in identifiers}

    assert result["status"] == "complete"
    assert ("optimade-provider", provider_id) in identifier_values
    assert ("optimade-database", database_id) in identifier_values
    assert ("optimade-entry-id", entry_id) in identifier_values
    assert cast(int, artifact["size_bytes"]) > 0
    assert len(cast(str, artifact["sha256"])) == 64
    assert cast(str, artifact["uri"]).startswith("https://")


def test_live_reference_get_uses_real_materials_literature_record() -> None:
    result = OptimadeClient().get_reference(
        {
            "provider_id": "mp",
            "database_id": "mp",
            "entry_id": "maddox1988",
            "response_fields": ["title", "year", "doi"],
            "include": [],
        }
    )
    _validate(result)

    properties = cast(list[dict[str, object]], result["properties"])
    property_ids = {cast(str, item["property_id"]) for item in properties}
    assert "urn:optimade:1.2:references:title" in property_ids
    assert "urn:optimade:1.2:references:doi" in property_ids


def test_live_expected_immutable_identity_must_match_provider_record() -> None:
    with pytest.raises(ProviderProtocolError) as captured:
        OptimadeClient().get_structure(
            {
                "provider_id": "mp",
                "database_id": "mp",
                "entry_id": "mp-733539",
                "response_fields": ["chemical_formula_reduced"],
                "include": [],
                "expected_immutable_id": "intentionally-nonmatching-identity",
            }
        )
    assert captured.value.code == "immutable-identity-mismatch"


def test_live_exact_result_projects_through_the_engine_context_contract() -> None:
    contracts = ContractRegistry.from_directory(PROFILE_ROOT, PROFILE_VERSION)
    context_manifest = load_json_object(
        PUBLIC_ROOT / "tests/contracts/profile-0.2.0/context-manifest.json"
    )
    policy = ContextPolicy.from_manifest(context_manifest, contracts)
    encoding = _search_encoding(BoundedHttpsTransport())
    gateway = ContextGateway(
        policy,
        contracts,
        token_counter=lambda text: len(encoding.encode(text)),
        tokenizer_ref=TOKENIZER_REF,
    )
    result = OptimadeClient().get_structure(
        {
            "provider_id": "nmd",
            "database_id": "nmd",
            "entry_id": "C1YUj8LENValWcMQ3Y0aUH5acDmX",
            "response_fields": ["chemical_formula_reduced", "elements", "nelements"],
            "include": [],
        }
    )
    projection = gateway.project_result(result, generated_at=datetime.now(UTC), unit="tokens")
    report = gateway.lint(
        control_tools=[],
        discovery_cards=[],
        active_schemas=[],
        inline_result=projection.to_document(),
        historical_mcp_tokens=0,
        model_window_tokens=128_000,
    )

    assert projection.tokens is not None
    assert projection.tokens <= policy.max_inline_tokens
    assert projection.utf8_bytes <= policy.max_inline_bytes
    assert report.tokenizer_ref == TOKENIZER_REF
    assert report.state == "pass"
    assert report.violations == ()
