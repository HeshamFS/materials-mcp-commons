"""Reviewed provider discovery and introspection over the bounded transport."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import math
import platform
import re
import threading
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import version as distribution_version
from typing import Any, Literal, cast

from materials_mcp_commons import MAX_DISPATCH_PAYLOAD_BYTES, MAX_DISPATCH_PAYLOAD_NODES
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
from tiktoken import Encoding

from .config import PROVIDERS, REGISTRY_BASE_URL, REGISTRY_LINKS_URL, ProviderConfig
from .contracts import (
    CAPABILITY_IDS,
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
_SEARCH_TOKENIZER_REF = "https://github.com/openai/tiktoken/tree/0.14.0#o200k_base"
_SEARCH_TOKENIZER_VERSION = "0.14.0"
_SEARCH_TOKENIZER_BASE_URL = "https://openaipublic.blob.core.windows.net/encodings"
_SEARCH_TOKENIZER_SHA256 = "446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d"
_SEARCH_TOKEN_LIMIT = 1500
_SEARCH_UTF8_BYTE_LIMIT = 8192
_SEARCH_QUERY_TOKEN_LIMIT = 500
_SEARCH_QUERY_UTF8_BYTE_LIMIT = 3072
_SEARCH_PATTERN = "|".join(
    [
        r"[^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}]*[\p{Ll}\p{Lm}\p{Lo}\p{M}]+(?i:'s|'t|'re|'ve|'m|'ll|'d)?",
        r"[^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}]+[\p{Ll}\p{Lm}\p{Lo}\p{M}]*(?i:'s|'t|'re|'ve|'m|'ll|'d)?",
        r"\p{N}{1,3}",
        r" ?[^\s\p{L}\p{N}]+[\r\n/]*",
        r"\s*[\r\n]+",
        r"\s+(?!\S)",
        r"\s+",
    ]
)
_PROVIDER_WARNING_LIMIT = 8
_HIT_WARNING_LIMIT = 16
_DISPATCH_BYTE_TARGET = 60 * 1024
_DISPATCH_NODE_TARGET = 3_800
_SEARCH_ENCODING_LOCK = threading.Lock()
_search_encoding_cache: Encoding | None = None
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


def _text(
    value: object,
    name: str,
    *,
    minimum: int = 1,
    maximum: int = 4096,
    max_utf8_bytes: int | None = None,
) -> str:
    if (
        type(value) is not str
        or not minimum <= len(value) <= maximum
        or (max_utf8_bytes is not None and len(value.encode("utf-8")) > max_utf8_bytes)
    ):
        raise ProviderProtocolError("provider-shape", f"Provider {name} is invalid")
    return value


def _validate_model(model: object, document: dict[str, object], label: str) -> None:
    try:
        cast(Any, model).model_validate(document)
    except ValidationError as error:
        raise ProviderProtocolError(
            "optimade-model-rejected", f"Provider {label} violates the OPTIMADE model"
        ) from error


def _provider_warning_text(value: object, name: str, *, limit: int, missing: str) -> str:
    if value is None or value == "":
        return missing
    if type(value) is not str:
        raise ProviderProtocolError("provider-shape", f"Provider {name} is invalid")
    text = value
    if len(text) <= limit:
        return text
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"Provider {name} omitted from inline context; sha256={digest}"


def _provider_implementation_document(name: str, version: str) -> dict[str, str]:
    canonical = json.dumps(
        {"name": name, "version": version},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {"implementation_metadata_sha256": hashlib.sha256(canonical).hexdigest()}


def _provider_messages(
    meta: Mapping[str, object], page_index: int
) -> tuple[list[dict[str, object]], int]:
    raw_messages = meta.get("warnings")
    if raw_messages is None:
        return [], 0
    messages = _array(raw_messages, "search warnings")
    projected: list[dict[str, object]] = []
    for raw in messages[: _PROVIDER_WARNING_LIMIT - 1]:
        message = _object(raw, "search warning")
        title = _provider_warning_text(
            message.get("title"), "warning title", limit=128, missing="Provider warning"
        )
        detail = _provider_warning_text(
            message.get("detail"),
            "warning detail",
            limit=256,
            missing="Provider supplied no warning detail.",
        )
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
    return projected, max(0, len(messages) - len(projected))


def _finalize_provider_messages(
    projected: list[dict[str, object]], omitted: int
) -> list[dict[str, object]]:
    if omitted <= 0:
        return projected
    return [
        *projected[: _PROVIDER_WARNING_LIMIT - 1],
        {
            "title": "Provider warnings omitted",
            "detail": (
                f"{omitted} additional provider warning(s) were omitted from inline context; "
                "their complete source pages remain bound by response_sha256."
            ),
        },
    ]


def _bounded_hit_warnings(warnings: list[str]) -> list[str]:
    if len(warnings) <= _HIT_WARNING_LIMIT:
        return warnings
    retained = warnings[: _HIT_WARNING_LIMIT - 1]
    retained.append(
        f"{len(warnings) - len(retained)} additional projection warning(s) were omitted."
    )
    return retained


def _compact_provider_warning_context(provider: dict[str, object]) -> bool:
    warnings = cast(list[dict[str, object]], provider["warnings"])
    if not warnings:
        return False
    observed = cast(int, provider["warning_records_observed"])
    provider["warnings"] = []
    provider["warning_records_omitted"] = observed
    return True


def _compact_failed_provider_context(provider: dict[str, object]) -> bool:
    if provider["outcome"] != "failed":
        return False
    return provider.pop("implementation_metadata_sha256", None) is not None


def _page_evidence_sha256(response_hashes: Sequence[str], retrieval_times: Sequence[str]) -> str:
    if len(response_hashes) != len(retrieval_times):
        raise ProviderProtocolError(
            "context-measurement", "Provider page evidence arrays are not aligned"
        )
    evidence = [
        {"response_sha256": digest, "retrieved_at": retrieved_at}
        for digest, retrieved_at in zip(response_hashes, retrieval_times, strict=True)
    ]
    encoded = json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _compact_provider_page_evidence(provider: dict[str, object]) -> bool:
    response_hashes = cast(list[str], provider["response_sha256"])
    retrieval_times = cast(list[str], provider["retrieved_at"])
    if not response_hashes:
        return False
    provider["page_evidence_commitment"] = {
        "count": len(response_hashes),
        "sha256": _page_evidence_sha256(response_hashes, retrieval_times),
    }
    provider["response_sha256"] = []
    provider["retrieved_at"] = []
    return True


def _search_encoding(transport: BoundedHttpsTransport) -> Encoding:
    global _search_encoding_cache
    if _search_encoding_cache is not None:
        return _search_encoding_cache
    installed_version = distribution_version("tiktoken")
    if installed_version != _SEARCH_TOKENIZER_VERSION:
        raise ProviderProtocolError(
            "context-tokenizer-mismatch",
            "Installed tiktoken does not match the declared context tokenizer version",
        )
    with _SEARCH_ENCODING_LOCK:
        if _search_encoding_cache is not None:
            return _search_encoding_cache
        endpoint = TrustedEndpoint.from_url(_SEARCH_TOKENIZER_BASE_URL)
        response = transport.get(
            endpoint,
            "/o200k_base.tiktoken",
            accepted_content_types=frozenset({"application/octet-stream", "text/plain"}),
            max_bytes=4 * 1024 * 1024,
        )
        if response.sha256 != _SEARCH_TOKENIZER_SHA256:
            raise ProviderProtocolError(
                "context-tokenizer-integrity",
                "Context tokenizer data failed its exact SHA-256 check",
            )
        try:
            ranks = {
                base64.b64decode(token): int(rank)
                for line in response.body.splitlines()
                for token, rank in [line.split()]
            }
        except (ValueError, TypeError) as error:
            raise ProviderProtocolError(
                "context-tokenizer-integrity",
                "Context tokenizer data has invalid rank syntax",
            ) from error
        _search_encoding_cache = Encoding(
            name="o200k_base",
            pat_str=_SEARCH_PATTERN,
            mergeable_ranks=ranks,
            special_tokens={"<|endoftext|>": 199999, "<|endofprompt|>": 200018},
        )
        return _search_encoding_cache


def _encoding_token_count(encoding: Encoding, text: str) -> int:
    """Count arbitrary JSON text without treating tokenizer sentinels as control input."""

    return len(encoding.encode(text, disallowed_special=()))


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


def _json_node_count(value: object) -> int:
    if type(value) is dict:
        return 1 + sum(_json_node_count(item) for item in cast(dict[str, object], value).values())
    if type(value) is list:
        return 1 + sum(_json_node_count(item) for item in cast(list[object], value))
    return 1


def _dispatch_metrics(document: Mapping[str, object]) -> tuple[int, int]:
    encoded = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return len(encoded), _json_node_count(document)


def _within_dispatch_target(document: Mapping[str, object]) -> bool:
    encoded_bytes, nodes = _dispatch_metrics(document)
    return encoded_bytes <= _DISPATCH_BYTE_TARGET and nodes <= _DISPATCH_NODE_TARGET


def _assert_within_engine_dispatch(document: Mapping[str, object], label: str) -> None:
    encoded_bytes, nodes = _dispatch_metrics(document)
    if encoded_bytes > MAX_DISPATCH_PAYLOAD_BYTES or nodes > MAX_DISPATCH_PAYLOAD_NODES:
        raise ProviderProtocolError(
            "dispatch-budget-exceeded",
            f"Bounded {label} result cannot fit the engine dispatch envelope",
        )


def _replace_prefixed_warning(warnings: list[str], prefix: str, message: str) -> None:
    warnings[:] = [warning for warning in warnings if not warning.startswith(prefix)]
    warnings.append(message)


def _bounded_provider_list_result(document: dict[str, object]) -> dict[str, object]:
    providers = cast(list[dict[str, object]], document["providers"])
    registry = cast(dict[str, object], document["registry"])
    warnings = cast(list[str], document["warnings"])
    omitted = 0
    while not _within_dispatch_target(document):
        if not providers:
            raise ProviderProtocolError(
                "dispatch-budget-exceeded",
                "Provider-list metadata cannot fit the engine dispatch envelope",
            )
        providers.pop()
        omitted += 1
        registry["data_returned"] = len(providers)
        registry["more_data_available"] = True
        _replace_prefixed_warning(
            warnings,
            "Provider-list dispatch bound omitted ",
            (
                f"Provider-list dispatch bound omitted {omitted} whole registry record(s); "
                "increase registry_entry_offset by data_returned to retrieve the next window."
            ),
        )
    _assert_within_engine_dispatch(document, "provider-list")
    return document


def _bounded_provider_inspection_result(document: dict[str, object]) -> dict[str, object]:
    entry_types = cast(list[dict[str, object]], document["entry_types"])
    omitted_by_type = {cast(str, item["entry_type"]): 0 for item in entry_types}
    while not _within_dispatch_target(document):
        candidates = [item for item in entry_types if cast(list[object], item["properties"])]
        if not candidates:
            raise ProviderProtocolError(
                "dispatch-budget-exceeded",
                "Provider-inspection metadata cannot fit the engine dispatch envelope",
            )
        selected = max(candidates, key=lambda item: len(cast(list[object], item["properties"])))
        cast(list[object], selected["properties"]).pop()
        entry_type = cast(str, selected["entry_type"])
        omitted_by_type[entry_type] += 1
        selected["returned_property_count"] = len(cast(list[object], selected["properties"]))
        selected["omitted_property_count"] = cast(int, selected["omitted_property_count"]) + 1
        _replace_prefixed_warning(
            cast(list[str], selected["warnings"]),
            "Engine dispatch bound omitted ",
            (
                f"Engine dispatch bound omitted {omitted_by_type[entry_type]} additional whole "
                "property definition(s); lower property_limit to retrieve a bounded prefix."
            ),
        )
    _assert_within_engine_dispatch(document, "provider-inspection")
    return document


def _bounded_result_bundle(document: dict[str, object]) -> dict[str, object]:
    properties = cast(list[dict[str, object]], document["properties"])
    provenance = cast(dict[str, object], document["provenance"])
    sources = cast(list[dict[str, object]], provenance["sources"])
    transformations = cast(list[dict[str, object]], sources[0]["transformations"])
    warnings = cast(list[str], document["warnings"])
    omitted = 0
    warnings_compacted = False
    while not _within_dispatch_target(document):
        if not warnings_compacted and warnings:
            warnings_compacted = True
            bounded_warnings = [
                warning
                if len(warning.encode("utf-8")) <= 512
                else (
                    "Projection warning omitted from inline context; sha256="
                    f"{hashlib.sha256(warning.encode('utf-8')).hexdigest()}"
                )
                for warning in warnings
            ]
            protected = [
                warning
                for warning in bounded_warnings
                if warning.startswith("Applicable provider terms ")
                or warning.startswith("The provider rights review ")
            ]
            retained = list(dict.fromkeys([*bounded_warnings[:2], *protected]))
            compacted_count = len(bounded_warnings) - len(retained)
            compacted = [*retained]
            if compacted_count:
                compacted.append(
                    f"{compacted_count} additional projection warning(s) were compacted to keep "
                    "the result inside the engine dispatch envelope."
                )
            if compacted != warnings:
                warnings[:] = compacted
                continue
        if properties:
            property_index = len(properties) - 1
            properties.pop()
            target = f"/properties/{property_index}/value"
            transformations[:] = [
                item for item in transformations if item.get("target_pointer") != target
            ]
            omitted += 1
            document["status"] = "partial"
            _replace_prefixed_warning(
                warnings,
                "Engine dispatch bound omitted ",
                (
                    f"Engine dispatch bound omitted {omitted} whole inline scientific "
                    "property record(s); the checksummed source artifact retains the values."
                ),
            )
            continue
        raise ProviderProtocolError(
            "dispatch-budget-exceeded",
            "Exact-record metadata cannot fit the engine dispatch envelope",
        )
    _assert_within_engine_dispatch(document, "exact-record")
    return document


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
        required_keys = {
            "providers",
            "filter",
            "response_fields",
            "sort",
            "include",
            "page_limit",
            "max_pages_per_provider",
            "max_results",
        }
        if not required_keys.issubset(payload) or set(payload) - (required_keys | {"continuation"}):
            raise ProviderProtocolError(
                "input-shape", "Search input keys do not match the exact contract"
            )
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
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
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
        required_keys = {"provider_id", "database_id", "entry_id", "response_fields", "include"}
        if not required_keys.issubset(payload) or set(payload) - (
            required_keys | {"expected_immutable_id"}
        ):
            raise ProviderProtocolError(
                "input-shape", "Exact-record input keys do not match the exact contract"
            )
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
    starting_offset: int
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


def _search_wire_text(document: Mapping[str, object]) -> str:
    try:
        return json.dumps(
            document,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as error:
        raise ProviderProtocolError(
            "context-measurement", "Search projection is not strict JSON"
        ) from error


def _measure_search_context(
    document: dict[str, object], token_counter: Callable[[str], int]
) -> tuple[int, int]:
    context = cast(dict[str, object], document["context"])
    previous: tuple[int, int] | None = None
    for _ in range(8):
        text = _search_wire_text(document)
        current = (token_counter(text), len(text.encode("utf-8")))
        context["observed_tokens"] = current[0]
        context["observed_utf8_bytes"] = current[1]
        if current == previous:
            return current
        previous = current
    raise ProviderProtocolError(
        "context-measurement", "Search projection measurement did not stabilize"
    )


def _assert_search_query_context(
    request: _SearchRequest, token_counter: Callable[[str], int]
) -> None:
    encoded = json.dumps(
        request.query_document(), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    if (
        token_counter(encoded) > _SEARCH_QUERY_TOKEN_LIMIT
        or len(encoded.encode("utf-8")) > _SEARCH_QUERY_UTF8_BYTE_LIMIT
    ):
        raise ProviderProtocolError(
            "input-context-budget",
            "Search query metadata cannot fit the bounded result context",
        )


def _deferred_search_hit(
    hit: Mapping[str, object], entry_type: Literal["structures", "references"]
) -> dict[str, object]:
    identity = cast(dict[str, object], hit["identity"])
    exact_input: dict[str, object] = {
        "provider_id": identity["provider_id"],
        "database_id": identity["database_id"],
        "entry_id": identity["entry_id"],
        "response_fields": ["id"],
        "include": [],
    }
    immutable_id = identity.get("immutable_id")
    if immutable_id is not None:
        exact_input["expected_immutable_id"] = immutable_id
    capability_name = "structures_get" if entry_type == "structures" else "references_get"
    return {
        "composite_ref": identity["composite_ref"],
        "reason": "record-exceeds-remaining-inline-context",
        "exact_capability_id": CAPABILITY_IDS[capability_name],
        "exact_input": exact_input,
    }


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
        registry_entry_offset = 0
        if payload is not None:
            required = {"include_registry_only", "registry_entry_limit"}
            if not required.issubset(payload) or set(payload) - (
                required | {"registry_entry_offset"}
            ):
                raise ProviderProtocolError(
                    "input-shape", "Provider list input fields do not match the contract"
                )
            include_value = payload.get("include_registry_only")
            limit_value = payload.get("registry_entry_limit")
            offset_value = payload.get("registry_entry_offset", 0)
            if type(include_value) is not bool:
                raise ProviderProtocolError(
                    "input-shape", "Provider registry-only selection must be boolean"
                )
            if type(limit_value) is not int or not 1 <= limit_value <= 100:
                raise ProviderProtocolError(
                    "input-shape", "Provider registry entry limit is invalid"
                )
            if type(offset_value) is not int or not 0 <= offset_value <= 2_147_483_647:
                raise ProviderProtocolError(
                    "input-shape", "Provider registry entry offset is invalid"
                )
            include_registry_only = include_value
            registry_entry_limit = limit_value
            registry_entry_offset = offset_value
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
        selected_providers = eligible[
            registry_entry_offset : registry_entry_offset + registry_entry_limit
        ]
        locally_truncated = registry_entry_offset + len(selected_providers) < len(eligible)
        more = upstream_more or locally_truncated
        if upstream_more:
            result_warnings.append(
                "Registry reports additional pages; this bounded call does not follow them."
            )
        if locally_truncated:
            result_warnings.append(
                "Registry entries were explicitly truncated by registry_entry_limit."
            )
        result: dict[str, object] = {
            "contract": f"{SCHEMA_BASE}provider-list-result.schema.json",
            "profile_version": PROFILE_VERSION,
            "retrieved_at": _wire_time(response),
            "registry": {
                "uri": REGISTRY_LINKS_URL,
                "api_version": api_version,
                "response_sha256": response.sha256,
                "requested_offset": registry_entry_offset,
                "data_returned": len(selected_providers),
                "more_data_available": more,
            },
            "providers": selected_providers,
            "warnings": result_warnings,
        }
        return _bounded_provider_list_result(result)

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
        result: dict[str, object] = {
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
        return _bounded_provider_inspection_result(result)

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
        page_index: int,
        resource_index: int,
    ) -> dict[str, object]:
        entry_id = _text(resource.get("id"), "entry ID", maximum=512, max_utf8_bytes=512)
        resource_type = _text(resource.get("type"), "entry type", maximum=128)
        if resource_type != entry_type:
            raise ProviderProtocolError(
                "entry-type-mismatch", "Provider returned the wrong entry resource type"
            )
        attributes_value = resource.get("attributes", {})
        attributes = _object(attributes_value, "entry attributes")
        immutable_value = attributes.get("immutable_id")
        immutable_id = (
            _text(
                immutable_value,
                "immutable ID",
                maximum=512,
                max_utf8_bytes=512,
            )
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
                digest = hashlib.sha256(name.encode("utf-8")).hexdigest()
                warnings.append(
                    f"Relationship with an invalid name was omitted; name_sha256={digest}."
                )
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
            "page_index": page_index,
            "resource_index": resource_index,
            "warnings": _bounded_hit_warnings(warnings),
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
        starting_offset: int,
        offset: int,
        response_hashes: list[str],
        retrieval_times: list[str],
        hits: list[dict[str, object]],
        pages_returned: int,
        data_available: int | None,
        api_version: str | None,
        implementation: tuple[str, str] | None,
        provider_warnings: list[dict[str, object]],
        provider_warnings_observed: int,
        provider_warnings_omitted: int,
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
            "response_sha256": response_hashes,
            "retrieved_at": retrieval_times,
            "rights": config.rights.to_search_document(),
            "citation_ref": config.citation.citation_ref,
            "warning_records_observed": provider_warnings_observed,
            "warning_records_omitted": provider_warnings_omitted,
            "warnings": _finalize_provider_messages(provider_warnings, provider_warnings_omitted),
            "failure": failure,
        }
        if implementation is not None:
            provider.update(_provider_implementation_document(*implementation))
        return _ProviderSearch(
            provider=provider,
            hits=hits,
            starting_offset=starting_offset,
            cursor=cursor,
        )

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
        starting_offset = offset
        hits: list[dict[str, object]] = []
        response_hashes: list[str] = []
        retrieval_times: list[str] = []
        provider_warnings: list[dict[str, object]] = []
        provider_warnings_observed = 0
        provider_warnings_omitted = 0
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
                response_hashes.append(response.sha256)
                retrieval_times.append(_wire_time(response))
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
                            page_index=page_index,
                            resource_index=resource_index,
                        )
                    )
                hits.extend(page_hits)
                offset += len(records)
                if available_value is not None and available_value < offset:
                    raise ProviderProtocolError(
                        "pagination-inconsistent",
                        "Provider data-available count is smaller than returned records",
                    )
                page_messages, page_omitted = _provider_messages(meta, page_index)
                provider_warnings_observed += len(page_messages) + page_omitted
                remaining_message_slots = _PROVIDER_WARNING_LIMIT - 1 - len(provider_warnings)
                retained_messages = page_messages[:remaining_message_slots]
                provider_warnings.extend(retained_messages)
                provider_warnings_omitted += (
                    page_omitted + len(page_messages) - len(retained_messages)
                )
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
                    starting_offset=starting_offset,
                    offset=offset,
                    response_hashes=response_hashes,
                    retrieval_times=retrieval_times,
                    hits=hits,
                    pages_returned=len(response_hashes),
                    data_available=data_available,
                    api_version=api_version,
                    implementation=implementation,
                    provider_warnings=provider_warnings,
                    provider_warnings_observed=provider_warnings_observed,
                    provider_warnings_omitted=provider_warnings_omitted,
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
            "response_sha256": response_hashes,
            "retrieved_at": retrieval_times,
            "rights": config.rights.to_search_document(),
            "citation_ref": config.citation.citation_ref,
            "warning_records_observed": provider_warnings_observed,
            "warning_records_omitted": provider_warnings_omitted,
            "warnings": _finalize_provider_messages(provider_warnings, provider_warnings_omitted),
        }
        if implementation is not None:
            provider.update(_provider_implementation_document(*implementation))
        return _ProviderSearch(
            provider=provider,
            hits=hits,
            starting_offset=starting_offset,
            cursor=cursor,
        )

    def _bounded_search_result(
        self,
        *,
        entry_type: Literal["structures", "references"],
        request: _SearchRequest,
        results: list[_ProviderSearch],
        token_counter: Callable[[str], int],
    ) -> dict[str, object]:
        providers = [result.provider for result in results]
        hits = [hit for result in results for hit in result.hits]
        failed = [
            cast(str, provider["provider_id"])
            for provider in providers
            if provider["outcome"] == "failed"
        ]
        base_warnings: list[str] = []
        document: dict[str, object] = {
            "contract": f"{SCHEMA_BASE}search-result.schema.json",
            "profile_version": PROFILE_VERSION,
            "entry_type": entry_type,
            "status": "partial" if failed else "complete",
            "produced_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "query": {"sha256": request.query_digest(entry_type)},
            "providers": providers,
            "hits": hits,
            "deferred_hits": [],
            "total_returned": len(hits),
            "more_data_available": False,
            "continuation": {},
            "citation_refs": list(
                dict.fromkeys(PROVIDERS[item].citation.citation_ref for item in request.providers)
            ),
            "transformation": "selected-field-projection",
            "context": {
                "tokenizer_ref": _SEARCH_TOKENIZER_REF,
                "token_limit": _SEARCH_TOKEN_LIMIT,
                "observed_tokens": 0,
                "utf8_byte_limit": _SEARCH_UTF8_BYTE_LIMIT,
                "observed_utf8_bytes": 0,
                "omitted_hits": 0,
                "deferred_hits": 0,
            },
            "warnings": base_warnings,
        }
        original_hits = hits.copy()
        fetched_hits = len(original_hits)
        deferred_hits = cast(list[dict[str, object]], document["deferred_hits"])
        excluded_providers: set[str] = set()
        warning_context_compacted = False
        page_evidence_compacted = False
        failed_provider_context_compacted = False

        def refresh() -> None:
            retained_by_provider = {provider_id: 0 for provider_id in request.providers}
            for hit in hits:
                identity = cast(dict[str, object], hit["identity"])
                provider_id = cast(str, identity["provider_id"])
                retained_by_provider[provider_id] += 1
            deferred_by_provider = {provider_id: 0 for provider_id in request.providers}
            for item in deferred_hits:
                exact_input = cast(dict[str, object], item["exact_input"])
                provider_id = cast(str, exact_input["provider_id"])
                deferred_by_provider[provider_id] += 1
            continuation: dict[str, str] = {}
            for index, result in enumerate(results):
                provider_id = request.providers[index]
                retained = retained_by_provider[provider_id]
                deferred = deferred_by_provider[provider_id]
                progressed = retained + deferred
                result.provider["records_returned"] = retained
                cursor = result.cursor
                if progressed < len(result.hits):
                    cursor = _encode_cursor(
                        provider_id,
                        entry_type,
                        result.starting_offset + progressed,
                        request.query_digest(entry_type),
                    )
                result.provider["more_data_available"] = cursor is not None
                if cursor is not None:
                    continuation[provider_id] = cursor
            omitted = fetched_hits - len(hits)
            context = cast(dict[str, object], document["context"])
            context["omitted_hits"] = omitted
            context["deferred_hits"] = len(deferred_hits)
            document["total_returned"] = len(hits)
            document["continuation"] = continuation
            document["more_data_available"] = any(
                cast(bool, provider["more_data_available"]) for provider in providers
            )
            document["warnings"] = [
                *base_warnings,
                *(
                    [f"{omitted - len(deferred_hits)} hit(s) omitted; use continuation."]
                    if omitted > len(deferred_hits)
                    else []
                ),
                *(
                    [f"{len(deferred_hits)} hit(s) deferred; use deferred_hits exact_input."]
                    if deferred_hits
                    else []
                ),
            ]

        removed_hits: list[dict[str, object]] = []
        while True:
            refresh()
            tokens, utf8_bytes = _measure_search_context(document, token_counter)
            if (
                tokens <= _SEARCH_TOKEN_LIMIT
                and utf8_bytes <= _SEARCH_UTF8_BYTE_LIMIT
                and (hits or not removed_hits)
            ):
                return document
            if not warning_context_compacted:
                warning_context_compacted = True
                compacted = [_compact_provider_warning_context(provider) for provider in providers]
                if any(compacted):
                    continue
            if not page_evidence_compacted:
                page_evidence_compacted = True
                compacted = [_compact_provider_page_evidence(provider) for provider in providers]
                if any(compacted):
                    continue
            if not failed_provider_context_compacted:
                failed_provider_context_compacted = True
                compacted = [_compact_failed_provider_context(provider) for provider in providers]
                if any(compacted):
                    continue
            if not hits:
                if tokens > _SEARCH_TOKEN_LIMIT or utf8_bytes > _SEARCH_UTF8_BYTE_LIMIT:
                    raise ProviderProtocolError(
                        "context-budget-exceeded",
                        "Search metadata cannot fit the exact inline context budget",
                    )
                descriptor_trials: list[tuple[_ProviderSearch, dict[str, object], int, int]] = []
                for result in results:
                    provider_id = cast(str, result.provider["provider_id"])
                    if provider_id in excluded_providers or not result.hits:
                        continue
                    descriptor = _deferred_search_hit(result.hits[0], entry_type)
                    deferred_hits.append(descriptor)
                    refresh()
                    descriptor_tokens, descriptor_bytes = _measure_search_context(
                        document, token_counter
                    )
                    deferred_hits.clear()
                    descriptor_trials.append(
                        (result, descriptor, descriptor_tokens, descriptor_bytes)
                    )
                fitting = [
                    trial
                    for trial in descriptor_trials
                    if trial[2] <= _SEARCH_TOKEN_LIMIT and trial[3] <= _SEARCH_UTF8_BYTE_LIMIT
                ]
                failing = [trial for trial in descriptor_trials if trial not in fitting]
                if fitting and not failing:
                    selected = min(
                        fitting,
                        key=lambda trial: (
                            trial[0].starting_offset,
                            cast(str, trial[0].provider["provider_id"]),
                        ),
                    )
                    deferred_hits.append(selected[1])
                    refresh()
                    _measure_search_context(document, token_counter)
                    return document
                if not descriptor_trials:
                    removed_hits.clear()
                    continue
                isolated = max(
                    failing or descriptor_trials,
                    key=lambda trial: (trial[2], trial[3]),
                )
                isolated_result = isolated[0]
                provider = isolated_result.provider
                provider_id = cast(str, provider["provider_id"])
                if provider["outcome"] != "failed":
                    provider["outcome"] = "failed"
                    provider["failure"] = {
                        "code": "record-identity-context",
                        "http_status": 0,
                        "title": "Record identity exceeds context",
                        "detail": (
                            "A provider record identity cannot fit the inline context budget."
                        ),
                        "retryable": False,
                    }
                provider.pop("implementation_metadata_sha256", None)
                excluded_providers.add(provider_id)
                document["status"] = "partial"
                hits[:] = [
                    hit
                    for hit in original_hits
                    if cast(str, cast(dict[str, object], hit["identity"])["provider_id"])
                    not in excluded_providers
                ]
                deferred_hits.clear()
                removed_hits.clear()
                continue
            retained_counts: dict[str, int] = {}
            for hit in hits:
                identity = cast(dict[str, object], hit["identity"])
                provider_id = cast(str, identity["provider_id"])
                retained_counts[provider_id] = retained_counts.get(provider_id, 0) + 1
            largest = max(retained_counts.values())
            candidates = [
                provider_id
                for provider_id, retained in retained_counts.items()
                if retained == largest
            ]
            starting_offsets = {
                request.providers[index]: result.starting_offset
                for index, result in enumerate(results)
            }
            outcomes = {
                cast(str, result.provider["provider_id"]): result.provider["outcome"]
                for result in results
            }
            provider_to_remove = max(
                candidates,
                key=lambda provider_id: (
                    outcomes[provider_id] == "failed",
                    starting_offsets[provider_id],
                    request.providers.index(provider_id),
                ),
            )
            remove_index = next(
                index
                for index in range(len(hits) - 1, -1, -1)
                if cast(str, cast(dict[str, object], hits[index]["identity"])["provider_id"])
                == provider_to_remove
            )
            removed_hits.append(hits.pop(remove_index))

    def search(
        self,
        entry_type: Literal["structures", "references"],
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        request = _SearchRequest.from_payload(payload)
        query_digest = request.query_digest(entry_type)
        for provider_id, token in request.continuation.items():
            _decode_cursor(
                token,
                provider_id=provider_id,
                entry_type=entry_type,
                query_digest=query_digest,
            )
        encoding = _search_encoding(self._transport)

        def token_counter(text: str) -> int:
            return _encoding_token_count(encoding, text)

        _assert_search_query_context(request, token_counter)
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
        return self._bounded_search_result(
            entry_type=entry_type,
            request=request,
            results=results,
            token_counter=token_counter,
        )

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
        result: dict[str, object] = {
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
                    "This integration checks protocol shape and provenance; scientific "
                    "values retain their source-reported meaning."
                ),
                "criteria": [],
                "limitations": [
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
        return _bounded_result_bundle(result)

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
