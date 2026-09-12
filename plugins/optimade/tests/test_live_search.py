from __future__ import annotations

# pyright: reportPrivateUsage=false
import base64
import json
import os
from pathlib import Path
from typing import NoReturn, cast

import pytest
import requests

from materials_mcp_optimade import PROFILE_VERSION, SCHEMA_BASE, OptimadeClient
from materials_mcp_optimade import client as client_module
from materials_mcp_optimade.client import (  # pyright: ignore[reportPrivateUsage]
    _SEARCH_QUERY_TOKEN_LIMIT,
    _assert_search_query_context,
    _composite_identity,
    _encode_cursor,
    _encoding_token_count,
    _provider_implementation_document,
    _ProviderSearch,
    _search_encoding,
    _SearchRequest,
)
from materials_mcp_optimade.config import PROVIDERS
from materials_mcp_optimade.contracts import load_declarative_manifest
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
TOKENIZER_REF = "https://github.com/openai/tiktoken/tree/0.14.0#o200k_base"
NOMAD_RECORD = "C1YUj8LENValWcMQ3Y0aUH5acDmX"


def _validate(result: dict[str, object]) -> None:
    manifest = load_declarative_manifest(PROFILE_ROOT)
    manifest.validate(f"{SCHEMA_BASE}search-result.schema.json", result)


def _rendered(result: dict[str, object]) -> str:
    return json.dumps(
        result,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _cursor_offset(cursor: str) -> int:
    padded = cursor + "=" * (-len(cursor) % 4)
    decoded = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    return cast(int, cast(dict[str, object], decoded)["offset"])


def _assert_exact_context_measurement(result: dict[str, object]) -> None:
    rendered = _rendered(result)
    encoding = _search_encoding(BoundedHttpsTransport())
    context = cast(dict[str, object], result["context"])
    assert len(rendered.encode("utf-8")) == context["observed_utf8_bytes"]
    assert _encoding_token_count(encoding, rendered) == context["observed_tokens"], TOKENIZER_REF
    assert cast(int, context["observed_utf8_bytes"]) <= 8192
    assert cast(int, context["observed_tokens"]) <= 1500


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


def test_live_tokenizer_source_uses_bounded_transport_without_disk_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def forbidden_get(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("Tokenizer initialization bypassed the bounded project transport")

    cache = tmp_path / "forbidden-tokenizer-cache"
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(cache))
    monkeypatch.setattr(requests, "get", forbidden_get)
    client_module._search_encoding_cache = None  # pyright: ignore[reportPrivateUsage]
    encoding = _search_encoding(BoundedHttpsTransport())

    assert encoding.encode("Materials MCP Commons")
    assert _encoding_token_count(encoding, "<|endoftext|>") > 0
    special_token_query = _SearchRequest.from_payload(
        {
            "providers": ["nmd"],
            "filter": 'id="<|endoftext|>"',
            "response_fields": ["id"],
            "sort": [],
            "include": [],
            "page_limit": 1,
            "max_pages_per_provider": 1,
            "max_results": 1,
        }
    )
    _assert_search_query_context(
        special_token_query, lambda text: _encoding_token_count(encoding, text)
    )
    assert not cache.exists()


def test_live_maximal_page_metadata_compacts_to_cryptographic_commitments() -> None:
    encoding = _search_encoding(BoundedHttpsTransport())
    payload: dict[str, object] = {
        "providers": ["mp", "nmd"],
        "filter": "",
        "response_fields": ["id"],
        "sort": [],
        "include": [],
        "page_limit": 10,
        "max_pages_per_provider": 5,
        "max_results": 2,
    }
    for count in range(1, 50):
        candidate = {
            **payload,
            "filter": " OR ".join(f'id="mp-{index:04d}"' for index in range(count)),
        }
        encoded_query = json.dumps(
            candidate, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        if _encoding_token_count(encoding, encoded_query) > _SEARCH_QUERY_TOKEN_LIMIT:
            break
        payload = candidate
    request = _SearchRequest.from_payload(payload)
    _assert_search_query_context(request, lambda text: _encoding_token_count(encoding, text))
    results: list[_ProviderSearch] = []
    for provider_index, provider_id in enumerate(request.providers):
        config = PROVIDERS[provider_id]
        hit: dict[str, object] = {
            "identity": _composite_identity(config, "structures", f"boundary-{provider_id}", None),
            "standard_attributes": {"id": f"boundary-{provider_id}"},
            "namespaced_attributes": {},
            "relationships": {},
            "included": [],
            "selected_field_count": 1,
            "returned_selected_field_count": 1,
            "omitted_selected_field_count": 0,
            "unrequested_field_count": 0,
            "page_index": 4,
            "resource_index": 0,
            "warnings": [],
        }
        cursor = _encode_cursor(provider_id, "structures", 1, request.query_digest("structures"))
        provider: dict[str, object] = {
            "provider_id": provider_id,
            "database_id": config.database_id,
            "api_base_url": config.api_base_url,
            "api_version": "1.2.0",
            **_provider_implementation_document("boundary-control", "1"),
            "outcome": "success",
            "pages_returned": 5,
            "records_returned": 1,
            "data_available": 100,
            "more_data_available": True,
            "response_sha256": [str(provider_index) * 63 + str(index) for index in range(5)],
            "retrieved_at": [f"2026-09-12T00:00:0{index}Z" for index in range(5)],
            "rights": config.rights.to_search_document(),
            "citation_ref": config.citation.citation_ref,
            "warning_records_observed": 0,
            "warning_records_omitted": 0,
            "warnings": [],
        }
        results.append(_ProviderSearch(provider, [hit], 0, cursor))

    result = OptimadeClient()._bounded_search_result(  # pyright: ignore[reportPrivateUsage]
        entry_type="structures",
        request=request,
        results=results,
        token_counter=lambda text: _encoding_token_count(encoding, text),
    )
    _validate(result)
    _assert_exact_context_measurement(result)

    providers = cast(list[dict[str, object]], result["providers"])
    committed = 0
    for provider in providers:
        commitment = provider.get("page_evidence_commitment")
        if commitment is not None:
            commitment_document = cast(dict[str, object], commitment)
            assert provider["response_sha256"] == []
            assert provider["retrieved_at"] == []
            assert commitment_document["count"] == 5
            assert len(cast(str, commitment_document["sha256"])) == 64
            committed += cast(int, commitment_document["count"])
    assert cast(int, result["total_returned"]) > 0
    assert committed == 10


def test_live_exact_tokenizer_isolates_unrepresentable_record_identity() -> None:
    encoding = _search_encoding(BoundedHttpsTransport())
    request = _SearchRequest.from_payload(
        {
            "providers": ["mp", "nmd"],
            "filter": "",
            "response_fields": ["id"],
            "sort": [],
            "include": [],
            "page_limit": 1,
            "max_pages_per_provider": 1,
            "max_results": 2,
        }
    )
    hostile_id = "\x01" * 512
    results: list[_ProviderSearch] = []
    for provider_index, provider_id in enumerate(request.providers):
        config = PROVIDERS[provider_id]
        provider: dict[str, object] = {
            "provider_id": provider_id,
            "database_id": config.database_id,
            "api_base_url": config.api_base_url,
            "api_version": "1.2.0",
            **_provider_implementation_document("boundary-control", "1"),
            "outcome": "success" if provider_id == "mp" else "empty",
            "pages_returned": 1,
            "records_returned": 1 if provider_id == "mp" else 0,
            "data_available": 1 if provider_id == "mp" else 0,
            "more_data_available": False,
            "response_sha256": [("a" if provider_index == 0 else "b") * 64],
            "retrieved_at": ["2026-09-12T00:00:00Z"],
            "rights": config.rights.to_search_document(),
            "citation_ref": config.citation.citation_ref,
            "warning_records_observed": 0,
            "warning_records_omitted": 0,
            "warnings": [],
        }
        hits: list[dict[str, object]] = []
        if provider_id == "mp":
            hits.append(
                {
                    "identity": _composite_identity(config, "structures", hostile_id, hostile_id),
                    "standard_attributes": {},
                    "namespaced_attributes": {},
                    "relationships": {},
                    "included": [],
                    "selected_field_count": 1,
                    "returned_selected_field_count": 1,
                    "omitted_selected_field_count": 0,
                    "unrequested_field_count": 0,
                    "page_index": 0,
                    "resource_index": 0,
                    "warnings": [],
                }
            )
        results.append(_ProviderSearch(provider, hits, 0, None))

    result = OptimadeClient()._bounded_search_result(  # pyright: ignore[reportPrivateUsage]
        entry_type="structures",
        request=request,
        results=results,
        token_counter=lambda text: _encoding_token_count(encoding, text),
    )
    _validate(result)
    _assert_exact_context_measurement(result)

    providers = cast(list[dict[str, object]], result["providers"])
    mp = next(provider for provider in providers if provider["provider_id"] == "mp")
    nmd = next(provider for provider in providers if provider["provider_id"] == "nmd")
    assert result["status"] == "partial"
    assert cast(dict[str, object], mp["failure"])["code"] == "record-identity-context"
    assert nmd["outcome"] == "empty"


def test_live_two_provider_structure_search() -> None:
    client = OptimadeClient()
    query = _structure_query()
    result = client.search_structures(query)
    _validate(result)

    providers = cast(list[dict[str, object]], result["providers"])
    context = cast(dict[str, object], result["context"])
    assert result["status"] == "complete"
    assert cast(int, result["total_returned"]) > 0
    assert cast(int, result["total_returned"]) + cast(int, context["omitted_hits"]) == 4
    assert result["total_returned"] == sum(
        cast(int, provider["records_returned"]) for provider in providers
    )
    assert cast(int, context["observed_tokens"]) <= cast(int, context["token_limit"])
    assert cast(int, context["observed_utf8_bytes"]) <= cast(int, context["utf8_byte_limit"])
    assert [(item["provider_id"], item["outcome"]) for item in providers] == [
        ("mp", "success"),
        ("nmd", "success"),
    ]
    assert cast(int, context["omitted_hits"]) > 0
    assert result["deferred_hits"] == []
    _assert_exact_context_measurement(result)

    continued = client.search_structures(
        {**query, "continuation": cast(dict[str, str], result["continuation"])}
    )
    _validate(continued)
    _assert_exact_context_measurement(continued)
    assert cast(int, cast(dict[str, object], continued["context"])["omitted_hits"]) > 0
    assert continued["deferred_hits"] == []
    first_refs = {
        cast(str, cast(dict[str, object], hit["identity"])["composite_ref"])
        for hit in cast(list[dict[str, object]], result["hits"])
    }
    continued_refs = {
        cast(str, cast(dict[str, object], hit["identity"])["composite_ref"])
        for hit in cast(list[dict[str, object]], continued["hits"])
    }
    assert first_refs.isdisjoint(continued_refs)
    provider_ids = {
        cast(str, cast(dict[str, object], hit["identity"])["provider_id"])
        for page in (result, continued)
        for hit in cast(list[dict[str, object]], page["hits"])
    }
    assert provider_ids == {"mp", "nmd"}
    first_continuation = cast(dict[str, str], result["continuation"])
    continued_continuation = cast(dict[str, str], continued["continuation"])
    continued_providers = {
        cast(str, provider["provider_id"]): provider
        for provider in cast(list[dict[str, object]], continued["providers"])
    }
    for provider_id, first_cursor in first_continuation.items():
        first_offset = _cursor_offset(first_cursor)
        if provider_id in continued_continuation:
            assert _cursor_offset(continued_continuation[provider_id]) == first_offset + cast(
                int, continued_providers[provider_id]["records_returned"]
            )


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
    query: dict[str, object] = {
        "providers": ["nmd"],
        "filter": 'elements HAS ALL "Si", "O"',
        "response_fields": ["chemical_formula_reduced", "elements", "nelements"],
        "sort": ["-nelements"],
        "include": [],
        "page_limit": 10,
        "max_pages_per_provider": 1,
        "max_results": 10,
    }
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
    first_context = cast(dict[str, object], first["context"])
    second_context = cast(dict[str, object], second["context"])
    first_cursor = cast(dict[str, str], first["continuation"])["nmd"]
    second_cursor = cast(dict[str, str], second["continuation"])["nmd"]

    assert cast(int, first_context["omitted_hits"]) > 0
    assert cast(int, second_context["omitted_hits"]) > 0
    assert _cursor_offset(first_cursor) == first["total_returned"]
    assert _cursor_offset(second_cursor) == cast(int, first["total_returned"]) + cast(
        int, second["total_returned"]
    )
    assert first_ids.isdisjoint(second_ids)


def test_live_sort_relationship_control_and_namespaced_projection() -> None:
    result = OptimadeClient().search_structures(
        {
            "providers": ["nmd"],
            "filter": "",
            "response_fields": [
                "chemical_formula_reduced",
                "nelements",
                "_nmd_entry_page_url",
            ],
            "sort": ["-nelements"],
            "include": ["references"],
            "page_limit": 10,
            "max_pages_per_provider": 1,
            "max_results": 10,
        }
    )
    _validate(result)

    hits = cast(list[dict[str, object]], result["hits"])
    providers = cast(list[dict[str, object]], result["providers"])
    values = [
        cast(int, cast(dict[str, object], hit["standard_attributes"])["nelements"]) for hit in hits
    ]
    assert values == sorted(values, reverse=True)
    assert any(
        cast(
            str, cast(dict[str, object], hit["namespaced_attributes"])["_nmd_entry_page_url"]
        ).startswith("https://nomad-lab.eu/")
        for hit in hits
    )
    assert all(type(hit["relationships"]) is dict for hit in hits)
    assert all(type(hit["included"]) is list for hit in hits)
    query_commitment = cast(dict[str, object], result["query"])
    assert set(query_commitment) == {"sha256"}
    assert len(cast(str, query_commitment["sha256"])) == 64
    assert len(cast(list[str], providers[0]["response_sha256"])) == len(
        cast(list[str], providers[0]["retrieved_at"])
    )


def test_live_single_hit_search_passes_the_profile_inline_context_budget() -> None:
    result = OptimadeClient().search_structures(
        {
            "providers": ["nmd"],
            "filter": f'id="{NOMAD_RECORD}"',
            "response_fields": ["chemical_formula_reduced"],
            "sort": [],
            "include": [],
            "page_limit": 1,
            "max_pages_per_provider": 1,
            "max_results": 1,
        }
    )
    _validate(result)

    assert result["total_returned"] == 1
    _assert_exact_context_measurement(result)
