from __future__ import annotations

import hashlib
import html
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from types import MappingProxyType
from typing import NoReturn, cast

from .contracts import (
    ContractRegistry,
    load_json_object,
    resolve_contained_file,
    sha256_file,
)
from .errors import ContractError, LifecycleError, PluginConformanceError
from .lifecycle import LifecycleRegistry
from .manifest import Capability, LoadedManifest, ManifestLoader

SCHEMA_ANNOTATION_KEYWORDS = frozenset(
    {
        "$comment",
        "default",
        "deprecated",
        "description",
        "examples",
        "readOnly",
        "title",
        "writeOnly",
    }
)


def _fail(code: str, message: str) -> NoReturn:
    raise PluginConformanceError(code, message)


def _freeze(value: object) -> object:
    if isinstance(value, dict):
        document = cast(dict[str, object], value)
        return MappingProxyType({key: _freeze(item) for key, item in document.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in cast(list[object], value))
    return value


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {str(key): _plain(item) for key, item in mapping.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in cast(tuple[object, ...], value)]
    return value


def _snapshot(document: Mapping[str, object]) -> Mapping[str, object]:
    try:
        encoded = json.dumps(
            _plain(document),
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        copied = json.loads(encoded)
    except (TypeError, ValueError) as error:
        raise PluginConformanceError(
            "invalid-report-value", "Conformance report is not strict JSON"
        ) from error
    return cast(Mapping[str, object], _freeze(copied))


def serialize_plugin_report(report: Mapping[str, object]) -> str:
    try:
        return (
            json.dumps(
                _plain(report),
                allow_nan=False,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
    except (TypeError, ValueError) as error:
        raise PluginConformanceError(
            "invalid-report-value", "Conformance report is not strict JSON"
        ) from error


@dataclass(frozen=True)
class PluginConformanceReport:
    document: Mapping[str, object]

    def to_document(self) -> dict[str, object]:
        return cast(dict[str, object], _plain(self.document))

    def to_json(self) -> str:
        return serialize_plugin_report(self.document)


@dataclass(frozen=True)
class ProfileCase:
    profile_version: str
    profile_root: Path


@dataclass(frozen=True)
class PackageCase:
    case_id: str
    package_root: Path


@dataclass(frozen=True)
class VersionedConformanceMatrix:
    document: Mapping[str, object]

    def to_document(self) -> dict[str, object]:
        return cast(dict[str, object], _plain(self.document))

    def to_json(self) -> str:
        return serialize_plugin_report(self.document)


@dataclass(frozen=True)
class MigrationAssessment:
    document: Mapping[str, object]

    def to_document(self) -> dict[str, object]:
        return cast(dict[str, object], _plain(self.document))

    @property
    def result(self) -> str:
        return cast(str, self.document["result"])

    def to_json(self) -> str:
        return serialize_plugin_report(self.document)


def _effect_document(capability: Capability) -> dict[str, object]:
    return asdict(capability.effect)


def _capability_document(capability: Capability) -> dict[str, object]:
    return {
        "capability_id": capability.capability_id,
        "title": capability.title,
        "description": capability.description,
        "effect": _effect_document(capability),
        "input_schema": capability.input_schema,
        "result_schema": capability.result_schema,
        "error_schema": capability.error_schema,
        "supports_async": capability.supports_async,
    }


class PluginConformanceRunner:
    """Evaluate declarative package structure without loading executable plugin code."""

    def __init__(self, contracts: ContractRegistry) -> None:
        self._contracts = contracts

    def evaluate(self, package_root: Path) -> PluginConformanceReport:
        try:
            manifest = ManifestLoader(self._contracts).load(package_root)
            lifecycle = LifecycleRegistry()
            first = lifecycle.register(manifest)
            second = lifecycle.register(manifest)
        except (ContractError, LifecycleError, OSError) as error:
            raise PluginConformanceError(
                "package-conformance-failed",
                "Declarative package failed exact-profile conformance",
            ) from error
        if first != second:
            _fail("registration-nondeterministic", "Repeated registration identity changed")
        document: dict[str, object] = {
            "report_version": 1,
            "result": "pass",
            "scope": "exact-profile-declarative-only",
            "profile_version": manifest.profile_version,
            "plugin": {
                "plugin_id": manifest.plugin_id,
                "plugin_version": manifest.plugin_version,
                "name": manifest.name,
                "description": manifest.description,
                "publisher_name": manifest.publisher_name,
                "license_expression": manifest.license_expression,
                "manifest_sha256": manifest.manifest_sha256,
                "registration_ref": first.registration_ref,
            },
            "capabilities": [
                _capability_document(capability) for capability in manifest.capabilities
            ],
            "schema_resources": [asdict(resource) for resource in manifest.schema_resources],
            "checks": [
                "strict-contained-manifest",
                "exact-profile-contract",
                "schema-byte-integrity",
                "offline-reference-resolution",
                "capability-schema-role-binding",
                "registered-extension-validation",
                "deterministic-registration-identity",
            ],
            "limitations": [
                "No plugin implementation code or backend was loaded or executed.",
                (
                    "This report does not establish security, interoperability, "
                    "or scientific validity."
                ),
            ],
        }
        return PluginConformanceReport(_snapshot(document))


def _compatibility_report(
    document: Mapping[str, object],
    registries: Mapping[str, ContractRegistry],
    roots: Mapping[str, Path],
) -> dict[str, object]:
    source_version = document.get("from_profile")
    target_version = document.get("to_profile")
    if not isinstance(source_version, str) or not isinstance(target_version, str):
        _fail("invalid-compatibility", "Compatibility profile versions are missing")
    source_registry = registries.get(source_version)
    target_registry = registries.get(target_version)
    if source_registry is None or target_registry is None:
        _fail("missing-profile", "Compatibility declaration references an absent profile")
    contract = document.get("contract")
    if not isinstance(contract, str):
        _fail("invalid-compatibility", "Compatibility contract is missing")
    try:
        target_registry.validate(contract, document)
    except ContractError as error:
        raise PluginConformanceError(
            "invalid-compatibility", "Compatibility declaration failed its target contract"
        ) from error
    carried_value = document.get("carried_resources")
    changed_value = document.get("changed_resources")
    added_value = document.get("added_resources")
    if not all(isinstance(value, list) for value in (carried_value, changed_value, added_value)):
        _fail("invalid-compatibility", "Compatibility resource partitions must be arrays")
    carried = cast(list[str], carried_value)
    changed = cast(list[str], changed_value)
    added = cast(list[str], added_value)
    try:
        semantic_match = True
        for resource_name in carried:
            source = load_json_object(resolve_contained_file(roots[source_version], resource_name))
            target = load_json_object(resolve_contained_file(roots[target_version], resource_name))
            normalized = _schema_validation_semantics(
                _normalize_profile_contract(
                    target,
                    target_registry.canonical_base,
                    source_registry.canonical_base,
                    target_version,
                    source_version,
                )
            )
            if normalized != _schema_validation_semantics(source):
                semantic_match = False
                break
    except (ContractError, OSError) as error:
        raise PluginConformanceError(
            "invalid-compatibility", "Compatibility resources could not be compared"
        ) from error
    checks = {
        "carried-contract-semantics": semantic_match,
        "profile-identities": document.get("profile_version") == target_version,
        "schema-index-identities": (
            document.get("predecessor_schema_index")
            == f"{source_registry.canonical_base}schema-index.json"
            and document.get("successor_schema_index")
            == f"{target_registry.canonical_base}schema-index.json"
        ),
        "resource-partition": (
            not set(carried).intersection(changed)
            and not set(carried).intersection(added)
            and not set(changed).intersection(added)
            and set(carried).union(changed, added)
            == {
                f"{schema_id.removeprefix(target_registry.canonical_base)}"
                for schema_id in target_registry.schema_ids
            }
        ),
    }
    return {
        "from_profile": source_version,
        "to_profile": target_version,
        "change_level": document.get("change_level"),
        "instance_validation": document.get("instance_validation"),
        "migration_strategy": cast(Mapping[str, object], document["migration"])["strategy"],
        "carried_resource_count": len(carried),
        "changed_resources": changed,
        "added_resources": added,
        "checks": checks,
        "result": "pass" if all(checks.values()) else "fail",
    }


def build_versioned_matrix(
    profiles: Sequence[ProfileCase],
    packages: Sequence[PackageCase],
    compatibility_documents: Sequence[Mapping[str, object]] = (),
) -> VersionedConformanceMatrix:
    if not profiles:
        _fail("missing-profile", "At least one exact profile is required")
    registries: dict[str, ContractRegistry] = {}
    roots: dict[str, Path] = {}
    profile_reports: list[dict[str, object]] = []
    for case in profiles:
        if case.profile_version in registries:
            _fail("duplicate-profile", "Versioned matrix repeats a profile")
        try:
            registry = ContractRegistry.from_directory(case.profile_root, case.profile_version)
            index = resolve_contained_file(case.profile_root, "schema-index.json")
        except (ContractError, OSError) as error:
            raise PluginConformanceError(
                "invalid-profile", "Versioned matrix profile failed validation"
            ) from error
        registries[case.profile_version] = registry
        roots[case.profile_version] = case.profile_root
        profile_reports.append(
            {
                "profile_version": case.profile_version,
                "canonical_base": registry.canonical_base,
                "schema_count": len(registry.schema_ids),
                "schema_index_sha256": sha256_file(index),
            }
        )
    package_reports: list[dict[str, object]] = []
    case_ids: set[str] = set()
    for package in packages:
        if not package.case_id or package.case_id in case_ids:
            _fail("duplicate-package-case", "Package case identifiers must be unique")
        case_ids.add(package.case_id)
        try:
            raw = load_json_object(resolve_contained_file(package.package_root, "manifest.json"))
        except ContractError as error:
            raise PluginConformanceError(
                "package-conformance-failed", "Package manifest could not be selected"
            ) from error
        declared_profile = raw.get("profile_version")
        registry = registries.get(cast(str, declared_profile))
        if registry is None:
            _fail("missing-profile", "Package declares a profile absent from the matrix")
        report = PluginConformanceRunner(registry).evaluate(package.package_root).to_document()
        package_reports.append({"case_id": package.case_id, "report": report})
    compatibility_reports = [
        _compatibility_report(document, registries, roots) for document in compatibility_documents
    ]
    result = "pass"
    if any(item["result"] != "pass" for item in compatibility_reports):
        result = "fail"
    document = {
        "report_version": 1,
        "result": result,
        "scope": "explicit-version-declarative-matrix",
        "profiles": sorted(profile_reports, key=lambda item: cast(str, item["profile_version"])),
        "packages": sorted(package_reports, key=lambda item: cast(str, item["case_id"])),
        "compatibility": compatibility_reports,
        "limitations": [
            (
                "Profiles and packages are local explicit inputs; no negotiation "
                "or retrieval occurred."
            ),
            "Matrix success is structural and does not execute or validate a scientific backend.",
        ],
    }
    return VersionedConformanceMatrix(_snapshot(document))


def _normalize_references(value: object, from_base: str, to_base: str) -> object:
    if isinstance(value, str):
        return f"{to_base}{value[len(from_base) :]}" if value.startswith(from_base) else value
    if isinstance(value, list):
        return [
            _normalize_references(item, from_base, to_base) for item in cast(list[object], value)
        ]
    if isinstance(value, Mapping):
        mapping = cast(Mapping[str, object], value)
        return {
            key: _normalize_references(item, from_base, to_base) for key, item in mapping.items()
        }
    return value


def _normalize_profile_contract(
    value: object,
    from_base: str,
    to_base: str,
    from_version: str,
    to_version: str,
) -> object:
    if isinstance(value, str):
        rewritten = f"{to_base}{value[len(from_base) :]}" if value.startswith(from_base) else value
        return to_version if rewritten == from_version else rewritten
    if isinstance(value, list):
        return [
            _normalize_profile_contract(
                item,
                from_base,
                to_base,
                from_version,
                to_version,
            )
            for item in cast(list[object], value)
        ]
    if isinstance(value, Mapping):
        mapping = cast(Mapping[str, object], value)
        return {
            key: _normalize_profile_contract(
                item,
                from_base,
                to_base,
                from_version,
                to_version,
            )
            for key, item in mapping.items()
        }
    return value


def _schema_validation_semantics(value: object) -> object:
    if isinstance(value, list):
        return [_schema_validation_semantics(item) for item in cast(list[object], value)]
    if isinstance(value, Mapping):
        mapping = cast(Mapping[str, object], value)
        return {
            key: _schema_validation_semantics(item)
            for key, item in mapping.items()
            if key not in SCHEMA_ANNOTATION_KEYWORDS
        }
    return value


def _manifest_semantics(
    document: Mapping[str, object],
    *,
    from_base: str,
    to_base: str,
) -> object:
    normalized = cast(dict[str, object], _normalize_references(document, from_base, to_base))
    for key in ("contract", "profile_version", "plugin_version"):
        normalized.pop(key, None)
    resources = normalized.get("schema_resources")
    if isinstance(resources, list):
        for item in cast(list[object], resources):
            if isinstance(item, dict):
                cast(dict[str, object], item).pop("sha256", None)
    return normalized


def assess_plugin_migration(
    *,
    source_package_root: Path,
    target_package_root: Path,
    source_contracts: ContractRegistry,
    target_contracts: ContractRegistry,
    compatibility_document: Mapping[str, object],
) -> MigrationAssessment:
    contract = compatibility_document.get("contract")
    if not isinstance(contract, str):
        _fail("invalid-compatibility", "Compatibility contract is missing")
    try:
        target_contracts.validate(contract, compatibility_document)
        source_manifest = ManifestLoader(source_contracts).load(source_package_root)
        target_manifest = ManifestLoader(target_contracts).load(target_package_root)
        source_raw = load_json_object(resolve_contained_file(source_package_root, "manifest.json"))
        target_raw = load_json_object(resolve_contained_file(target_package_root, "manifest.json"))
    except ContractError as error:
        raise PluginConformanceError(
            "migration-input-invalid", "Migration inputs must be separately valid"
        ) from error
    if (
        compatibility_document.get("from_profile") != source_contracts.profile_version
        or compatibility_document.get("to_profile") != target_contracts.profile_version
    ):
        _fail("compatibility-profile-mismatch", "Compatibility and package profiles differ")

    source_resources = {item.path: item for item in source_manifest.schema_resources}
    target_resources = {item.path: item for item in target_manifest.schema_resources}
    resource_descriptors_match = {
        path: (resource.schema_id, resource.role) for path, resource in source_resources.items()
    } == {
        path: (
            cast(
                str,
                _normalize_references(
                    resource.schema_id,
                    target_contracts.canonical_base,
                    source_contracts.canonical_base,
                ),
            ),
            resource.role,
        )
        for path, resource in target_resources.items()
    }
    schema_semantics_match = resource_descriptors_match
    if schema_semantics_match:
        for path in source_resources:
            source_schema = load_json_object(resolve_contained_file(source_package_root, path))
            target_schema = load_json_object(resolve_contained_file(target_package_root, path))
            normalized = _schema_validation_semantics(
                _normalize_profile_contract(
                    target_schema,
                    target_contracts.canonical_base,
                    source_contracts.canonical_base,
                    target_contracts.profile_version,
                    source_contracts.profile_version,
                )
            )
            if normalized != _schema_validation_semantics(source_schema):
                schema_semantics_match = False
                break
    checks = {
        "capability-identities": tuple(item.capability_id for item in source_manifest.capabilities)
        == tuple(item.capability_id for item in target_manifest.capabilities),
        "manifest-semantics": _manifest_semantics(
            target_raw,
            from_base=target_contracts.canonical_base,
            to_base=source_contracts.canonical_base,
        )
        == _manifest_semantics(
            source_raw,
            from_base=source_contracts.canonical_base,
            to_base=source_contracts.canonical_base,
        ),
        "plugin-identity": source_manifest.plugin_id == target_manifest.plugin_id,
        "resource-descriptors": resource_descriptors_match,
        "schema-semantics": schema_semantics_match,
    }
    document = {
        "report_version": 1,
        "result": "pass" if all(checks.values()) else "fail",
        "scope": "caller-supplied-declarative-migration",
        "from_profile": source_contracts.profile_version,
        "to_profile": target_contracts.profile_version,
        "plugin_id": source_manifest.plugin_id,
        "source_plugin_version": source_manifest.plugin_version,
        "target_plugin_version": target_manifest.plugin_version,
        "strategy": cast(Mapping[str, object], compatibility_document["migration"])["strategy"],
        "checks": checks,
        "limitations": [
            "The assessment does not mutate or publish either package.",
            "Passing preservation checks do not establish backend or scientific validity.",
        ],
    }
    return MigrationAssessment(_snapshot(document))


def _markdown_text(value: str) -> str:
    flattened = " ".join(value.split())
    escaped = html.escape(flattened, quote=False)
    for character in ("\\", "`", "*", "_", "[", "]"):
        escaped = escaped.replace(character, f"\\{character}")
    return escaped


def _inline_code(value: str) -> str:
    longest = max((len(match.group()) for match in re.finditer(r"`+", value)), default=0)
    fence = "`" * max(1, longest + 1)
    return f"{fence}{value}{fence}"


def render_capability_reference(manifest: LoadedManifest) -> str:
    lines = [
        f"# {_markdown_text(manifest.name)} capability reference",
        "",
        (
            "This generated reference reports exact declarative structure only. "
            "It does not load or execute plugin code and does not establish backend "
            "interoperability, security, or scientific validity."
        ),
        "",
        f"- Plugin ID: {_inline_code(manifest.plugin_id)}",
        f"- Plugin version: {_inline_code(manifest.plugin_version)}",
        f"- Profile version: {_inline_code(manifest.profile_version)}",
        f"- Publisher: {_markdown_text(manifest.publisher_name)}",
        f"- License expression: {_inline_code(manifest.license_expression)}",
        f"- Manifest SHA-256: {_inline_code(manifest.manifest_sha256)}",
    ]
    for capability in manifest.capabilities:
        lines.extend(
            (
                "",
                f"## {_markdown_text(capability.title)}",
                "",
                _markdown_text(capability.description),
                "",
                f"- Capability ID: {_inline_code(capability.capability_id)}",
                f"- Effect tier: {_inline_code(capability.effect.tier)}",
                f"- Effect category: {_inline_code(capability.effect.category)}",
                f"- Plan required: `{'yes' if capability.effect.plan_required else 'no'}`",
                f"- Approval required: `{'yes' if capability.effect.approval_required else 'no'}`",
                "- Strong confirmation required: "
                f"`{'yes' if capability.effect.strong_confirmation_required else 'no'}`",
                f"- Asynchronous: `{'yes' if capability.supports_async else 'no'}`",
                f"- Input schema: {_inline_code(capability.input_schema)}",
                f"- Result schema: {_inline_code(capability.result_schema)}",
                f"- Error schema: {_inline_code(capability.error_schema)}",
            )
        )
    return "\n".join(lines) + "\n"


def capability_reference_sha256(reference: str) -> str:
    return hashlib.sha256(reference.encode()).hexdigest()
