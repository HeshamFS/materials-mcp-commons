from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator, FormatChecker

from .contracts import (
    DIALECT,
    ContractRegistry,
    SchemaDocument,
    iter_references,
    iter_schema_nodes,
    load_json_object,
    resolve_contained_file,
    sha256_file,
)
from .errors import ContractError


@dataclass(frozen=True)
class Effect:
    tier: str
    category: str
    description: str
    plan_required: bool
    approval_required: bool
    strong_confirmation_required: bool


@dataclass(frozen=True)
class Capability:
    capability_id: str
    title: str
    description: str
    effect: Effect
    input_schema: str
    result_schema: str
    error_schema: str
    supports_async: bool


@dataclass(frozen=True)
class SchemaResource:
    schema_id: str
    path: str
    sha256: str
    role: str


@dataclass(frozen=True)
class LoadedManifest:
    plugin_id: str
    plugin_version: str
    profile_version: str
    name: str
    description: str
    publisher_name: str
    license_expression: str
    manifest_sha256: str
    capabilities: tuple[Capability, ...]
    schema_resources: tuple[SchemaResource, ...]


def _string(document: Mapping[str, object], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str):
        raise ContractError("invalid-manifest-shape", f"Manifest field {key} must be a string")
    return value


def _boolean(document: Mapping[str, object], key: str) -> bool:
    value = document.get(key)
    if not isinstance(value, bool):
        raise ContractError("invalid-manifest-shape", f"Manifest field {key} must be a boolean")
    return value


def _objects(value: object, field: str) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise ContractError("invalid-manifest-shape", f"Manifest field {field} must be an array")
    result: list[dict[str, object]] = []
    for item in cast(list[object], value):
        if not isinstance(item, dict):
            raise ContractError(
                "invalid-manifest-shape", f"Manifest field {field} must contain objects"
            )
        result.append(cast(dict[str, object], item))
    return result


class ManifestLoader:
    """Load one declarative package into an immutable validated snapshot."""

    def __init__(self, contracts: ContractRegistry, *, max_manifest_bytes: int = 1_048_576) -> None:
        self._contracts = contracts
        self._max_manifest_bytes = max_manifest_bytes

    def load(self, package_root: Path, manifest_path: str = "manifest.json") -> LoadedManifest:
        manifest_file = resolve_contained_file(package_root, manifest_path)
        manifest = load_json_object(manifest_file, max_bytes=self._max_manifest_bytes)
        manifest_contract = _string(manifest, "contract")
        expected_contract = f"{self._contracts.canonical_base}plugin-manifest.schema.json"
        if manifest_contract != expected_contract:
            raise ContractError(
                "manifest-contract-mismatch", "Manifest does not use the registry profile contract"
            )
        self._contracts.validate(manifest_contract, manifest)
        if manifest.get("profile_version") != self._contracts.profile_version:
            raise ContractError(
                "manifest-profile-mismatch", "Manifest profile version differs from its registry"
            )

        package_schemas: dict[str, SchemaDocument] = {}
        resource_models: list[SchemaResource] = []
        role_by_id: dict[str, str] = {}
        for resource in _objects(manifest.get("schema_resources"), "schema_resources"):
            schema_id = _string(resource, "schema_id")
            relative_path = _string(resource, "path")
            declared_digest = _string(resource, "sha256")
            role = _string(resource, "role")
            path = resolve_contained_file(package_root, relative_path)
            if sha256_file(path) != declared_digest:
                raise ContractError(
                    "package-schema-digest-mismatch",
                    f"Package schema digest differs: {relative_path}",
                )
            schema = load_json_object(path)
            if schema.get("$schema") != DIALECT or schema.get("$id") != schema_id:
                raise ContractError(
                    "package-schema-identity-mismatch",
                    f"Package schema path and declared identity differ: {relative_path}",
                )
            nodes = list(iter_schema_nodes(schema))
            if any("$id" in node for node in nodes[1:]):
                raise ContractError(
                    "nested-schema-id",
                    f"Nested package schema identifiers are prohibited: {relative_path}",
                )
            if schema_id in package_schemas:
                raise ContractError("duplicate-schema-id", "Package repeats a schema identifier")
            try:
                Draft202012Validator.check_schema(schema)
            except Exception as error:
                raise ContractError(
                    "invalid-package-schema", f"Invalid schema: {relative_path}"
                ) from error
            package_schemas[schema_id] = schema
            role_by_id[schema_id] = role
            resource_models.append(SchemaResource(schema_id, relative_path, declared_digest, role))

        combined, registry = self._contracts.combined_registry(package_schemas)
        for schema_id, schema in package_schemas.items():
            resolver = registry.resolver(base_uri=schema_id)
            for reference in iter_references(schema):
                try:
                    resolver.lookup(reference)
                except Exception as error:
                    raise ContractError(
                        "unresolved-package-reference",
                        f"Unresolved package reference in {schema_id}",
                    ) from error

        capabilities: list[Capability] = []
        capability_ids: set[str] = set()
        for item in _objects(manifest.get("capabilities"), "capabilities"):
            capability_id = _string(item, "capability_id")
            if capability_id in capability_ids:
                raise ContractError(
                    "duplicate-capability-id", "Manifest repeats a capability identifier"
                )
            capability_ids.add(capability_id)
            for field, required_role in (
                ("input_schema", "input"),
                ("result_schema", "result"),
                ("error_schema", "error"),
            ):
                schema_id = _string(item, field)
                if schema_id not in combined:
                    raise ContractError(
                        "unknown-capability-schema", f"Capability {field} is not registered"
                    )
                declared_role = role_by_id.get(schema_id)
                if declared_role is not None and declared_role != required_role:
                    raise ContractError(
                        "capability-schema-role-mismatch",
                        f"Capability {field} does not use a {required_role} schema",
                    )
            effect_value = item.get("effect")
            if not isinstance(effect_value, dict):
                raise ContractError("invalid-manifest-shape", "Capability effect must be an object")
            effect = cast(dict[str, object], effect_value)
            capabilities.append(
                Capability(
                    capability_id=capability_id,
                    title=_string(item, "title"),
                    description=_string(item, "description"),
                    effect=Effect(
                        tier=_string(effect, "tier"),
                        category=_string(effect, "category"),
                        description=_string(effect, "description"),
                        plan_required=_boolean(effect, "plan_required"),
                        approval_required=_boolean(effect, "approval_required"),
                        strong_confirmation_required=_boolean(
                            effect, "strong_confirmation_required"
                        ),
                    ),
                    input_schema=_string(item, "input_schema"),
                    result_schema=_string(item, "result_schema"),
                    error_schema=_string(item, "error_schema"),
                    supports_async=_boolean(item, "supports_async"),
                )
            )

        for declaration in _objects(
            manifest.get("extension_declarations"), "extension_declarations"
        ):
            schema_id = _string(declaration, "schema_id")
            if role_by_id.get(schema_id) != "extension":
                raise ContractError(
                    "invalid-extension-declaration",
                    "Extension declaration must name a packaged extension schema",
                )
            applies_to = declaration.get("applies_to")
            if not isinstance(applies_to, list) or not all(
                isinstance(target, str) and target in combined
                for target in cast(list[object], applies_to)
            ):
                raise ContractError(
                    "invalid-extension-target", "Extension declaration has an unknown target"
                )

        extensions = manifest.get("extensions", {})
        if not isinstance(extensions, dict):
            raise ContractError("invalid-manifest-shape", "Manifest extensions must be an object")
        for schema_id, payload in cast(dict[str, object], extensions).items():
            if role_by_id.get(schema_id) != "extension":
                raise ContractError(
                    "unregistered-extension", "Manifest extension is not declared by the package"
                )
            validator = Draft202012Validator(
                package_schemas[schema_id], registry=registry, format_checker=FormatChecker()
            )
            if next(cast(Any, validator).iter_errors(payload), None) is not None:
                raise ContractError(
                    "invalid-extension-payload", "Manifest extension payload failed validation"
                )

        publisher = cast(dict[str, object], manifest["publisher"])
        license_record = cast(dict[str, object], manifest["license"])
        digest = hashlib.sha256(manifest_file.read_bytes()).hexdigest()
        return LoadedManifest(
            plugin_id=_string(manifest, "plugin_id"),
            plugin_version=_string(manifest, "plugin_version"),
            profile_version=self._contracts.profile_version,
            name=_string(manifest, "name"),
            description=_string(manifest, "description"),
            publisher_name=_string(publisher, "name"),
            license_expression=_string(license_record, "expression"),
            manifest_sha256=digest,
            capabilities=tuple(capabilities),
            schema_resources=tuple(resource_models),
        )
