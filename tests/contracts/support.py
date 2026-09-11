from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, NoReturn, cast

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry
from referencing.exceptions import NoSuchResource
from referencing.jsonschema import DRAFT202012

PUBLIC_ROOT = Path(__file__).parents[2]
PROFILE_VERSION = "0.1.0"
PROFILE_VERSION_PATTERN = re.compile(r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$")
SCHEMA_ROOT = PUBLIC_ROOT / "schemas" / PROFILE_VERSION
CORPUS_ROOT = PUBLIC_ROOT / "tests" / "contracts"
CANONICAL_BASE = f"https://schemas.autonomouslab.io/materials-mcp/{PROFILE_VERSION}/"
DIALECT = "https://json-schema.org/draft/2020-12/schema"

SchemaDocument = dict[str, Any]
JsonPath = tuple[str | int, ...]
SchemaRegistry = Registry[Any]

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
KNOWN_SCHEMA_KEYWORDS = frozenset(
    {
        "$anchor",
        "$comment",
        "$defs",
        "$dynamicAnchor",
        "$dynamicRef",
        "$id",
        "$ref",
        "$schema",
        "$vocabulary",
        "additionalProperties",
        "allOf",
        "anyOf",
        "const",
        "contains",
        "contentEncoding",
        "contentMediaType",
        "contentSchema",
        "default",
        "dependentRequired",
        "dependentSchemas",
        "deprecated",
        "description",
        "else",
        "enum",
        "examples",
        "exclusiveMaximum",
        "exclusiveMinimum",
        "format",
        "if",
        "items",
        "maxContains",
        "maximum",
        "maxItems",
        "maxLength",
        "maxProperties",
        "minContains",
        "minimum",
        "minItems",
        "minLength",
        "minProperties",
        "multipleOf",
        "not",
        "oneOf",
        "pattern",
        "patternProperties",
        "prefixItems",
        "properties",
        "propertyNames",
        "readOnly",
        "required",
        "then",
        "title",
        "type",
        "unevaluatedItems",
        "unevaluatedProperties",
        "uniqueItems",
        "writeOnly",
    }
)


class DuplicateKeyError(ValueError):
    """Raised when a JSON object repeats a member name."""


def reject_non_finite(token: str) -> NoReturn:
    raise ValueError(f"Non-finite JSON number is prohibited: {token}")


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"Duplicate JSON member: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> SchemaDocument:
    text = path.read_bytes().decode("utf-8")
    parsed: object = json.loads(
        text,
        object_pairs_hook=unique_object,
        parse_float=Decimal,
        parse_constant=reject_non_finite,
    )
    if not isinstance(parsed, dict):
        raise TypeError(f"Expected an object root in {path.name}")
    return cast(SchemaDocument, parsed)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def iter_schema_nodes(schema: object) -> Iterator[SchemaDocument]:
    if isinstance(schema, bool):
        return
    if not isinstance(schema, dict):
        raise TypeError("A schema position must contain an object or boolean")

    document = cast(SchemaDocument, schema)
    yield document

    for keyword in SCHEMA_MAP_KEYWORDS:
        child_map = document.get(keyword)
        if child_map is None:
            continue
        if not isinstance(child_map, dict):
            raise TypeError(f"{keyword} must contain an object")
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
            raise TypeError(f"{keyword} must contain an array")
        for child in cast(list[object], children):
            yield from iter_schema_nodes(child)


def schema_root_for(profile_version: str) -> Path:
    if PROFILE_VERSION_PATTERN.fullmatch(profile_version) is None:
        raise ValueError(
            f"Profile version must be an exact stable semantic version: {profile_version}"
        )
    return PUBLIC_ROOT / "schemas" / profile_version


def canonical_base_for(profile_version: str) -> str:
    if PROFILE_VERSION_PATTERN.fullmatch(profile_version) is None:
        raise ValueError(
            f"Profile version must be an exact stable semantic version: {profile_version}"
        )
    return f"https://schemas.autonomouslab.io/materials-mcp/{profile_version}/"


def load_schemas(profile_version: str = PROFILE_VERSION) -> dict[str, SchemaDocument]:
    schemas: dict[str, SchemaDocument] = {}
    schema_root = schema_root_for(profile_version)
    canonical_base = canonical_base_for(profile_version)
    root = schema_root.resolve(strict=True)
    for path in sorted(schema_root.glob("*.schema.json")):
        if path.is_symlink() or path.resolve(strict=True).parent != root:
            raise ValueError(f"Unsafe schema path: {path.name}")
        document = load_json(path)
        schema_id = document.get("$id")
        expected_id = f"{canonical_base}{path.name}"
        if document.get("$schema") != DIALECT:
            raise ValueError(f"Wrong schema dialect: {path.name}")
        if schema_id != expected_id:
            raise ValueError(f"Path and schema identifier differ: {path.name}")
        if not isinstance(schema_id, str):
            raise TypeError(f"Schema identifier is not a string: {path.name}")
        if schema_id in schemas:
            raise ValueError(f"Duplicate schema identifier: {schema_id}")

        nodes = list(iter_schema_nodes(document))
        if any("$id" in node for node in nodes[1:]):
            raise ValueError(f"Nested schema identifiers are prohibited: {path.name}")
        for node in nodes:
            unknown = set(node).difference(KNOWN_SCHEMA_KEYWORDS)
            if unknown:
                raise ValueError(f"Unknown schema keywords in {path.name}: {sorted(unknown)}")
        Draft202012Validator.check_schema(document)
        schemas[schema_id] = document
    return schemas


def deny_retrieval(uri: str) -> NoReturn:
    raise NoSuchResource(ref=uri)


def build_registry(schemas: dict[str, SchemaDocument]) -> SchemaRegistry:
    resources = (
        (schema_id, DRAFT202012.create_resource(document))
        for schema_id, document in schemas.items()
    )
    registry: Any = cast(Any, Registry)(retrieve=deny_retrieval)
    return cast(SchemaRegistry, registry.with_resources(resources).crawl())


def iter_references(document: SchemaDocument) -> Iterator[str]:
    for node in iter_schema_nodes(document):
        for keyword in ("$ref", "$dynamicRef"):
            reference = node.get(keyword)
            if reference is None:
                continue
            if not isinstance(reference, str):
                raise TypeError(f"{keyword} must be a string")
            yield reference


def validator_for(
    schema_id: str,
    schemas: dict[str, SchemaDocument],
    registry: SchemaRegistry,
) -> Draft202012Validator:
    return Draft202012Validator(schemas[schema_id], registry=registry)


def validate_instance(validator: Draft202012Validator, instance: object) -> None:
    cast(Any, validator).validate(instance)


def validation_errors(validator: Draft202012Validator, instance: object) -> list[ValidationError]:
    return cast(list[ValidationError], list(cast(Any, validator).iter_errors(instance)))


def flatten_errors(errors: list[ValidationError]) -> list[ValidationError]:
    flattened: list[ValidationError] = []

    def visit(error: ValidationError) -> None:
        flattened.append(error)
        for child in error.context:
            visit(child)

    for error in errors:
        visit(error)
    return flattened


@dataclass(frozen=True)
class ExtensionFailure:
    code: str
    instance_path: JsonPath


def validate_extensions(
    instance: object,
    registry: SchemaRegistry,
    core_schema_ids: frozenset[str],
    path: JsonPath = (),
) -> list[ExtensionFailure]:
    failures: list[ExtensionFailure] = []
    if isinstance(instance, dict):
        object_value = cast(dict[str, Any], instance)
        extensions = object_value.get("extensions")
        if isinstance(extensions, dict):
            for schema_id, payload in cast(dict[str, object], extensions).items():
                extension_path = (*path, "extensions", schema_id)
                if schema_id in core_schema_ids:
                    failures.append(ExtensionFailure("core-schema-as-extension", extension_path))
                    continue
                try:
                    resolved = registry.resolver().lookup(schema_id)
                except Exception:  # referencing deliberately wraps retrieval failures
                    failures.append(ExtensionFailure("unregistered-extension", extension_path))
                    continue
                extension_schema = cast(SchemaDocument, resolved.contents)
                extension_validator = Draft202012Validator(extension_schema, registry=registry)
                errors = validation_errors(extension_validator, payload)
                if errors:
                    failures.append(ExtensionFailure("invalid-extension-payload", extension_path))

        for key, value in object_value.items():
            if key != "extensions":
                failures.extend(validate_extensions(value, registry, core_schema_ids, (*path, key)))
    elif isinstance(instance, list):
        for index, value in enumerate(cast(list[object], instance)):
            failures.extend(validate_extensions(value, registry, core_schema_ids, (*path, index)))
    return failures


def resolve_corpus_path(relative_path: str) -> Path:
    if "\\" in relative_path:
        raise ValueError("Corpus paths must use POSIX separators")
    root = CORPUS_ROOT.resolve(strict=True)
    candidate = (CORPUS_ROOT / relative_path).resolve(strict=True)
    candidate.relative_to(root)
    return candidate


def apply_add_mutation(instance: SchemaDocument, pointer: str, value: object) -> SchemaDocument:
    if not pointer.startswith("/"):
        raise ValueError("Only non-root JSON Pointer additions are supported")
    tokens = [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]
    mutated = copy.deepcopy(instance)
    target: object = mutated
    for token in tokens[:-1]:
        if not isinstance(target, dict) or token not in target:
            raise ValueError("Mutation pointer does not resolve")
        target = cast(dict[str, object], target)[token]
    if not isinstance(target, dict):
        raise ValueError("Mutation target is not an object")
    cast(dict[str, object], target)[tokens[-1]] = copy.deepcopy(value)
    return mutated


def load_case_instance(case: SchemaDocument) -> SchemaDocument:
    inline_instance = case.get("instance")
    if inline_instance is not None:
        if not isinstance(inline_instance, dict):
            raise TypeError("Negative case instance must be an object")
        return cast(SchemaDocument, inline_instance)

    base_path = case.get("base_instance")
    mutation = case.get("mutation")
    if not isinstance(base_path, str) or not isinstance(mutation, dict):
        raise TypeError("Negative case must provide an instance or base mutation")
    mutation_object = cast(dict[str, object], mutation)
    if mutation_object.get("operation") != "add":
        raise ValueError("Only generated add mutations are supported")
    pointer = mutation_object.get("path")
    if not isinstance(pointer, str) or "value" not in mutation_object:
        raise TypeError("Mutation path and value are required")
    base = load_json(resolve_corpus_path(base_path))
    return apply_add_mutation(base, pointer, mutation_object["value"])
