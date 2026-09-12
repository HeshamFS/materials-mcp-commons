from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from materials_mcp_optimade import PROVIDERS, OptimadeClient, OptimadeExporter
from materials_mcp_optimade import client as client_module
from materials_mcp_optimade.errors import ExportError, ProviderProtocolError, TransportError
from materials_mcp_optimade.transport import (
    HttpResponse,
    TrustedEndpoint,
    approved_ip_literals,
    decode_json_object,
    quote_path_segment,
)

PLUGIN_ROOT = Path(__file__).parents[1]


def _response(body: bytes) -> HttpResponse:
    return HttpResponse(
        request_uri="https://providers.optimade.org/v1/links",
        status=200,
        headers={},
        body=body,
        sha256="0" * 64,
        requested_at=datetime(2026, 9, 12, tzinfo=UTC),
        retrieved_at=datetime(2026, 9, 12, tzinfo=UTC),
    )


def test_reviewed_provider_authority_and_rights_are_exact() -> None:
    assert tuple(PROVIDERS) == ("mp", "nmd")
    assert PROVIDERS["mp"].api_base_url == "https://optimade.materialsproject.org"
    assert PROVIDERS["mp"].rights.review_status == "unavailable"
    assert PROVIDERS["mp"].rights.terms_sha256 is None
    assert not PROVIDERS["mp"].rights.permits_redistribution(datetime(2026, 9, 13, tzinfo=UTC))

    nomad = PROVIDERS["nmd"]
    assert nomad.api_base_url == "https://nomad-lab.eu/prod/v1/optimade"
    assert nomad.rights.terms_sha256 == (
        "174713534aece4cfdba681cdd2cb8436969b446eb3a9bc6dc7b04551bb4094ed"
    )
    assert nomad.rights.permits_redistribution(datetime(2026, 9, 13, tzinfo=UTC))
    assert not nomad.rights.permits_redistribution(datetime(2026, 10, 12, tzinfo=UTC))


def test_rights_reviews_retain_a_seven_day_operating_window() -> None:
    minimum_expiry = datetime.now(UTC) + timedelta(days=7)
    for config in PROVIDERS.values():
        assert config.rights.expires_at > minimum_expiry, (
            f"{config.provider_id} rights review expires too soon for unattended operation"
        )


@pytest.mark.parametrize(
    "url",
    [
        "http://providers.optimade.org",
        "https://user@example.org",
        "https://example.org:444",
        "https://127.0.0.1",
        "https://example.org/?next=https://127.0.0.1",
        "https://example.org/#fragment",
    ],
)
def test_unreviewed_endpoint_authority_is_rejected(url: str) -> None:
    with pytest.raises(TransportError):
        TrustedEndpoint.from_url(url)


def test_request_target_is_reconstructed_from_a_reviewed_origin() -> None:
    endpoint = TrustedEndpoint.from_url(PROVIDERS["nmd"].api_base_url)
    target, uri = endpoint.request_target(
        "/v1/structures",
        (("filter", 'elements HAS "Si"'), ("page_limit", "1")),
    )

    assert target.startswith("/prod/v1/optimade/v1/structures?")
    assert uri.startswith("https://nomad-lab.eu/prod/v1/optimade/v1/structures?")
    assert "127.0.0.1" not in uri
    with pytest.raises(TransportError):
        endpoint.request_target("/v1/../admin")


def test_record_ids_are_encoded_as_one_path_segment() -> None:
    assert quote_path_segment("db/record 1") == "db%2Frecord%201"
    with pytest.raises(TransportError):
        quote_path_segment("line\nbreak")


def test_dns_literals_must_all_be_public_and_bounded() -> None:
    assert approved_ip_literals(["1.1.1.1", "1.1.1.1"]) == ("1.1.1.1",)
    for address in (
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "::1",
        "fc00::1",
        "2606:4700:4700::1111",
        "64:ff9b::7f00:1",
        "64:ff9b::a00:1",
    ):
        with pytest.raises(TransportError):
            approved_ip_literals([address])


@pytest.mark.parametrize(
    "body, code",
    [
        (b'{"data":1,"data":2}', "json-duplicate-member"),
        (b'{"value":NaN}', "json-number-invalid"),
        (b"[]", "json-root"),
        (b"\xff", "json-encoding"),
    ],
)
def test_malformed_provider_json_fails_closed(body: bytes, code: str) -> None:
    with pytest.raises(ProviderProtocolError) as captured:
        decode_json_object(_response(body))
    assert captured.value.code == code


def test_runtime_source_does_not_authorize_upstream_http_clients() -> None:
    package_root = PLUGIN_ROOT / "src" / "materials_mcp_optimade"
    for path in sorted(package_root.glob("*.py")):
        source = path.read_text(encoding="utf-8").lower()
        assert "import requests" not in source
        assert "from requests" not in source
        assert "import httpx" not in source
        assert "from optimade.client" not in source
        assert "import optimade.client" not in source


def test_invalid_filter_and_continuation_fail_before_external_retrieval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_tokenizer_load(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("invalid input reached external tokenizer retrieval")

    monkeypatch.setattr(client_module, "_search_encoding", unexpected_tokenizer_load)
    client = OptimadeClient()
    base: dict[str, object] = {
        "providers": ["mp"],
        "filter": "elements HAS ???",
        "response_fields": ["elements"],
        "sort": [],
        "include": [],
        "page_limit": 1,
        "max_pages_per_provider": 1,
        "max_results": 1,
    }
    with pytest.raises(ProviderProtocolError) as malformed_filter:
        client.search_structures(base)
    assert malformed_filter.value.code == "filter-invalid"

    with pytest.raises(ProviderProtocolError) as malformed_cursor:
        client.search_structures(
            {**base, "filter": "", "continuation": {"mp": "not-a-valid-cursor"}}
        )
    assert malformed_cursor.value.code == "continuation-invalid"


@pytest.mark.parametrize(
    "payload, code",
    [
        (
            {
                "provider_id": "unreviewed",
                "database_id": "unreviewed",
                "entry_id": "record-1",
                "response_fields": ["elements"],
                "include": [],
            },
            "provider-not-allowed",
        ),
        (
            {
                "provider_id": "mp",
                "database_id": "nmd",
                "entry_id": "record-1",
                "response_fields": ["elements"],
                "include": [],
            },
            "database-mismatch",
        ),
        (
            {
                "provider_id": "mp",
                "database_id": "mp",
                "entry_id": "record-1",
                "response_fields": ["not a property"],
                "include": [],
            },
            "input-shape",
        ),
    ],
)
def test_exact_request_rejects_unreviewed_or_malformed_inputs_before_network(
    payload: dict[str, object], code: str
) -> None:
    with pytest.raises(ProviderProtocolError) as captured:
        OptimadeClient().get_structure(payload)
    assert captured.value.code == code


def test_export_fails_closed_on_rights_and_unsafe_paths(tmp_path: Path) -> None:
    exporter = OptimadeExporter(tmp_path)
    payload: dict[str, object] = {
        "provider_id": "mp",
        "database_id": "mp",
        "entry_type": "structures",
        "entry_id": "mp-733539",
        "format": "optimade-json",
        "destination": "mp-record.json",
        "overwrite": False,
    }
    with pytest.raises(ExportError) as denied:
        exporter.export(payload, request_ref="urn:materials-mcp:request:rights-denial")
    assert denied.value.code == "rights-denied"
    assert not (tmp_path / "mp-record.json").exists()

    with pytest.raises(ExportError) as escaped:
        exporter.export(
            {**payload, "provider_id": "nmd", "database_id": "nmd", "destination": "../x"},
            request_ref="urn:materials-mcp:request:path-denial",
        )
    assert escaped.value.code == "export-path-rejected"


def test_export_rejects_invalid_request_identity_before_persistence(tmp_path: Path) -> None:
    payload: dict[str, object] = {
        "provider_id": "nmd",
        "database_id": "nmd",
        "entry_type": "structures",
        "entry_id": "C1YUj8LENValWcMQ3Y0aUH5acDmX",
        "format": "optimade-json",
        "destination": "must-not-exist.json",
        "overwrite": False,
    }

    with pytest.raises(ExportError) as captured:
        OptimadeExporter(tmp_path).export(payload, request_ref="relative-request")
    assert captured.value.code == "input-shape"
    assert not (tmp_path / "must-not-exist.json").exists()


def test_export_rejects_existing_or_missing_parent_before_network(tmp_path: Path) -> None:
    existing = tmp_path / "existing.json"
    existing.write_bytes(b"preserve me")
    payload: dict[str, object] = {
        "provider_id": "nmd",
        "database_id": "nmd",
        "entry_type": "structures",
        "entry_id": "C1YUj8LENValWcMQ3Y0aUH5acDmX",
        "format": "optimade-json",
        "destination": existing.name,
        "overwrite": False,
    }

    with pytest.raises(ExportError) as overwrite:
        OptimadeExporter(tmp_path).export(
            payload,
            request_ref="urn:materials-mcp:request:overwrite-denial",
        )
    assert overwrite.value.code == "overwrite-rejected"
    assert existing.read_bytes() == b"preserve me"

    with pytest.raises(ExportError) as missing_parent:
        OptimadeExporter(tmp_path).export(
            {**payload, "destination": "missing/record.json"},
            request_ref="urn:materials-mcp:request:missing-parent",
        )
    assert missing_parent.value.code == "export-parent-missing"
    assert not (tmp_path / "missing").exists()


def test_export_write_is_handle_bound_and_exclusive(tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    destination = nested / "record.json"
    exporter = OptimadeExporter(tmp_path)

    exporter._write(destination, b"real provider bytes")  # pyright: ignore[reportPrivateUsage]
    assert destination.read_bytes() == b"real provider bytes"

    with pytest.raises(ExportError) as captured:
        exporter._write(destination, b"replacement")  # pyright: ignore[reportPrivateUsage]
    assert captured.value.code == "overwrite-rejected"
    assert destination.read_bytes() == b"real provider bytes"


def test_export_write_rejects_a_linked_parent(tmp_path: Path) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    linked_parent = root / "linked"
    try:
        linked_parent.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory-link creation is unavailable on this host")

    exporter = OptimadeExporter(root)
    with pytest.raises(ExportError) as captured:
        exporter._write(  # pyright: ignore[reportPrivateUsage]
            linked_parent / "must-not-exist.json",
            b"must not escape",
        )
    assert captured.value.code == "export-path-rejected"
    assert not (outside / "must-not-exist.json").exists()
