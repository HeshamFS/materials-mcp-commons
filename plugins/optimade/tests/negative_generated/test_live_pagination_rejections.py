"""Live-source negative controls for bounded pagination behavior."""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path
from typing import cast

import pytest

from materials_mcp_optimade import PROFILE_VERSION, SCHEMA_BASE, OptimadeClient
from materials_mcp_optimade.contracts import load_declarative_manifest
from materials_mcp_optimade.transport import (
    DEFAULT_MAX_RESPONSE_BYTES,
    BoundedHttpsTransport,
    HttpResponse,
    TrustedEndpoint,
)

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("MATERIALS_MCP_LIVE") != "1",
        reason="Set MATERIALS_MCP_LIVE=1 to run fixed-provider live evidence",
    ),
]

PLUGIN_ROOT = Path(__file__).parents[2]
PUBLIC_ROOT = PLUGIN_ROOT.parents[1]
PROFILE_ROOT = PUBLIC_ROOT / "schemas" / PROFILE_VERSION


class _RepeatFirstLiveResponse(BoundedHttpsTransport):
    """Return one authentic first page again to simulate a looping provider."""

    def __init__(self) -> None:
        super().__init__()
        self._first_response: HttpResponse | None = None

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
        if endpoint.hostname == "openaipublic.blob.core.windows.net":
            return super().get(
                endpoint,
                relative_path,
                query=query,
                accepted_content_types=accepted_content_types,
                expected_statuses=expected_statuses,
                max_bytes=max_bytes,
            )
        if self._first_response is None:
            self._first_response = super().get(
                endpoint,
                relative_path,
                query=query,
                accepted_content_types=accepted_content_types,
                expected_statuses=expected_statuses,
                max_bytes=max_bytes,
            )
        return self._first_response


def test_identical_live_page_at_a_new_offset_fails_closed() -> None:
    result = OptimadeClient(_RepeatFirstLiveResponse()).search_structures(
        {
            "providers": ["nmd"],
            "filter": 'elements HAS ALL "Si", "O"',
            "response_fields": ["chemical_formula_reduced"],
            "sort": [],
            "include": [],
            "page_limit": 1,
            "max_pages_per_provider": 2,
            "max_results": 2,
        }
    )
    load_declarative_manifest(PROFILE_ROOT).validate(
        f"{SCHEMA_BASE}search-result.schema.json", result
    )

    providers = cast(list[dict[str, object]], result["providers"])
    failure = cast(dict[str, object], providers[0]["failure"])
    assert result["status"] == "partial"
    assert result["total_returned"] == 1
    assert providers[0]["records_returned"] == 1
    assert failure["code"] == "pagination-loop"
