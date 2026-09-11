from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any, NoReturn, cast

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry
from referencing.exceptions import NoSuchResource
from referencing.jsonschema import DRAFT202012

from .errors import ContractError

SchemaDocument = dict[str, Any]
SchemaRegistry = Registry[Any]

DIALECT = "https://json-schema.org/draft/2020-12/schema"
PROFILE_VERSION_PATTERN = re.compile(r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$")
DEFAULT_JSON_LIMIT_BYTES = 1_048_576
SCHEMA_MAP_KEYWORDS = frozenset({"$defs", "properties", "patternProperties", "dependentSchemas"})
SCHEMA_VALUE_KEYWORDS = frozenset(
    {
        "additionalProperties",
        "contains",
        "else",
        "if",
        "items",
        "not",
        "propertyNames",
        "then",
        "unevaluatedItems",
        "unevaluatedProperties",
    }
)
SCHEMA_ARRAY_KEYWORDS = frozenset({"allOf", "anyOf", "oneOf", "prefixItems"})


def _fail(code: str, message: str) -> NoReturn:
    raise ContractError(code, message)


def _reject_non_finite(token: str) -> NoReturn:
    _fail("non-finite-number", f"Non-finite JSON number is prohibited: {token}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("duplicate-key", f"Duplicate JSON member: {key}")
        result[key] = value
    return result


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json_object(path: Path, *, max_bytes: int = DEFAULT_JSON_LIMIT_BYTES) -> SchemaDocument:
    if max_bytes < 1:
        _fail("invalid-byte-limit", "JSON byte limit must be positive")
    try:
        size = path.stat().st_size
    except OSError as error:
        raise ContractError("unreadable-file", f"Cannot read JSON file: {path.name}") from error
    if size > max_bytes:
        _fail("document-too-large", f"JSON document exceeds {max_bytes} bytes: {path.name}")
    try:
        text = path.read_bytes().decode("utf-8")
        parsed: object = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_float=Decimal,
            parse_constant=_reject_non_finite,
        )
    except UnicodeDecodeError as error:
        raise ContractError(
            "invalid-utf8", f"JSON file is not strict UTF-8: {path.name}"
        ) from error
    except json.JSONDecodeError as error:
        raise ContractError("invalid-json", f"Malformed JSON document: {path.name}") from error
    if not isinstance(parsed, dict):
        _fail("non-object-root", f"JSON root must be an object: {path.name}")
    return cast(SchemaDocument, parsed)


def resolve_contained_file(root: Path, relative_path: str) -> Path:
    if "\\" in relative_path:
        _fail("unsafe-path", "Package paths must use POSIX separators")
    relative = Path(relative_path)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        _fail("unsafe-path", "Package path is absolute, empty, or contains traversal")
    try:
        resolved_root = root.resolve(strict=True)
    except OSError as error:
        raise ContractError("invalid-root", "Package root does not exist") from error
    if not resolved_root.is_dir() or root.is_symlink():
        _fail("invalid-root", "Package root must be a non-symlink directory")

    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            _fail("unsafe-path", "Package path contains a symbolic link")
    try:
        candidate = (root / relative).resolve(strict=True)
        candidate.relative_to(resolved_root)
    except (OSError, ValueError) as error:
        raise ContractError("unsafe-path", "Package path escapes its declared root") from error
    if not candidate.is_file():
        _fail("not-a-file", "Package resource is not a regular file")
    return candidate


def iter_schema_nodes(schema: object) -> Iterator[SchemaDocument]:
    if isinstance(schema, bool):
        return
    if not isinstance(schema, dict):
        _fail("invalid-schema-position", "A schema position must be an object or boolean")
    document = cast(SchemaDocument, schema)
    yield document
    for keyword in SCHEMA_MAP_KEYWORDS:
        child_map = document.get(keyword)
        if child_map is None:
            continue
        if not isinstance(child_map, dict):
            _fail("invalid-schema-position", f"{keyword} must be an object")
        for child in cast(dict[str, object], child_map).values():
            yield from iter_schema_nodes(child)
    for keyword in SCHEMA_VALUE_KEYWORDS:
        child = document.get(keyword)
        if child is not None:
            yield from iter_schema_nodes(child)
    for keyword in SCHEMA_ARRAY_KEYWORDS:
        children = document.get(keyword)
        if children is None:
            continue
        if not isinstance(children, list):
            _fail("invalid-schema-position", f"{keyword} must be an array")
        for child in cast(list[object], children):
            yield from iter_schema_nodes(child)


def iter_references(document: SchemaDocument) -> Iterator[str]:
    for node in iter_schema_nodes(document):
        for keyword in ("$ref", "$dynamicRef"):
            reference = node.get(keyword)
            if reference is None:
                continue
            if not isinstance(reference, str):
                _fail("invalid-reference", f"{keyword} must be a string")
            yield reference


def _deny_retrieval(uri: str) -> NoReturn:
    raise NoSuchResource(ref=uri)


def build_registry(schemas: Mapping[str, SchemaDocument]) -> SchemaRegistry:
    resources = (
        (schema_id, DRAFT202012.create_resource(document))
        for schema_id, document in schemas.items()
    )
    registry: Any = cast(Any, Registry)(retrieve=_deny_retrieval)
    return cast(SchemaRegistry, registry.with_resources(resources).crawl())


def _string(document: Mapping[str, object], key: str, context: str) -> str:
    value = document.get(key)
    if not isinstance(value, str):
        _fail("invalid-contract-shape", f"{context}.{key} must be a string")
    return value


@dataclass(frozen=True)
class ContractRegistry:
    """A validated, exact-version, offline profile registry."""

    profile_version: str
    canonical_base: str
    schema_ids: frozenset[str]
    _schemas: Mapping[str, SchemaDocument]
    _registry: SchemaRegistry

    @classmethod
    def from_directory(cls, profile_root: Path, profile_version: str) -> ContractRegistry:
        if PROFILE_VERSION_PATTERN.fullmatch(profile_version) is None:
            _fail("invalid-profile-version", "Profile version must be an exact stable version")
        root = profile_root.resolve(strict=True)
        if not root.is_dir() or profile_root.is_symlink():
            _fail("invalid-profile-root", "Profile root must be a non-symlink directory")
        base = f"https://schemas.autonomouslab.io/materials-mcp/{profile_version}/"
        schemas: dict[str, SchemaDocument] = {}
        paths: dict[str, Path] = {}
        for path in sorted(root.glob("*.schema.json")):
            if path.is_symlink() or path.resolve(strict=True).parent != root:
                _fail("unsafe-schema-path", f"Unsafe schema path: {path.name}")
            document = load_json_object(path)
            expected_id = f"{base}{path.name}"
            if document.get("$schema") != DIALECT or document.get("$id") != expected_id:
                _fail("schema-identity-mismatch", f"Schema path and identity differ: {path.name}")
            nodes = list(iter_schema_nodes(document))
            if any("$id" in node for node in nodes[1:]):
                _fail("nested-schema-id", f"Nested schema identifiers are prohibited: {path.name}")
            try:
                Draft202012Validator.check_schema(document)
            except Exception as error:
                raise ContractError("invalid-schema", f"Invalid schema: {path.name}") from error
            schemas[expected_id] = document
            paths[path.name] = path
        if not schemas:
            _fail("empty-profile", "Profile root contains no schemas")

        registry = build_registry(schemas)
        for schema_id, document in schemas.items():
            resolver = registry.resolver(base_uri=schema_id)
            for reference in iter_references(document):
                if not reference.startswith(base):
                    _fail("cross-profile-reference", f"Schema reference leaves {profile_version}")
                try:
                    resolver.lookup(reference)
                except Exception as error:
                    raise ContractError(
                        "unresolved-schema-reference", f"Unresolved reference in {schema_id}"
                    ) from error

        index_path = resolve_contained_file(root, "schema-index.json")
        index = load_json_object(index_path)
        if index.get("profile_version") != profile_version or index.get("canonical_base") != base:
            _fail("index-profile-mismatch", "Schema index does not identify the requested profile")
        index_contract = _string(index, "contract", "schema-index")
        cls._validate_instance(index_contract, index, schemas, registry)
        resources_value = index.get("resources")
        if not isinstance(resources_value, list):
            _fail("invalid-index", "Schema index resources must be an array")
        indexed: set[str] = set()
        for item in cast(list[object], resources_value):
            if not isinstance(item, dict):
                _fail("invalid-index", "Schema index resource must be an object")
            resource = cast(dict[str, object], item)
            relative = _string(resource, "path", "schema-index.resource")
            schema_id = _string(resource, "schema_id", "schema-index.resource")
            if relative not in paths or schema_id != f"{base}{relative}":
                _fail("invalid-index", "Schema index contains an unknown resource")
            if resource.get("sha256") != sha256_file(paths[relative]):
                _fail("schema-digest-mismatch", f"Schema digest mismatch: {relative}")
            if resource.get("media_type") != "application/schema+json":
                _fail("invalid-index", f"Schema media type mismatch: {relative}")
            indexed.add(schema_id)
        if indexed != set(schemas):
            _fail("incomplete-index", "Schema index does not cover the exact schema set")

        snapshots = MappingProxyType(copy.deepcopy(schemas))
        snapshot_registry = build_registry(snapshots)
        return cls(profile_version, base, frozenset(snapshots), snapshots, snapshot_registry)

    @staticmethod
    def _validate_instance(
        schema_id: str,
        instance: object,
        schemas: Mapping[str, SchemaDocument],
        registry: SchemaRegistry,
    ) -> None:
        if schema_id not in schemas:
            _fail("unknown-schema", f"Schema is not registered: {schema_id}")
        validator = Draft202012Validator(
            schemas[schema_id], registry=registry, format_checker=FormatChecker()
        )
        errors = sorted(
            cast(Any, validator).iter_errors(instance),
            key=lambda error: (list(error.absolute_path), list(error.absolute_schema_path)),
        )
        if errors:
            first = errors[0]
            location = "/".join(str(part) for part in first.absolute_path) or "<root>"
            _fail("schema-validation", f"Instance failed {schema_id} at {location}")

    def validate(self, schema_id: str, instance: object) -> None:
        self._validate_instance(schema_id, instance, self._schemas, self._registry)

    def combined_registry(
        self, additional: Mapping[str, SchemaDocument]
    ) -> tuple[Mapping[str, SchemaDocument], SchemaRegistry]:
        overlap = self.schema_ids.intersection(additional)
        if overlap:
            _fail("schema-id-collision", "Package schema shadows a profile schema")
        combined = {**self._schemas, **additional}
        return MappingProxyType(combined), build_registry(combined)
