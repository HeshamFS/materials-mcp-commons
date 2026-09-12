"""Reviewed provider discovery and introspection over the bounded transport."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import math
import platform
import re
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import version as distribution_version
from typing import Any, Literal, cast

from optimade.filterparser import LarkParser  # pyright: ignore[reportMissingTypeStubs]
from optimade.models import (  # pyright: ignore[reportMissingTypeStubs]
    EntryInfoResponse,
    InfoResponse,
    LinksResponse,
    ReferenceResponseMany,
    ReferenceResponseOne,
    StructureResponseMany,
    StructureResponseOne,
)
from pydantic import ValidationError

from .config import PROVIDERS, REGISTRY_BASE_URL, REGISTRY_LINKS_URL, ProviderConfig
from .contracts import (
    OPTIMADE_BASELINE_VERSION,
    OPTIMADE_CONTRACT_LINE,
    PROFILE_VERSION,
    SCHEMA_BASE,
    is_supported_api_version,
)
from .errors import ProviderProtocolError, TransportError
from .transport import (
    BoundedHttpsTransport,
    HttpResponse,
    TrustedEndpoint,
    decode_json_object,
    quote_path_segment,
)

_VERSION_PATTERN = re.compile(r"^1\.[0-9]+\.[0-9]+$")
_ADVERTISED_VERSION_PATTERN = re.compile(r"^v?[0-9]+(?:\.[0-9]+(?:\.[0-9]+)?)?$")
_MODEL_PROPERTY_PATTERN = re.compile(r"^[a-z_][a-z_0-9]+$")
_OUTPUT_PROPERTY_PATTERN = re.compile(r"^[a-z_][a-z0-9_]{0,127}$")
_NAMESPACED_PROPERTY_PATTERN = re.compile(r"^_[a-z0-9]+_[a-z0-9_]+$")
_STANDARD_PROPERTY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,2048}$")
_IDENTITY_FIELDS = frozenset({"id", "type", "immutable_id"})
_DIMENSIONLESS_SCALARS = frozenset(
    {"nelements", "nsites", "nperiodic_dimensions", "space_group_it_number", "year"}
)
_DIMENSIONLESS_ARRAYS = frozenset({"elements_ratios"})


def _object(value: object, name: str) -> dict[str, object]:
    if type(value) is not dict:
        raise ProviderProtocolError("provider-shape", f"Provider {name} must be an object")
    return cast(dict[str, object], value)


def _array(value: object, name: str) -> list[object]:
    if type(value) is not list:
        raise ProviderProtocolError("provider-shape", f"Provider {name} must be an array")
    return cast(list[object], value)


def _text(value: object, name: str, *, minimum: int = 1, maximum: int = 4096) -> str:
    if type(value) is not str or not minimum <= len(value) <= maximum:
        raise ProviderProtocolError("provider-shape", f"Provider {name} is invalid")
    return value


def _validate_model(model: object, document: dict[str, object], label: str) -> None:
    try:
        cast(Any, model).model_validate(document)
    except ValidationError as error:
        raise ProviderProtocolError(
            "optimade-model-rejected", f"Provider {label} violates the OPTIMADE model"
        ) from error


def _provider_messages(meta: Mapping[str, object], page_index: int) -> list[dict[str, object]]:
    raw_messages = meta.get("warnings")
    if raw_messages is None:
        return []
    messages = _array(raw_messages, "search warnings")
    projected: list[dict[str, object]] = []
    for raw in messages[:31]:
        message = _object(raw, "search warning")
        title = _text(message.get("title"), "warning title", maximum=512)
        detail = _text(message.get("detail"), "warning detail", maximum=2000)
        item: dict[str, object] = {
            "title": title,
            "detail": f"Page {page_index + 1}: {detail}",
        }
        code = message.get("code")
        if type(code) is str and 1 <= len(code) <= 128:
            item["code"] = code
        status = message.get("status")
        if type(status) is str and status.isdigit():
            numeric_status = int(status)
            if 0 <= numeric_status <= 599:
                item["http_status"] = numeric_status
        projected.append(item)
    if len(messages) > 31:
        projected.append(
            {
                "title": "Provider warnings truncated",
                "detail": (
                    f"Page {page_index + 1}: {len(messages) - 31} additional provider warnings "
                    "were omitted by the 32-message bound."
                ),
            }
        )
    return projected


def _normalized_base(value: str) -> str:
    endpoint = TrustedEndpoint.from_url(value)
    return f"{endpoint.origin}{endpoint.base_path}"


def _wire_time(response: HttpResponse) -> str:
    return response.retrieved_at.isoformat().replace("+00:00", "Z")


def _bounded_value(value: object, *, depth: int = 0) -> tuple[object, bool]:
    if depth > 8:
        return "Value omitted beyond local projection depth 8", True
    if value is None or type(value) in {bool, int}:
        return value, False
    if type(value) is float:
        if not math.isfinite(value):
            return "Non-finite provider number omitted", True
        return value, False
    if type(value) is str:
        if len(value) <= 4096:
            return value, False
        return value[:4096], True
    if type(value) is list:
        items = cast(list[object], value)
        projected: list[object] = []
        changed = len(items) > 128
        for item in items[:128]:
            bounded, item_changed = _bounded_value(item, depth=depth + 1)
            projected.append(bounded)
            changed = changed or item_changed
        return projected, changed
    if type(value) is dict:
        entries = sorted(cast(dict[str, object], value).items())
        result: dict[str, object] = {}
        changed = len(entries) > 64
        for key, item in entries[:64]:
            if len(key) > 128:
                changed = True
                continue
            bounded, item_changed = _bounded_value(item, depth=depth + 1)
            result[key] = bounded
            changed = changed or item_changed
        return result, changed
    return f"Unsupported provider value of type {type(value).__name__} omitted", True


def _input_sequence(value: object, name: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise ProviderProtocolError("input-shape", f"Input {name} must be an array")
    return tuple(cast(Sequence[object], value))


def _input_strings(
    value: object,
    name: str,
    *,
    minimum: int,
    maximum: int,
) -> tuple[str, ...]:
    items = _input_sequence(value, name)
    if not minimum <= len(items) <= maximum or any(type(item) is not str for item in items):
        raise ProviderProtocolError("input-shape", f"Input {name} is outside its array bounds")
    strings = cast(tuple[str, ...], items)
    if len(set(strings)) != len(strings):
        raise ProviderProtocolError("input-shape", f"Input {name} must contain unique values")
    return strings


@dataclass(frozen=True)
class _SearchRequest:
    providers: tuple[Literal["mp", "nmd"], ...]
    filter: str
    response_fields: tuple[str, ...]
    sort: tuple[str, ...]
    include: tuple[str, ...]
    page_limit: int
    max_pages_per_provider: int
    max_results: int
    continuation: Mapping[str, str]

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> _SearchRequest:
        providers_raw = _input_strings(payload.get("providers"), "providers", minimum=1, maximum=2)
        if any(provider not in PROVIDERS for provider in providers_raw):
            raise ProviderProtocolError(
                "provider-not-allowed", "Search provider is outside the reviewed allowlist"
            )
        filter_value = payload.get("filter")
        if type(filter_value) is not str or len(filter_value) > 4096:
            raise ProviderProtocolError("input-shape", "Search filter is invalid")
        response_fields = _input_strings(
            payload.get("response_fields"), "response_fields", minimum=1, maximum=32
        )
        if any(
            _STANDARD_PROPERTY_PATTERN.fullmatch(field) is None
            and _NAMESPACED_PROPERTY_PATTERN.fullmatch(field) is None
            for field in response_fields
        ):
            raise ProviderProtocolError(
                "input-shape", "Response fields contain a non-conforming property name"
            )
        sort = _input_strings(payload.get("sort"), "sort", minimum=0, maximum=8)
        for item in sort:
            field = item[1:] if item.startswith("-") else item
            if (
                _STANDARD_PROPERTY_PATTERN.fullmatch(field) is None
                and _NAMESPACED_PROPERTY_PATTERN.fullmatch(field) is None
            ):
                raise ProviderProtocolError(
                    "input-shape", "Sort contains a non-conforming property name"
                )
        include = _input_strings(payload.get("include"), "include", minimum=0, maximum=4)
        if any(item not in {"structures", "references"} for item in include):
            raise ProviderProtocolError("input-shape", "Include contains an unknown entry type")
        page_limit = payload.get("page_limit")
        max_pages = payload.get("max_pages_per_provider")
        max_results = payload.get("max_results")
        if type(page_limit) is not int or not 1 <= page_limit <= 50:
            raise ProviderProtocolError("input-shape", "Page limit is invalid")
        if type(max_pages) is not int or not 1 <= max_pages <= 5:
            raise ProviderProtocolError("input-shape", "Per-provider page limit is invalid")
        if type(max_results) is not int or not len(providers_raw) <= max_results <= 100:
            raise ProviderProtocolError(
                "input-shape", "Combined result limit must cover every selected provider"
            )
        continuation_raw = payload.get("continuation", {})
        if not isinstance(continuation_raw, Mapping):
            raise ProviderProtocolError("input-shape", "Continuation must be an object")
        continuation: dict[str, str] = {}
        for key, value in cast(Mapping[object, object], continuation_raw).items():
            if (
                type(key) is not str
                or key not in providers_raw
                or type(value) is not str
                or _TOKEN_PATTERN.fullmatch(value) is None
            ):
                raise ProviderProtocolError("continuation-invalid", "Continuation is invalid")
            continuation[key] = value
        parser = cast(Any, LarkParser(version=(1, 2, 0)))
        try:
            parser.parse(filter_value)
        except Exception as error:
            raise ProviderProtocolError(
                "filter-invalid", "Filter is not valid OPTIMADE 1.2 syntax"
            ) from error
        return cls(
            providers=cast(tuple[Literal["mp", "nmd"], ...], providers_raw),
            filter=filter_value,
            response_fields=response_fields,
            sort=sort,
            include=include,
            page_limit=page_limit,
            max_pages_per_provider=max_pages,
            max_results=max_results,
            continuation=continuation,
        )

    def query_document(self) -> dict[str, object]:
        return {
            "providers": list(self.providers),
            "filter": self.filter,
            "response_fields": list(self.response_fields),
            "sort": list(self.sort),
            "include": list(self.include),
            "page_limit": self.page_limit,
            "max_pages_per_provider": self.max_pages_per_provider,
            "max_results": self.max_results,
        }

    def query_digest(self, entry_type: str) -> str:
        payload = {"entry_type": entry_type, **self.query_document()}
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ExactRecordRequest:
    provider_id: Literal["mp", "nmd"]
    database_id: Literal["mp", "nmd"]
    entry_id: str
    response_fields: tuple[str, ...]
    include: tuple[str, ...]
    expected_immutable_id: str | None

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> ExactRecordRequest:
        provider_id = payload.get("provider_id")
        if type(provider_id) is not str or provider_id not in PROVIDERS:
            raise ProviderProtocolError(
                "provider-not-allowed", "Exact provider is outside the reviewed allowlist"
            )
        config = PROVIDERS[provider_id]
        database_id = payload.get("database_id")
        if database_id != config.database_id:
            raise ProviderProtocolError(
                "database-mismatch", "Exact database does not belong to the reviewed provider"
            )
        entry_id = payload.get("entry_id")
        if type(entry_id) is not str or not 1 <= len(entry_id) <= 512:
            raise ProviderProtocolError("input-shape", "Exact entry ID is invalid")
        response_fields = _input_strings(
            payload.get("response_fields"), "response_fields", minimum=1, maximum=64
        )
        if any(
            _STANDARD_PROPERTY_PATTERN.fullmatch(field) is None
            and _NAMESPACED_PROPERTY_PATTERN.fullmatch(field) is None
            for field in response_fields
        ):
            raise ProviderProtocolError(
                "input-shape", "Response fields contain a non-conforming property name"
            )
        include = _input_strings(payload.get("include"), "include", minimum=0, maximum=4)
        if any(item not in {"structures", "references"} for item in include):
            raise ProviderProtocolError("input-shape", "Include contains an unknown entry type")
        expected = payload.get("expected_immutable_id")
        if expected is not None and (type(expected) is not str or not 1 <= len(expected) <= 512):
            raise ProviderProtocolError("input-shape", "Expected immutable identity is invalid")
        return cls(
            provider_id=cast(Literal["mp", "nmd"], provider_id),
            database_id=cast(Literal["mp", "nmd"], database_id),
            entry_id=entry_id,
            response_fields=response_fields,
            include=include,
            expected_immutable_id=expected,
        )


@dataclass
class _ProviderSearch:
    provider: dict[str, object]
    hits: list[dict[str, object]]
    cursor: str | None


def _encode_cursor(provider_id: str, entry_type: str, offset: int, query_digest: str) -> str:
    document = {
        "entry_type": entry_type,
        "offset": offset,
        "provider_id": provider_id,
        "query_sha256": query_digest,
        "version": 1,
    }
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("=")


def _decode_cursor(
    token: str,
    *,
    provider_id: str,
    entry_type: str,
    query_digest: str,
) -> int:
    try:
        padded = token + "=" * (-len(token) % 4)
        raw = base64.b64decode(padded, altchars=b"-_", validate=True)
        document = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProviderProtocolError("continuation-invalid", "Continuation is malformed") from error
    if type(document) is not dict:
        raise ProviderProtocolError("continuation-invalid", "Continuation is malformed")
    values = cast(dict[str, object], document)
    offset = values.get("offset")
    if (
        set(values) != {"entry_type", "offset", "provider_id", "query_sha256", "version"}
        or values.get("version") != 1
        or values.get("provider_id") != provider_id
        or values.get("entry_type") != entry_type
        or values.get("query_sha256") != query_digest
        or type(offset) is not int
        or not 0 <= offset <= 10_000_000
    ):
        raise ProviderProtocolError(
            "continuation-invalid", "Continuation does not bind this exact bounded query"
        )
    return offset


def _composite_identity(
    config: ProviderConfig,
    entry_type: str,
    entry_id: str,
    immutable_id: str | None,
) -> dict[str, object]:
    material = "\x00".join(
        (
            config.provider_id,
            config.database_id,
            config.api_base_url,
            entry_type,
            entry_id,
            immutable_id or "",
        )
    ).encode("utf-8")
    result: dict[str, object] = {
        "composite_ref": (
            f"urn:materials-mcp:optimade:record:{hashlib.sha256(material).hexdigest()}"
        ),
        "provider_id": config.provider_id,
        "database_id": config.database_id,
        "base_url": config.api_base_url,
        "entry_type": entry_type,
        "entry_id": entry_id,
    }
    if immutable_id is not None:
        result["immutable_id"] = immutable_id
    return result


def _unit_one() -> dict[str, object]:
    return {"system": "UCUM", "identifier": "1", "symbol": "1"}


def _scientific_value(field: str, value: object) -> dict[str, object] | None:
    if type(value) is str and value:
        if len(value) <= 16_384:
            return {"value_type": "text", "value": value}
        return None
    if type(value) is bool:
        return {"value_type": "boolean", "value": value}
    if type(value) is int and field in _DIMENSIONLESS_SCALARS:
        return {"value_type": "integer", "value": value, "unit": _unit_one()}
    if type(value) is float and field in _DIMENSIONLESS_SCALARS and math.isfinite(value):
        return {"value_type": "number", "value": value, "unit": _unit_one()}
    if type(value) is list and field in _DIMENSIONLESS_ARRAYS:
        items = cast(list[object], value)
        if (
            1 <= len(items) <= 16
            and all(type(item) in {int, float} for item in items)
            and all(type(item) is int or math.isfinite(cast(float, item)) for item in items)
        ):
            return {"value_type": "number-array", "value": items, "unit": _unit_one()}
    return None


def _stable_ref(kind: str, material: str) -> str:
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return f"urn:materials-mcp:optimade:{kind}:{digest}"


class OptimadeClient:
    """No-cache client for the two exact reviewed providers."""

    def __init__(self, transport: BoundedHttpsTransport | None = None) -> None:
        self._transport = transport or BoundedHttpsTransport()
        self._registry = TrustedEndpoint.from_url(REGISTRY_BASE_URL)
        self._index_endpoints = {
            provider_id: TrustedEndpoint.from_url(config.index_base_url)
            for provider_id, config in PROVIDERS.items()
        }
        self._api_endpoints = {
            provider_id: TrustedEndpoint.from_url(config.api_base_url)
            for provider_id, config in PROVIDERS.items()
        }

    def _links(self, endpoint: TrustedEndpoint) -> tuple[HttpResponse, dict[str, object]]:
        response = self._transport.get(endpoint, "/v1/links", max_bytes=1_048_576)
        document = decode_json_object(response)
        _validate_model(LinksResponse, document, "links response")
        return response, document

    def _resolve_index(self, config: ProviderConfig) -> str:
        response, document = self._links(self._index_endpoints[config.provider_id])
        matches: list[dict[str, object]] = []
        for raw in _array(document.get("data"), "links data"):
            entry = _object(raw, "link entry")
            attributes = _object(entry.get("attributes"), "link attributes")
            if entry.get("id") == config.database_id and attributes.get("link_type") == "child":
                matches.append(attributes)
        if len(matches) != 1:
            raise ProviderProtocolError(
                "index-resolution", "Reviewed database does not resolve to one child endpoint"
            )
        actual = _text(matches[0].get("base_url"), "child base URL", maximum=2048)
        if _normalized_base(actual) != _normalized_base(config.api_base_url):
            raise ProviderProtocolError(
                "index-resolution", "Reviewed database child endpoint changed"
            )
        return response.sha256

    def list_providers(self, payload: Mapping[str, object] | None = None) -> dict[str, object]:
        include_registry_only = True
        registry_entry_limit = 100
        if payload is not None:
            if set(payload) != {"include_registry_only", "registry_entry_limit"}:
                raise ProviderProtocolError(
                    "input-shape", "Provider list input fields do not match the contract"
                )
            include_value = payload.get("include_registry_only")
            limit_value = payload.get("registry_entry_limit")
            if type(include_value) is not bool:
                raise ProviderProtocolError(
                    "input-shape", "Provider registry-only selection must be boolean"
                )
            if type(limit_value) is not int or not 1 <= limit_value <= 100:
                raise ProviderProtocolError(
                    "input-shape", "Provider registry entry limit is invalid"
                )
            include_registry_only = include_value
            registry_entry_limit = limit_value
        response, document = self._links(self._registry)
        meta = _object(document.get("meta"), "links metadata")
        api_version = _text(meta.get("api_version"), "registry API version", maximum=32)
        records = _array(document.get("data"), "registry data")
        if len(records) > 100:
            raise ProviderProtocolError(
                "registry-too-large", "Registry exceeds the declared provider count limit"
            )
        providers: list[dict[str, object]] = []
        result_warnings: list[str] = []
        for raw in records:
            entry = _object(raw, "registry link entry")
            attributes = _object(entry.get("attributes"), "registry link attributes")
            provider_id = _text(entry.get("id"), "registry provider ID", maximum=64)
            name = _text(attributes.get("name"), "registry provider name", maximum=512)
            description_value = attributes.get("description", "")
            description = _text(
                description_value,
                "registry provider description",
                minimum=0,
                maximum=4096,
            )
            link_type = _text(attributes.get("link_type"), "registry link type", maximum=32)
            base_url = attributes.get("base_url")
            normalized_index: str | None = None
            item_warnings: list[str] = []
            if base_url is None:
                item_warnings.append(
                    "Registry entry supplies no base URL and is not execution authority."
                )
            elif type(base_url) is str:
                try:
                    normalized_index = _normalized_base(base_url)
                except TransportError:
                    item_warnings.append(
                        "Registry base URL is not bounded HTTPS and is not execution authority."
                    )
            else:
                item_warnings.append(
                    "Registry base URL has an invalid type and is not execution authority."
                )
            item: dict[str, object] = {
                "provider_id": provider_id,
                "name": name,
                "description": description,
                "registry_link_type": link_type,
                "index_base_url": normalized_index,
                "support_status": "registry-only",
                "warnings": item_warnings,
            }
            homepage = attributes.get("homepage")
            if type(homepage) is str:
                try:
                    item["homepage"] = _normalized_base(homepage)
                except TransportError:
                    cast(list[str], item["warnings"]).append(
                        "Registry homepage was omitted because it is not a bounded HTTPS URL."
                    )
            config = PROVIDERS.get(provider_id)
            if config is not None:
                if normalized_index != _normalized_base(config.index_base_url):
                    item["support_status"] = "rejected"
                    cast(list[str], item["warnings"]).append(
                        "Reviewed registry indirection changed; execution is disabled."
                    )
                else:
                    try:
                        index_hash = self._resolve_index(config)
                    except ProviderProtocolError:
                        item["support_status"] = "rejected"
                        cast(list[str], item["warnings"]).append(
                            "Reviewed child endpoint resolution failed; execution is disabled."
                        )
                    else:
                        item.update(
                            {
                                "database_id": config.database_id,
                                "api_base_url": config.api_base_url,
                                "support_status": "supported",
                                "index_response_sha256": index_hash,
                            }
                        )
            providers.append(item)
        upstream_more = meta.get("more_data_available")
        if type(upstream_more) is not bool:
            raise ProviderProtocolError(
                "provider-shape", "Registry pagination declaration is invalid"
            )
        eligible = (
            providers
            if include_registry_only
            else [item for item in providers if item["provider_id"] in PROVIDERS]
        )
        selected_providers = eligible[:registry_entry_limit]
        locally_truncated = len(eligible) > len(selected_providers)
        more = upstream_more or locally_truncated
        if upstream_more:
            result_warnings.append(
                "Registry reports additional pages; this bounded call does not follow them."
            )
        if locally_truncated:
            result_warnings.append(
                "Registry entries were explicitly truncated by registry_entry_limit."
            )
        return {
            "contract": f"{SCHEMA_BASE}provider-list-result.schema.json",
            "profile_version": PROFILE_VERSION,
            "retrieved_at": _wire_time(response),
            "registry": {
                "uri": REGISTRY_LINKS_URL,
                "api_version": api_version,
                "response_sha256": response.sha256,
                "data_returned": len(selected_providers),
                "more_data_available": more,
            },
            "providers": selected_providers,
            "warnings": result_warnings,
        }

    def _versions(self, config: ProviderConfig) -> dict[str, object]:
        endpoint = self._api_endpoints[config.provider_id]
        try:
            response = self._transport.get(
                endpoint,
                "/versions",
                accepted_content_types=frozenset(
                    {"text/csv", "application/json", "application/vnd.api+json"}
                ),
                expected_statuses=frozenset({200, 404}),
                max_bytes=65_536,
            )
        except TransportError as error:
            return {
                "outcome": "failed",
                "http_status": error.http_status or 0,
                "advertised_versions": [],
            }
        if response.status == 404:
            return {"outcome": "unsupported", "http_status": 404, "advertised_versions": []}
        try:
            lines = [line.strip() for line in response.body.decode("utf-8").splitlines()]
        except UnicodeDecodeError:
            return {"outcome": "failed", "http_status": 200, "advertised_versions": []}
        values = lines[1:] if lines and lines[0].lower() == "version" else lines
        advertised = [
            value
            for value in values
            if value and _ADVERTISED_VERSION_PATTERN.fullmatch(value) is not None
        ]
        if len(advertised) > 32:
            advertised = advertised[:32]
        return {
            "outcome": "success",
            "http_status": 200,
            "advertised_versions": list(dict.fromkeys(advertised)),
        }

    def _entry_info(
        self,
        config: ProviderConfig,
        entry_type: str,
        *,
        include_property_definitions: bool,
        property_limit: int,
    ) -> dict[str, object]:
        response = self._transport.get(
            self._api_endpoints[config.provider_id],
            f"/v1/info/{entry_type}",
            max_bytes=2 * 1024 * 1024,
        )
        document = decode_json_object(response)
        data = _object(document.get("data"), "entry info data")
        properties = _object(data.get("properties"), "entry info properties")
        warnings: list[str] = []
        validation_document = copy.deepcopy(document)
        validation_data = _object(validation_document.get("data"), "entry info data")
        if "id" not in validation_data:
            validation_data["id"] = entry_type
            warnings.append(
                "Provider omitted the required entry-info resource ID; the requested endpoint "
                "identity was supplied only to validate the remaining standard model."
            )
        valid_model_names = [
            name for name in properties if _MODEL_PROPERTY_PATTERN.fullmatch(name) is not None
        ]
        validation_data["properties"] = {
            name: copy.deepcopy(properties[name]) for name in valid_model_names
        }
        output_fields = validation_data.get("output_fields_by_format")
        if type(output_fields) is dict:
            output_mapping = cast(dict[str, object], output_fields)
            for format_name, raw_fields in tuple(output_mapping.items()):
                if type(raw_fields) is list:
                    output_mapping[format_name] = [
                        field
                        for field in cast(list[object], raw_fields)
                        if type(field) is str
                        and _MODEL_PROPERTY_PATTERN.fullmatch(field) is not None
                    ]
        invalid_names = sorted(set(properties) - set(valid_model_names))
        if invalid_names:
            warnings.append(
                f"{len(invalid_names)} non-conforming provider property names were omitted."
            )
        _validate_model(EntryInfoResponse, validation_document, f"{entry_type} info response")
        names = sorted(
            name for name in properties if _OUTPUT_PROPERTY_PATTERN.fullmatch(name) is not None
        )
        selected = names[:property_limit] if include_property_definitions else []
        projected: list[dict[str, object]] = []
        changed = False
        for name in selected:
            bounded, item_changed = _bounded_value(properties[name])
            projected.append({"name": name, "definition": bounded})
            changed = changed or item_changed
        omitted_count = len(properties) - len(selected)
        if not include_property_definitions and properties:
            warnings.append("Property definitions were omitted because this request disabled them.")
        elif omitted_count > len(invalid_names):
            warnings.append(
                f"{omitted_count - len(invalid_names)} property definitions were omitted by the "
                f"{property_limit}-property limit."
            )
        if changed:
            warnings.append(
                "One or more property definitions were explicitly reduced to local value bounds."
            )
        return {
            "entry_type": entry_type,
            "endpoint_status": response.status,
            "property_count": len(properties),
            "returned_property_count": len(selected),
            "omitted_property_count": omitted_count,
            "properties": projected,
            "response_sha256": response.sha256,
            "warnings": warnings,
        }

    def inspect_provider(self, payload: str | Mapping[str, object]) -> dict[str, object]:
        if isinstance(payload, str):
            provider_id = payload
            entry_types = ("structures", "references")
            include_property_definitions = True
            property_limit = 128
        else:
            if set(payload) != {
                "provider_id",
                "entry_types",
                "include_property_definitions",
                "property_limit",
            }:
                raise ProviderProtocolError(
                    "input-shape", "Provider inspection input fields do not match the contract"
                )
            provider_value = payload.get("provider_id")
            if type(provider_value) is not str:
                raise ProviderProtocolError("input-shape", "Provider ID must be a string")
            provider_id = provider_value
            entry_types = _input_strings(
                payload.get("entry_types"), "entry_types", minimum=1, maximum=2
            )
            if any(item not in {"structures", "references"} for item in entry_types):
                raise ProviderProtocolError("input-shape", "Inspection entry types are invalid")
            include_value = payload.get("include_property_definitions")
            if type(include_value) is not bool:
                raise ProviderProtocolError(
                    "input-shape", "Property-definition selection must be boolean"
                )
            limit_value = payload.get("property_limit")
            if type(limit_value) is not int or not 1 <= limit_value <= 128:
                raise ProviderProtocolError("input-shape", "Inspection property limit is invalid")
            include_property_definitions = include_value
            property_limit = limit_value
        config = PROVIDERS.get(provider_id)
        if config is None:
            raise ProviderProtocolError(
                "provider-not-allowed", "Provider is outside the reviewed execution allowlist"
            )
        self._resolve_index(config)
        response = self._transport.get(
            self._api_endpoints[provider_id], "/v1/info", max_bytes=1_048_576
        )
        document = decode_json_object(response)
        _validate_model(InfoResponse, document, "base info response")
        meta = _object(document.get("meta"), "base info metadata")
        api_version = _text(meta.get("api_version"), "provider API version", maximum=32)
        if _VERSION_PATTERN.fullmatch(api_version) is None:
            raise ProviderProtocolError(
                "api-version", "Provider API version is not an exact semantic 1.x version"
            )
        implementation = _object(meta.get("implementation"), "implementation metadata")
        source_url = _text(
            implementation.get("source_url"), "implementation source URL", maximum=2048
        )
        source_endpoint = TrustedEndpoint.from_url(source_url)
        source = f"{source_endpoint.origin}{source_endpoint.base_path}"
        warnings: list[str] = []
        if not config.rights.is_current(response.retrieved_at):
            warnings.append(
                "The provider rights review is expired; persistence and export remain disabled."
            )
        if config.rights.review_status == "unavailable":
            warnings.append(
                "Applicable terms were unavailable for review; access conveys no "
                "redistribution permission."
            )
        return {
            "contract": f"{SCHEMA_BASE}provider-inspect-result.schema.json",
            "profile_version": PROFILE_VERSION,
            "provider_id": config.provider_id,
            "database_id": config.database_id,
            "index_base_url": config.index_base_url,
            "api_base_url": config.api_base_url,
            "retrieved_at": _wire_time(response),
            "negotiation": {
                "reported_api_version": api_version,
                "selected_api_version": OPTIMADE_BASELINE_VERSION,
                "versions_endpoint": self._versions(config),
                "supported": is_supported_api_version(api_version),
            },
            "implementation": {
                "name": _text(implementation.get("name"), "implementation name", maximum=512),
                "version": _text(
                    implementation.get("version"), "implementation version", maximum=128
                ),
                "source_url": source,
            },
            "entry_types": [
                self._entry_info(
                    config,
                    entry_type,
                    include_property_definitions=include_property_definitions,
                    property_limit=property_limit,
                )
                for entry_type in entry_types
            ],
            "rights": config.rights.to_document(),
            "warnings": warnings,
        }

    def _project_included(
        self,
        relationships: dict[str, object],
        included: list[object],
    ) -> tuple[list[object], bool]:
        wanted: set[tuple[str, str]] = set()
        for relationship in relationships.values():
            if type(relationship) is not dict:
                continue
            linkage = cast(dict[str, object], relationship).get("data")
            candidates: list[object] = (
                cast(list[object], linkage) if type(linkage) is list else [linkage]
            )
            for candidate in candidates:
                if type(candidate) is not dict:
                    continue
                item = cast(dict[str, object], candidate)
                if type(item.get("type")) is str and type(item.get("id")) is str:
                    wanted.add((cast(str, item["type"]), cast(str, item["id"])))
        selected: list[object] = []
        changed = False
        for raw in included:
            if type(raw) is not dict:
                changed = True
                continue
            item = cast(dict[str, object], raw)
            key = (item.get("type"), item.get("id"))
            if key not in wanted:
                continue
            bounded, item_changed = _bounded_value(item)
            if len(selected) < 16:
                selected.append(bounded)
            else:
                changed = True
            changed = changed or item_changed
        return selected, changed

    def _project_hit(
        self,
        *,
        config: ProviderConfig,
        entry_type: str,
        resource: dict[str, object],
        included: list[object],
        request: _SearchRequest,
        response: HttpResponse,
        page_index: int,
        resource_index: int,
    ) -> dict[str, object]:
        entry_id = _text(resource.get("id"), "entry ID", maximum=512)
        resource_type = _text(resource.get("type"), "entry type", maximum=128)
        if resource_type != entry_type:
            raise ProviderProtocolError(
                "entry-type-mismatch", "Provider returned the wrong entry resource type"
            )
        attributes_value = resource.get("attributes", {})
        attributes = _object(attributes_value, "entry attributes")
        immutable_value = attributes.get("immutable_id")
        immutable_id = (
            _text(immutable_value, "immutable ID", maximum=512)
            if immutable_value is not None
            else None
        )
        warnings: list[str] = []
        standard: dict[str, object] = {}
        namespaced: dict[str, object] = {}
        returned = 0
        for field in request.response_fields:
            if field == "id":
                returned += 1
                continue
            if field == "type":
                returned += 1
                continue
            if field not in attributes:
                continue
            bounded, changed = _bounded_value(attributes[field])
            if field.startswith("_"):
                if _NAMESPACED_PROPERTY_PATTERN.fullmatch(field) is None:
                    warnings.append(
                        f"Selected provider field {field!r} was omitted because its name "
                        "is invalid."
                    )
                    continue
                namespaced[field] = bounded
            else:
                standard[field] = bounded
            returned += 1
            if changed:
                warnings.append(
                    f"Selected field {field!r} was explicitly reduced to local value bounds."
                )
        relationships_value = resource.get("relationships", {})
        relationships_raw = _object(relationships_value, "entry relationships")
        relationships: dict[str, object] = {}
        for name, value in sorted(relationships_raw.items())[:8]:
            if _STANDARD_PROPERTY_PATTERN.fullmatch(name) is None:
                warnings.append(f"Relationship {name!r} was omitted because its name is invalid.")
                continue
            bounded, changed = _bounded_value(value)
            relationships[name] = bounded
            if changed:
                warnings.append(
                    f"Relationship {name!r} was explicitly reduced to local value bounds."
                )
        if len(relationships_raw) > 8:
            warnings.append(
                f"{len(relationships_raw) - 8} relationships were omitted by the local limit."
            )
        included_items, included_changed = self._project_included(relationships_raw, included)
        if included_changed:
            warnings.append(
                "Included relationship resources were explicitly reduced to local bounds."
            )
        selected = set(request.response_fields)
        unrequested = sum(1 for name in attributes if name not in selected)
        return {
            "identity": _composite_identity(config, entry_type, entry_id, immutable_id),
            "standard_attributes": standard,
            "namespaced_attributes": namespaced,
            "relationships": relationships,
            "included": included_items,
            "selected_field_count": len(request.response_fields),
            "returned_selected_field_count": returned,
            "omitted_selected_field_count": len(request.response_fields) - returned,
            "unrequested_field_count": unrequested,
            "source_uri": response.request_uri,
            "source_response_sha256": response.sha256,
            "page_index": page_index,
            "resource_index": resource_index,
            "retrieved_at": _wire_time(response),
            "rights": config.rights.to_document(),
            "citation_refs": [config.citation.citation_ref],
            "warnings": warnings,
        }

    def _search_parameters(
        self,
        request: _SearchRequest,
        *,
        page_limit: int,
        page_offset: int,
    ) -> tuple[tuple[str, str], ...]:
        fields = list(request.response_fields)
        if "immutable_id" not in fields:
            fields.append("immutable_id")
        parameters: list[tuple[str, str]] = [
            ("filter", request.filter),
            ("response_fields", ",".join(fields)),
            ("page_limit", str(page_limit)),
            ("page_offset", str(page_offset)),
        ]
        if request.sort:
            parameters.append(("sort", ",".join(request.sort)))
        if request.include:
            parameters.append(("include", ",".join(request.include)))
        return tuple(parameters)

    def _failed_search(
        self,
        *,
        config: ProviderConfig,
        request: _SearchRequest,
        entry_type: str,
        offset: int,
        request_uris: list[str],
        response_hashes: list[str],
        hits: list[dict[str, object]],
        pages_returned: int,
        data_available: int | None,
        api_version: str | None,
        implementation: tuple[str, str] | None,
        provider_warnings: list[dict[str, object]],
        error: ProviderProtocolError | TransportError,
    ) -> _ProviderSearch:
        retryable = isinstance(error, TransportError) and error.retryable
        status = error.http_status if isinstance(error, TransportError) else None
        failure: dict[str, object] = {
            "code": error.code,
            "http_status": status or 0,
            "title": "Bounded provider request failed",
            "detail": f"The {entry_type} request failed at the {error.code} boundary.",
            "retryable": retryable,
        }
        cursor = _encode_cursor(
            config.provider_id,
            entry_type,
            offset,
            request.query_digest(entry_type),
        )
        provider: dict[str, object] = {
            "provider_id": config.provider_id,
            "database_id": config.database_id,
            "api_base_url": config.api_base_url,
            "api_version": api_version,
            "outcome": "failed",
            "pages_returned": pages_returned,
            "records_returned": len(hits),
            "data_available": data_available,
            "more_data_available": True,
            "request_uris": request_uris,
            "response_sha256": response_hashes,
            "rights": config.rights.to_document(),
            "citation_ref": config.citation.citation_ref,
            "next_cursor": cursor,
            "warnings": provider_warnings,
            "failure": failure,
        }
        if implementation is not None:
            provider["implementation_name"] = implementation[0]
            provider["implementation_version"] = implementation[1]
        return _ProviderSearch(provider=provider, hits=hits, cursor=cursor)

    def _search_provider(
        self,
        config: ProviderConfig,
        entry_type: Literal["structures", "references"],
        request: _SearchRequest,
        quota: int,
    ) -> _ProviderSearch:
        endpoint = self._api_endpoints[config.provider_id]
        digest = request.query_digest(entry_type)
        token = request.continuation.get(config.provider_id)
        offset = (
            _decode_cursor(
                token,
                provider_id=config.provider_id,
                entry_type=entry_type,
                query_digest=digest,
            )
            if token is not None
            else 0
        )
        hits: list[dict[str, object]] = []
        request_uris: list[str] = []
        response_hashes: list[str] = []
        provider_warnings: list[dict[str, object]] = []
        seen_records: set[tuple[str, str]] = set()
        data_available: int | None = None
        api_version: str | None = None
        implementation: tuple[str, str] | None = None
        more_data_available = False
        for page_index in range(request.max_pages_per_provider):
            remaining = quota - len(hits)
            if remaining <= 0:
                more_data_available = True
                break
            page_limit = min(request.page_limit, remaining)
            parameters = self._search_parameters(request, page_limit=page_limit, page_offset=offset)
            _, request_uri = endpoint.request_target(f"/v1/{entry_type}", parameters)
            request_uris.append(request_uri)
            try:
                response = self._transport.get(
                    endpoint,
                    f"/v1/{entry_type}",
                    query=parameters,
                    max_bytes=2 * 1024 * 1024,
                )
                if response.sha256 in response_hashes:
                    raise ProviderProtocolError(
                        "pagination-loop",
                        "Provider repeated an identical response for a new page offset",
                    )
                document = decode_json_object(response)
                model = (
                    StructureResponseMany if entry_type == "structures" else ReferenceResponseMany
                )
                _validate_model(model, document, f"{entry_type} search response")
                meta = _object(document.get("meta"), "search metadata")
                observed_version = _text(meta.get("api_version"), "search API version", maximum=32)
                if not is_supported_api_version(observed_version):
                    raise ProviderProtocolError(
                        "api-version-unsupported",
                        "Search response is outside the verified stable OPTIMADE 1.2 patch line",
                    )
                if api_version is not None and observed_version != api_version:
                    raise ProviderProtocolError(
                        "api-version-changed", "Provider API version changed within one search"
                    )
                api_version = observed_version
                implementation_value = _object(
                    meta.get("implementation"), "search implementation metadata"
                )
                observed_implementation = (
                    _text(
                        implementation_value.get("name"),
                        "search implementation name",
                        maximum=512,
                    ),
                    _text(
                        implementation_value.get("version"),
                        "search implementation version",
                        maximum=128,
                    ),
                )
                if implementation is not None and observed_implementation != implementation:
                    raise ProviderProtocolError(
                        "implementation-changed",
                        "Provider implementation changed within one search",
                    )
                implementation = observed_implementation
                available_value = meta.get("data_available")
                if available_value is not None and (
                    type(available_value) is not int or available_value < 0
                ):
                    raise ProviderProtocolError(
                        "provider-shape", "Search data-available count is invalid"
                    )
                data_available = available_value
                more_value = meta.get("more_data_available")
                if type(more_value) is not bool:
                    raise ProviderProtocolError(
                        "provider-shape", "Search pagination declaration is invalid"
                    )
                records = _array(document.get("data"), "search data")
                if len(records) > page_limit:
                    raise ProviderProtocolError(
                        "page-limit-violated", "Provider exceeded the requested page limit"
                    )
                included_value = document.get("included", [])
                included = _array(included_value, "included resources")
                page_hits: list[dict[str, object]] = []
                for resource_index, raw in enumerate(records):
                    resource = _object(raw, "search resource")
                    resource_type = _text(resource.get("type"), "search resource type", maximum=32)
                    resource_id = _text(resource.get("id"), "search resource ID", maximum=512)
                    identity = (resource_type, resource_id)
                    if identity in seen_records:
                        raise ProviderProtocolError(
                            "pagination-loop",
                            "Provider repeated a record within the bounded pagination window",
                        )
                    seen_records.add(identity)
                    page_hits.append(
                        self._project_hit(
                            config=config,
                            entry_type=entry_type,
                            resource=resource,
                            included=included,
                            request=request,
                            response=response,
                            page_index=page_index,
                            resource_index=resource_index,
                        )
                    )
                if available_value is not None and available_value < offset + len(page_hits):
                    raise ProviderProtocolError(
                        "pagination-inconsistent",
                        "Provider data-available count is smaller than returned records",
                    )
                hits.extend(page_hits)
                response_hashes.append(response.sha256)
                page_messages = _provider_messages(meta, page_index)
                remaining_message_slots = 32 - len(provider_warnings)
                if len(page_messages) <= remaining_message_slots:
                    provider_warnings.extend(page_messages[:remaining_message_slots])
                elif remaining_message_slots > 0:
                    provider_warnings.extend(page_messages[: remaining_message_slots - 1])
                    provider_warnings.append(
                        {
                            "title": "Provider warnings truncated",
                            "detail": (
                                "Additional provider warnings were omitted by the call bound."
                            ),
                        }
                    )
                elif provider_warnings:
                    provider_warnings[-1] = {
                        "title": "Provider warnings truncated",
                        "detail": "Additional provider warnings were omitted by the call bound.",
                    }
                offset += len(records)
                more_data_available = more_value
                if not more_value:
                    break
                if not records:
                    raise ProviderProtocolError(
                        "pagination-stalled",
                        "Provider reported more data but returned an empty page",
                    )
            except (ProviderProtocolError, TransportError) as error:
                return self._failed_search(
                    config=config,
                    request=request,
                    entry_type=entry_type,
                    offset=offset,
                    request_uris=request_uris,
                    response_hashes=response_hashes,
                    hits=hits,
                    pages_returned=len(response_hashes),
                    data_available=data_available,
                    api_version=api_version,
                    implementation=implementation,
                    provider_warnings=provider_warnings,
                    error=error,
                )
        cursor = (
            _encode_cursor(config.provider_id, entry_type, offset, digest)
            if more_data_available
            else None
        )
        provider: dict[str, object] = {
            "provider_id": config.provider_id,
            "database_id": config.database_id,
            "api_base_url": config.api_base_url,
            "api_version": api_version,
            "outcome": "success" if hits else "empty",
            "pages_returned": len(response_hashes),
            "records_returned": len(hits),
            "data_available": data_available,
            "more_data_available": more_data_available,
            "request_uris": request_uris,
            "response_sha256": response_hashes,
            "rights": config.rights.to_document(),
            "citation_ref": config.citation.citation_ref,
            "warnings": provider_warnings,
        }
        if implementation is not None:
            provider["implementation_name"] = implementation[0]
            provider["implementation_version"] = implementation[1]
        if cursor is not None:
            provider["next_cursor"] = cursor
        return _ProviderSearch(provider=provider, hits=hits, cursor=cursor)

    def search(
        self,
        entry_type: Literal["structures", "references"],
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        request = _SearchRequest.from_payload(payload)
        count = len(request.providers)
        base_quota, remainder = divmod(request.max_results, count)
        quotas = [base_quota + (1 if index < remainder else 0) for index in range(count)]
        with ThreadPoolExecutor(max_workers=count, thread_name_prefix="optimade-read") as pool:
            futures = [
                pool.submit(
                    self._search_provider,
                    PROVIDERS[provider_id],
                    entry_type,
                    request,
                    quotas[index],
                )
                for index, provider_id in enumerate(request.providers)
            ]
            results = [future.result() for future in futures]
        providers = [result.provider for result in results]
        hits = [hit for result in results for hit in result.hits]
        continuation = {
            request.providers[index]: result.cursor
            for index, result in enumerate(results)
            if result.cursor is not None
        }
        failed = [
            cast(str, provider["provider_id"])
            for provider in providers
            if provider["outcome"] == "failed"
        ]
        warnings = [
            f"Provider {provider_id} failed; its bounded failure is preserved separately."
            for provider_id in failed
        ]
        return {
            "contract": f"{SCHEMA_BASE}search-result.schema.json",
            "profile_version": PROFILE_VERSION,
            "entry_type": entry_type,
            "status": "partial" if failed else "complete",
            "produced_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "query": request.query_document(),
            "providers": providers,
            "hits": hits,
            "total_returned": len(hits),
            "more_data_available": any(
                cast(bool, provider["more_data_available"]) for provider in providers
            ),
            "continuation": continuation,
            "citations": [PROVIDERS[item].citation.to_document() for item in request.providers],
            "warnings": warnings,
        }

    def search_structures(self, payload: Mapping[str, object]) -> dict[str, object]:
        return self.search("structures", payload)

    def search_references(self, payload: Mapping[str, object]) -> dict[str, object]:
        return self.search("references", payload)

    def _exact_parameters(self, request: ExactRecordRequest) -> tuple[tuple[str, str], ...]:
        fields = list(request.response_fields)
        if "immutable_id" not in fields:
            fields.append("immutable_id")
        parameters: list[tuple[str, str]] = [("response_fields", ",".join(fields))]
        if request.include:
            parameters.append(("include", ",".join(request.include)))
        return tuple(parameters)

    def _result_bundle(
        self,
        *,
        config: ProviderConfig,
        entry_type: Literal["structures", "references"],
        request: ExactRecordRequest,
        response: HttpResponse,
        document: dict[str, object],
    ) -> dict[str, object]:
        meta = _object(document.get("meta"), "exact response metadata")
        api_version = _text(meta.get("api_version"), "exact API version", maximum=32)
        if not is_supported_api_version(api_version):
            raise ProviderProtocolError(
                "api-version-unsupported",
                "Exact response is outside the verified stable OPTIMADE 1.2 patch line",
            )
        resource = _object(document.get("data"), "exact response data")
        returned_type = _text(resource.get("type"), "exact entry type", maximum=128)
        returned_id = _text(resource.get("id"), "exact entry ID", maximum=512)
        if returned_type != entry_type or returned_id != request.entry_id:
            raise ProviderProtocolError(
                "identity-mismatch", "Provider returned a different exact record identity"
            )
        attributes = _object(resource.get("attributes", {}), "exact entry attributes")
        immutable_value = attributes.get("immutable_id")
        immutable_id = (
            _text(immutable_value, "exact immutable ID", maximum=512)
            if immutable_value is not None
            else None
        )
        if request.expected_immutable_id is not None and (
            immutable_id != request.expected_immutable_id
        ):
            raise ProviderProtocolError(
                "immutable-identity-mismatch",
                "Provider record does not match the expected immutable identity",
            )
        identity = _composite_identity(config, entry_type, returned_id, immutable_id)
        entity_ref = cast(str, identity["composite_ref"])
        provenance_ref = _stable_ref("provenance", f"{entity_ref}\x00{response.sha256}")
        artifact_ref = _stable_ref("artifact", f"{response.request_uri}\x00{response.sha256}")
        source_ref = _stable_ref("source", f"{response.request_uri}\x00{response.sha256}")
        result_ref = _stable_ref("result", f"{entity_ref}\x00{response.sha256}")
        identifiers: list[dict[str, object]] = [
            {"scheme": "optimade-provider", "value": config.provider_id},
            {"scheme": "optimade-database", "value": config.database_id},
            {"scheme": "optimade-entry-type", "value": entry_type},
            {
                "scheme": "optimade-entry-id",
                "value": returned_id,
                "uri": response.request_uri,
            },
            {"scheme": "optimade-composite", "value": entity_ref},
        ]
        if immutable_id is not None:
            identifiers.append({"scheme": "optimade-immutable-id", "value": immutable_id})
        label_candidates = (
            (
                attributes.get("chemical_formula_descriptive"),
                attributes.get("chemical_formula_reduced"),
            )
            if entry_type == "structures"
            else (attributes.get("title"),)
        )
        label = next(
            (value for value in label_candidates if type(value) is str and 1 <= len(value) <= 4096),
            f"{config.name} {entry_type} record {returned_id}",
        )
        properties: list[dict[str, object]] = []
        transformations: list[dict[str, object]] = [
            {
                "operation": "identifier-mapping",
                "source_locator": "/data/id",
                "target_pointer": "/entities/0",
                "note": "Provider and database context are retained in the composite identity.",
            }
        ]
        warnings: list[str] = [
            "The checksummed source record remains at its provider URI; "
            "this R0 result does not persist its bytes.",
            "Provider-supplied scientific values are source-reported and "
            "were not independently assessed.",
        ]
        for field in request.response_fields:
            if field in _IDENTITY_FIELDS:
                continue
            if field not in attributes:
                warnings.append(f"Requested field {field!r} was not returned by the provider.")
                continue
            scientific_value = _scientific_value(field, attributes[field])
            if scientific_value is None:
                warnings.append(
                    f"Requested field {field!r} is preserved only in the source artifact because "
                    "the profile cannot represent it inline without inventing units or structure."
                )
                continue
            property_index = len(properties)
            property_ref = _stable_ref("property", f"{entity_ref}\x00{field}\x00{response.sha256}")
            properties.append(
                {
                    "property_ref": property_ref,
                    "property_id": (f"urn:optimade:{OPTIMADE_CONTRACT_LINE}:{entry_type}:{field}"),
                    "label": field.replace("_", " "),
                    "subject_ref": entity_ref,
                    "value": scientific_value,
                    "condition_refs": [],
                    "uncertainty": {
                        "status": "not-reported",
                        "reason": (
                            "The OPTIMADE source response did not report uncertainty "
                            "for this field."
                        ),
                    },
                    "evidence_refs": [artifact_ref],
                }
            )
            transformations.append(
                {
                    "operation": "copy",
                    "source_locator": f"/data/attributes/{field}",
                    "target_pointer": f"/properties/{property_index}/value",
                }
            )
        if config.rights.review_status == "unavailable":
            warnings.append(
                "Applicable provider terms were unavailable for review; "
                "redistribution remains unknown."
            )
        if not config.rights.is_current(response.retrieved_at):
            warnings.append(
                "The provider rights review is expired; persistence and export remain disabled."
            )
        media_type = response.headers.get("content-type", "application/vnd.api+json").split(
            ";", maxsplit=1
        )[0]
        return {
            "contract": (
                "https://schemas.autonomouslab.io/materials-mcp/0.2.0/result-bundle.schema.json"
            ),
            "profile_version": PROFILE_VERSION,
            "result_ref": result_ref,
            "produced_at": _wire_time(response),
            "status": "complete",
            "entities": [
                {
                    "entity_ref": entity_ref,
                    "entity_type": "structure" if entry_type == "structures" else "publication",
                    "label": label,
                    "identifiers": identifiers,
                    "extensions": {f"{SCHEMA_BASE}record-identity.extension.schema.json": identity},
                }
            ],
            "properties": properties,
            "conditions": [],
            "artifacts": [
                {
                    "artifact_ref": artifact_ref,
                    "uri": response.request_uri,
                    "media_type": media_type,
                    "size_bytes": len(response.body),
                    "sha256": response.sha256,
                    "role": "source-record",
                    "access_scope": "public",
                    "provenance_ref": provenance_ref,
                }
            ],
            "quality": {
                "status": "not-assessed",
                "reason": (
                    "This integration validated protocol shape and provenance but did not "
                    "independently assess the provider's scientific record."
                ),
                "criteria": [],
                "limitations": [
                    "Protocol conformance is not scientific validation.",
                    "Only profile-representable selected scalars are projected inline.",
                ],
            },
            "provenance": {
                "provenance_ref": provenance_ref,
                "activity_ref": _stable_ref(
                    "activity",
                    f"{request.provider_id}\x00{response.request_uri}\x00{response.sha256}",
                ),
                "activity_type": "source-projection",
                "started_at": response.requested_at.isoformat().replace("+00:00", "Z"),
                "ended_at": _wire_time(response),
                "producer": {
                    "producer_ref": "https://schemas.autonomouslab.io/materials-mcp/plugins/optimade",
                    "name": "Materials MCP OPTIMADE",
                    "version": "0.1.0a1",
                },
                "inputs": [response.request_uri],
                "parameters": [
                    {"name": "provider", "value": request.provider_id},
                    {"name": "database", "value": request.database_id},
                    {"name": "entry-type", "value": entry_type},
                    {"name": "entry-id", "value": request.entry_id},
                    {
                        "name": "response-fields",
                        "value": json.dumps(list(request.response_fields), separators=(",", ":")),
                    },
                    {
                        "name": "include",
                        "value": json.dumps(list(request.include), separators=(",", ":")),
                    },
                ],
                "environment": {
                    "status": "reported",
                    "software": [
                        {"name": "materials-mcp-optimade", "version": "0.1.0a1"},
                        {"name": "optimade", "version": distribution_version("optimade")},
                    ],
                    "platform": platform.platform(),
                },
                "sources": [
                    {
                        "source_ref": source_ref,
                        "source_type": "database-record",
                        "title": f"{config.name} OPTIMADE {entry_type} record {returned_id}",
                        "uri": response.request_uri,
                        "version": api_version,
                        "retrieved_at": _wire_time(response),
                        "rights": {
                            "basis": config.rights.basis,
                            "identifier": config.rights.identifier,
                            "uri": config.rights.terms_uri,
                            "redistribution": config.rights.redistribution,
                            "attribution": config.rights.attribution,
                        },
                        "size_bytes": len(response.body),
                        "sha256": response.sha256,
                        "transformations": transformations,
                        "citation_refs": [config.citation.citation_ref],
                    }
                ],
            },
            "citations": [config.citation.to_document()],
            "warnings": warnings,
        }

    def fetch_exact_record(
        self,
        entry_type: Literal["structures", "references"],
        request: ExactRecordRequest,
        *,
        complete: bool = False,
    ) -> tuple[ProviderConfig, HttpResponse, dict[str, object]]:
        config = PROVIDERS[request.provider_id]
        endpoint = self._api_endpoints[request.provider_id]
        path = f"/v1/{entry_type}/{quote_path_segment(request.entry_id)}"
        response = self._transport.get(
            endpoint,
            path,
            query=() if complete else self._exact_parameters(request),
            max_bytes=4 * 1024 * 1024,
        )
        document = decode_json_object(response)
        model = StructureResponseOne if entry_type == "structures" else ReferenceResponseOne
        _validate_model(model, document, f"exact {entry_type} response")
        data = _object(document.get("data"), "exact response data")
        if data.get("type") != entry_type or data.get("id") != request.entry_id:
            raise ProviderProtocolError(
                "identity-mismatch", "Provider returned a different exact record identity"
            )
        attributes = _object(data.get("attributes"), "exact record attributes")
        immutable_id = attributes.get("immutable_id")
        if request.expected_immutable_id is not None and (
            immutable_id != request.expected_immutable_id
        ):
            raise ProviderProtocolError(
                "immutable-identity-mismatch",
                "Provider record does not match the expected immutable identity",
            )
        return config, response, document

    def get(
        self,
        entry_type: Literal["structures", "references"],
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        request = ExactRecordRequest.from_payload(payload)
        config, response, document = self.fetch_exact_record(entry_type, request)
        return self._result_bundle(
            config=config,
            entry_type=entry_type,
            request=request,
            response=response,
            document=document,
        )

    def get_structure(self, payload: Mapping[str, object]) -> dict[str, object]:
        return self.get("structures", payload)

    def get_reference(self, payload: Mapping[str, object]) -> dict[str, object]:
        return self.get("references", payload)
