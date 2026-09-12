"""Generated boundary controls; no values here are scientific evidence."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from materials_mcp_optimade import (
    PROFILE_VERSION,
    SCHEMA_BASE,
    OptimadeClient,
)
from materials_mcp_optimade import (
    client as client_module,
)
from materials_mcp_optimade.client import (
    _assert_search_query_context,
    _bounded_hit_warnings,
    _bounded_provider_inspection_result,
    _bounded_provider_list_result,
    _bounded_result_bundle,
    _composite_identity,
    _dispatch_metrics,
    _encode_cursor,
    _finalize_provider_messages,
    _page_evidence_sha256,
    _provider_implementation_document,
    _provider_messages,
    _ProviderSearch,
    _search_encoding,
    _SearchRequest,
    _text,
)
from materials_mcp_optimade.config import PROVIDERS
from materials_mcp_optimade.contracts import CAPABILITY_IDS, load_declarative_manifest
from materials_mcp_optimade.errors import ProviderProtocolError
from materials_mcp_optimade.transport import (
    DEFAULT_MAX_RESPONSE_BYTES,
    BoundedHttpsTransport,
    HttpResponse,
    TrustedEndpoint,
)

PLUGIN_ROOT = Path(__file__).parents[2]
PUBLIC_ROOT = PLUGIN_ROOT.parents[1]
PROFILE_ROOT = PUBLIC_ROOT / "schemas" / PROFILE_VERSION


def _conservative_token_count(text: str) -> int:
    utf8_bytes = len(text.encode("utf-8"))
    return (utf8_bytes + 2) // 3


def _cursor_offset(cursor: str) -> int:
    padded = cursor + "=" * (-len(cursor) % 4)
    document = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    return cast(int, cast(dict[str, object], document)["offset"])


def _provider_search_fixture(
    *,
    provider_id: str,
    request: _SearchRequest,
    entry_id: str,
    field_value: str,
    outcome: str = "success",
    failure_code: str | None = None,
) -> _ProviderSearch:
    config = PROVIDERS[provider_id]
    provider: dict[str, object] = {
        "provider_id": provider_id,
        "database_id": config.database_id,
        "api_base_url": config.api_base_url,
        "api_version": "1.2.0",
        **_provider_implementation_document("boundary-control", "1"),
        "outcome": outcome,
        "pages_returned": 1,
        "records_returned": 1,
        "data_available": 1,
        "more_data_available": False,
        "response_sha256": [("a" if provider_id == "mp" else "b") * 64],
        "retrieved_at": ["2026-09-12T00:00:00Z"],
        "rights": config.rights.to_search_document(),
        "citation_ref": config.citation.citation_ref,
        "warning_records_observed": 0,
        "warning_records_omitted": 0,
        "warnings": [],
    }
    if failure_code is not None:
        provider["failure"] = {
            "code": failure_code,
            "http_status": 0,
            "title": "Existing provider failure",
            "detail": "The original provider failure must remain unchanged.",
            "retryable": True,
        }
    hit: dict[str, object] = {
        "identity": _composite_identity(config, "structures", entry_id, None),
        "standard_attributes": {"field_a": field_value},
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
    cursor = _encode_cursor(provider_id, "structures", 1, request.query_digest("structures"))
    return _ProviderSearch(provider, [hit], 0, cursor)


class _WrongTokenizerTransport(BoundedHttpsTransport):
    def get(
        self,
        endpoint: TrustedEndpoint,
        relative_path: str,
        *,
        query: Sequence[tuple[str, str]] = (),
        accepted_content_types: frozenset[str] = frozenset(
            {"application/vnd.api+json", "application/json"}
        ),
        expected_statuses: frozenset[int] = frozenset({200}),
        max_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ) -> HttpResponse:
        del query, accepted_content_types, expected_statuses, max_bytes
        body = b"wrong tokenizer bytes"
        now = datetime.now(UTC)
        return HttpResponse(
            request_uri=f"{endpoint.origin}{relative_path}",
            status=200,
            headers={},
            body=body,
            sha256=hashlib.sha256(body).hexdigest(),
            requested_at=now,
            retrieved_at=now,
        )


def test_tokenizer_source_hash_mismatch_fails_closed() -> None:
    client_module._search_encoding_cache = None
    with pytest.raises(ProviderProtocolError) as captured:
        _search_encoding(_WrongTokenizerTransport())
    assert captured.value.code == "context-tokenizer-integrity"


def test_oversized_hit_advances_with_an_exact_retrieval_descriptor() -> None:
    request = _SearchRequest.from_payload(
        {
            "providers": ["nmd"],
            "filter": "",
            "response_fields": ["field_a", "field_b"],
            "sort": [],
            "include": [],
            "page_limit": 1,
            "max_pages_per_provider": 1,
            "max_results": 1,
        }
    )
    config = PROVIDERS["nmd"]
    hit: dict[str, object] = {
        "identity": _composite_identity(config, "structures", "oversized-boundary", None),
        "standard_attributes": {"field_a": "a" * 4096, "field_b": "b" * 4096},
        "namespaced_attributes": {},
        "relationships": {},
        "included": [],
        "selected_field_count": 2,
        "returned_selected_field_count": 2,
        "omitted_selected_field_count": 0,
        "unrequested_field_count": 0,
        "page_index": 0,
        "resource_index": 0,
        "warnings": [],
    }
    cursor = _encode_cursor("nmd", "structures", 1, request.query_digest("structures"))
    provider: dict[str, object] = {
        "provider_id": "nmd",
        "database_id": "nmd",
        "api_base_url": config.api_base_url,
        "api_version": "1.2.0",
        **_provider_implementation_document("boundary-control", "1"),
        "outcome": "success",
        "pages_returned": 1,
        "records_returned": 1,
        "data_available": 2,
        "more_data_available": True,
        "response_sha256": ["a" * 64],
        "retrieved_at": ["2026-09-12T00:00:00Z"],
        "rights": config.rights.to_search_document(),
        "citation_ref": config.citation.citation_ref,
        "warning_records_observed": 0,
        "warning_records_omitted": 0,
        "warnings": [],
    }
    result = OptimadeClient()._bounded_search_result(  # pyright: ignore[reportPrivateUsage]
        entry_type="structures",
        request=request,
        results=[_ProviderSearch(provider, [hit], 0, cursor)],
        token_counter=_conservative_token_count,
    )
    load_declarative_manifest(PROFILE_ROOT).validate(
        f"{SCHEMA_BASE}search-result.schema.json", result
    )

    deferred = cast(list[dict[str, object]], result["deferred_hits"])
    context = cast(dict[str, object], result["context"])
    assert result["hits"] == []
    assert result["total_returned"] == 0
    assert cast(dict[str, object], result["query"])["sha256"] == request.query_digest("structures")
    assert context["omitted_hits"] == 1
    assert context["deferred_hits"] == 1
    assert len(deferred) == 1
    assert deferred[0]["exact_capability_id"] == CAPABILITY_IDS["structures_get"]
    assert _cursor_offset(cast(dict[str, str], result["continuation"])["nmd"]) == 1


def test_unrepresentable_record_identity_isolates_only_its_provider() -> None:
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
        hits: list[dict[str, object]] = (
            [
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
            ]
            if provider_id == "mp"
            else []
        )
        results.append(_ProviderSearch(provider, hits, 0, None))

    result = OptimadeClient()._bounded_search_result(  # pyright: ignore[reportPrivateUsage]
        entry_type="structures",
        request=request,
        results=results,
        token_counter=_conservative_token_count,
    )
    load_declarative_manifest(PROFILE_ROOT).validate(
        f"{SCHEMA_BASE}search-result.schema.json", result
    )

    providers = cast(list[dict[str, object]], result["providers"])
    mp = next(provider for provider in providers if provider["provider_id"] == "mp")
    nmd = next(provider for provider in providers if provider["provider_id"] == "nmd")
    assert result["status"] == "partial"
    assert mp["outcome"] == "failed"
    assert cast(dict[str, object], mp["failure"])["code"] == "record-identity-context"
    assert nmd["outcome"] == "empty"
    assert result["hits"] == []
    assert result["deferred_hits"] == []
    assert _cursor_offset(cast(dict[str, str], result["continuation"])["mp"]) == 0


def test_competing_benign_oversized_hits_make_deferred_progress() -> None:
    request = _SearchRequest.from_payload(
        {
            "providers": ["mp", "nmd"],
            "filter": "",
            "response_fields": ["field_a"],
            "sort": [],
            "include": [],
            "page_limit": 1,
            "max_pages_per_provider": 1,
            "max_results": 2,
        }
    )
    results = [
        _provider_search_fixture(
            provider_id=provider_id,
            request=request,
            entry_id=f"ordinary-{provider_id}",
            field_value="x" * 4096,
        )
        for provider_id in request.providers
    ]

    result = OptimadeClient()._bounded_search_result(  # pyright: ignore[reportPrivateUsage]
        entry_type="structures",
        request=request,
        results=results,
        token_counter=_conservative_token_count,
    )
    load_declarative_manifest(PROFILE_ROOT).validate(
        f"{SCHEMA_BASE}search-result.schema.json", result
    )

    deferred = cast(list[dict[str, object]], result["deferred_hits"])
    providers = cast(list[dict[str, object]], result["providers"])
    assert result["status"] == "complete"
    assert result["hits"] == []
    assert len(deferred) == 1
    assert all(provider["outcome"] == "success" for provider in providers)
    progressed_provider = cast(
        str, cast(dict[str, object], deferred[0]["exact_input"])["provider_id"]
    )
    continuation = cast(dict[str, str], result["continuation"])
    assert _cursor_offset(continuation[progressed_provider]) == 1
    stalled_provider = next(item for item in request.providers if item != progressed_provider)
    assert _cursor_offset(continuation[stalled_provider]) == 0


def test_existing_failure_is_preserved_while_successful_provider_hit_survives() -> None:
    request = _SearchRequest.from_payload(
        {
            "providers": ["mp", "nmd"],
            "filter": "",
            "response_fields": ["field_a"],
            "sort": [],
            "include": [],
            "page_limit": 1,
            "max_pages_per_provider": 1,
            "max_results": 2,
        }
    )
    results = [
        _provider_search_fixture(
            provider_id="mp",
            request=request,
            entry_id="ordinary-mp",
            field_value="x" * 4096,
            outcome="failed",
            failure_code="transport-timeout",
        ),
        _provider_search_fixture(
            provider_id="nmd",
            request=request,
            entry_id="ordinary-nmd",
            field_value="retained",
        ),
    ]

    result = OptimadeClient()._bounded_search_result(  # pyright: ignore[reportPrivateUsage]
        entry_type="structures",
        request=request,
        results=results,
        token_counter=_conservative_token_count,
    )
    load_declarative_manifest(PROFILE_ROOT).validate(
        f"{SCHEMA_BASE}search-result.schema.json", result
    )

    providers = cast(list[dict[str, object]], result["providers"])
    mp = next(provider for provider in providers if provider["provider_id"] == "mp")
    retained = cast(list[dict[str, object]], result["hits"])
    assert cast(dict[str, object], mp["failure"])["code"] == "transport-timeout"
    assert [cast(dict[str, object], hit["identity"])["provider_id"] for hit in retained] == ["nmd"]


def test_warning_projection_has_explicit_aggregate_bounds() -> None:
    messages = [
        {"title": f"warning-{index}-" + "t" * 600, "detail": "d" * 2000} for index in range(20)
    ]
    projected, omitted = _provider_messages({"warnings": messages}, 0)
    finalized = _finalize_provider_messages(projected, omitted)
    hit_warnings = _bounded_hit_warnings([f"warning-{index}" for index in range(40)])

    assert len(finalized) == 8
    assert finalized[-1]["title"] == "Provider warnings omitted"
    assert "13 additional" in cast(str, finalized[-1]["detail"])
    assert all(len(cast(str, item["detail"])) <= 2048 for item in finalized)
    assert len(hit_warnings) == 16
    assert "25 additional" in hit_warnings[-1]


def test_provider_implementation_metadata_is_always_hash_committed() -> None:
    ordinary = _provider_implementation_document("implementation", "1.0")
    ordinary_expected = hashlib.sha256(b'{"name":"implementation","version":"1.0"}').hexdigest()
    assert ordinary == {"implementation_metadata_sha256": ordinary_expected}
    large_name = "\U0001f600" * 512
    committed = _provider_implementation_document(large_name, "1.0")
    expected = hashlib.sha256(
        json.dumps(
            {"name": large_name, "version": "1.0"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert set(committed) == {"implementation_metadata_sha256"}
    assert committed["implementation_metadata_sha256"] == expected
    assert committed == _provider_implementation_document(large_name, "1.0")
    with pytest.raises(ProviderProtocolError) as captured:
        _text(large_name, "entry id", maximum=512, max_utf8_bytes=512)
    assert captured.value.code == "provider-shape"


def test_page_evidence_commitment_uses_documented_canonical_json() -> None:
    response_hashes = ["a" * 64, "b" * 64]
    retrieval_times = ["2026-09-12T00:00:00Z", "2026-09-12T00:00:01Z"]
    canonical = (
        '[{"response_sha256":"'
        + "a" * 64
        + '","retrieved_at":"2026-09-12T00:00:00Z"},'
        + '{"response_sha256":"'
        + "b" * 64
        + '","retrieved_at":"2026-09-12T00:00:01Z"}]'
    )
    assert (
        _page_evidence_sha256(response_hashes, retrieval_times)
        == hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    )


def test_optional_provider_warning_members_project_without_provider_failure() -> None:
    projected, omitted = _provider_messages(
        {
            "warnings": [
                {"detail": "detail only"},
                {"title": "title only"},
                {},
                {"title": "", "detail": ""},
                {"title": "x" * 20000, "detail": "y" * 20000},
            ]
        },
        0,
    )

    assert omitted == 0
    assert projected[0] == {"title": "Provider warning", "detail": "Page 1: detail only"}
    assert projected[1] == {
        "title": "title only",
        "detail": "Page 1: Provider supplied no warning detail.",
    }
    assert projected[2] == {
        "title": "Provider warning",
        "detail": "Page 1: Provider supplied no warning detail.",
    }
    assert projected[3] == {
        "title": "Provider warning",
        "detail": "Page 1: Provider supplied no warning detail.",
    }
    assert "sha256=" in cast(str, projected[4]["title"])
    assert "sha256=" in cast(str, projected[4]["detail"])


def test_two_provider_warning_metadata_compacts_before_denying_result() -> None:
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
    results: list[_ProviderSearch] = []
    for provider_index, provider_id in enumerate(request.providers):
        config = PROVIDERS[provider_id]
        provider: dict[str, object] = {
            "provider_id": provider_id,
            "database_id": config.database_id,
            "api_base_url": config.api_base_url,
            "api_version": "1.2.0",
            **_provider_implementation_document("boundary-control", "1"),
            "outcome": "empty",
            "pages_returned": 1,
            "records_returned": 0,
            "data_available": 0,
            "more_data_available": False,
            "response_sha256": [("a" if provider_index == 0 else "b") * 64],
            "retrieved_at": ["2026-09-12T00:00:00Z"],
            "rights": config.rights.to_search_document(),
            "citation_ref": config.citation.citation_ref,
            "warning_records_observed": 8,
            "warning_records_omitted": 0,
            "warnings": [{"title": f"warning-{index}", "detail": "x" * 1800} for index in range(8)],
        }
        results.append(_ProviderSearch(provider, [], 0, None))

    result = OptimadeClient()._bounded_search_result(  # pyright: ignore[reportPrivateUsage]
        entry_type="structures",
        request=request,
        results=results,
        token_counter=_conservative_token_count,
    )
    providers = cast(list[dict[str, object]], result["providers"])

    load_declarative_manifest(PROFILE_ROOT).validate(
        f"{SCHEMA_BASE}search-result.schema.json", result
    )

    assert all(provider["warning_records_omitted"] == 8 for provider in providers)
    assert all(cast(list[object], provider["warnings"]) == [] for provider in providers)
    context = cast(dict[str, object], result["context"])
    assert cast(int, context["observed_utf8_bytes"]) <= 8192


def test_oversized_search_query_fails_before_provider_federation() -> None:
    filter_value = f'chemical_formula_reduced="{"x" * 3000}"'
    request = _SearchRequest.from_payload(
        {
            "providers": ["nmd"],
            "filter": filter_value,
            "response_fields": ["id"],
            "sort": [],
            "include": [],
            "page_limit": 1,
            "max_pages_per_provider": 1,
            "max_results": 1,
        }
    )

    with pytest.raises(ProviderProtocolError) as captured:
        _assert_search_query_context(request, _conservative_token_count)

    assert captured.value.code == "input-context-budget"


def test_dispatch_compactors_remove_whole_records_and_preserve_evidence() -> None:
    list_document: dict[str, object] = {
        "registry": {"data_returned": 40, "more_data_available": False},
        "providers": [
            {"support_status": "registry-only", "description": "x" * 4096} for _ in range(40)
        ],
        "warnings": [],
    }
    inspection_document: dict[str, object] = {
        "entry_types": [
            {
                "entry_type": "structures",
                "properties": [
                    {"name": f"field_{index}", "definition": {"description": "x" * 4096}}
                    for index in range(40)
                ],
                "returned_property_count": 40,
                "omitted_property_count": 0,
                "warnings": [],
            }
        ]
    }
    result_document: dict[str, object] = {
        "status": "complete",
        "properties": [{"value": {"value_type": "text", "value": "x" * 16000}} for _ in range(10)],
        "provenance": {
            "sources": [
                {
                    "sha256": "a" * 64,
                    "transformations": [
                        {"target_pointer": "/entities/0"},
                        *[{"target_pointer": f"/properties/{index}/value"} for index in range(10)],
                    ],
                }
            ]
        },
        "warnings": [
            "source retained",
            "not assessed",
            *[f"projection warning {index}: " + "x" * 1000 for index in range(10)],
            (
                "Applicable provider terms were unavailable for review; "
                "redistribution remains unknown."
            ),
            "The provider rights review is expired; persistence and export remain disabled.",
        ],
    }

    _bounded_provider_list_result(list_document)
    _bounded_provider_inspection_result(inspection_document)
    _bounded_result_bundle(result_document)

    documents = (list_document, inspection_document, result_document)
    assert all(_dispatch_metrics(item)[0] <= 65_536 for item in documents)
    assert all(_dispatch_metrics(item)[1] <= 4_096 for item in documents)
    provenance = cast(dict[str, object], result_document["provenance"])
    sources = cast(list[dict[str, object]], provenance["sources"])
    assert sources[0]["sha256"] == "a" * 64
    assert result_document["status"] == "partial"
    assert any(
        warning.startswith("Applicable provider terms ")
        for warning in cast(list[str], result_document["warnings"])
    )
    assert any(
        warning.startswith("The provider rights review ")
        for warning in cast(list[str], result_document["warnings"])
    )
    assert "registry_entry_offset" in cast(list[str], list_document["warnings"])[0]


def test_warning_only_dispatch_compaction_preserves_exact_status_and_properties() -> None:
    result_document: dict[str, object] = {
        "status": "complete",
        "properties": [{"value": {"value_type": "text", "value": "retained"}}],
        "provenance": {
            "sources": [
                {
                    "sha256": "a" * 64,
                    "transformations": [
                        {"target_pointer": "/entities/0"},
                        {"target_pointer": "/properties/0/value"},
                    ],
                }
            ]
        },
        "warnings": [f"warning-{index}: " + "x" * 7000 for index in range(10)],
    }

    _bounded_result_bundle(result_document)

    assert result_document["status"] == "complete"
    assert len(cast(list[object], result_document["properties"])) == 1
    assert all(
        len(warning.encode("utf-8")) <= 512
        for warning in cast(list[str], result_document["warnings"])
    )


def test_invalid_relationship_name_is_hash_identified_within_warning_bound() -> None:
    invalid_name = "x" * 4096
    request = _SearchRequest.from_payload(
        {
            "providers": ["nmd"],
            "filter": "",
            "response_fields": ["id"],
            "sort": [],
            "include": [],
            "page_limit": 1,
            "max_pages_per_provider": 1,
            "max_results": 1,
        }
    )
    hit = OptimadeClient()._project_hit(  # pyright: ignore[reportPrivateUsage]
        config=PROVIDERS["nmd"],
        entry_type="structures",
        resource={
            "id": "boundary-record",
            "type": "structures",
            "attributes": {},
            "relationships": {invalid_name: {"data": None}},
        },
        included=[],
        request=request,
        page_index=0,
        resource_index=0,
    )
    warnings = cast(list[str], hit["warnings"])

    assert len(warnings) == 1
    assert len(warnings[0]) <= 1024
    assert hashlib.sha256(invalid_name.encode("utf-8")).hexdigest() in warnings[0]
