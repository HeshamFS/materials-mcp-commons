from __future__ import annotations

import argparse
import ast
import json
import sys
import tomllib
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, NoReturn, cast

from tests.contracts.support import (
    PUBLIC_ROOT,
    DuplicateKeyError,
    SchemaDocument,
    build_registry,
    canonical_base_for,
    flatten_errors,
    iter_references,
    iter_schema_nodes,
    load_case_instance,
    load_json,
    load_schemas,
    schema_root_for,
    sha256,
    validate_extensions,
    validate_instance,
    validation_errors,
    validator_for,
)

SemanticChecker = Callable[[SchemaDocument], list[str]]


class ConformanceFailure(RuntimeError):
    """Raised when the declared suite or a conformance invariant fails."""


def _fail(message: str) -> NoReturn:
    raise ConformanceFailure(message)


def _objects(value: object, field: str) -> list[SchemaDocument]:
    if not isinstance(value, list):
        _fail(f"{field} must be an array")
    result: list[SchemaDocument] = []
    for index, item in enumerate(cast(list[object], value)):
        if not isinstance(item, dict):
            _fail(f"{field}[{index}] must be an object")
        result.append(cast(SchemaDocument, item))
    return result


def _strings(value: object, field: str) -> list[str]:
    if not isinstance(value, list):
        _fail(f"{field} must be an array of strings")
    items = cast(list[object], value)
    if not all(isinstance(item, str) for item in items):
        _fail(f"{field} must be an array of strings")
    return cast(list[str], items)


def _string(document: SchemaDocument, field: str) -> str:
    value = document.get(field)
    if not isinstance(value, str):
        _fail(f"{field} must be a string")
    return value


def _integer(document: SchemaDocument, field: str) -> int:
    value = document.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        _fail(f"{field} must be an integer")
    return value


def resolve_public_path(relative_path: str) -> Path:
    """Resolve one suite path inside the public tree without following an escape."""
    if "\\" in relative_path:
        _fail(f"Public paths must use POSIX separators: {relative_path}")
    path = Path(relative_path)
    if path.is_absolute() or ".." in path.parts:
        _fail(f"Unsafe public path: {relative_path}")
    root = PUBLIC_ROOT.resolve(strict=True)
    candidate = (PUBLIC_ROOT / path).resolve(strict=True)
    try:
        candidate.relative_to(root)
    except ValueError:
        _fail(f"Public path escapes repository: {relative_path}")
    cursor = PUBLIC_ROOT
    for part in path.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            _fail(f"Symlinks are prohibited in conformance inputs: {relative_path}")
    return candidate


def compact_budget_failures(instance: SchemaDocument) -> list[str]:
    projection = cast(dict[str, Any], instance["projection"])
    budget = cast(dict[str, Any], projection["budget"])
    measurement = cast(dict[str, Any], budget["measurement"])
    failures: list[str] = []
    if budget["observed"] > budget["limit"]:
        failures.append("observed-exceeds-limit")
    if budget["unit"] == "tokens" and measurement["method"] != "host-tokenizer":
        failures.append("token-measurement-method-mismatch")
    if budget["unit"] == "utf8-bytes" and measurement["method"] != "utf8-bytes":
        failures.append("byte-measurement-method-mismatch")
    return failures


def context_budget_failures(instance: SchemaDocument) -> list[str]:
    budgets = cast(dict[str, Any], instance["budgets"])
    activation = cast(dict[str, Any], budgets["activation"])
    inline_result = cast(dict[str, Any], budgets["inline_result"])
    total_mcp = cast(dict[str, Any], budgets["total_mcp"])
    lease_policy = cast(dict[str, Any], instance["lease_policy"])
    failures: list[str] = []
    if activation["target_schemas"] > activation["max_schemas"]:
        failures.append("activation-target-exceeds-maximum")
    if inline_result["target_tokens"] > inline_result["max_tokens"]:
        failures.append("inline-target-exceeds-maximum")
    if lease_policy["default_turns"] > lease_policy["max_turns"]:
        failures.append("lease-default-exceeds-maximum")
    if not (
        total_mcp["target_fraction"]
        <= total_mcp["warning_fraction"]
        <= total_mcp["intervention_fraction"]
    ):
        failures.append("context-fractions-out-of-order")
    return failures


SEMANTIC_CHECKERS: dict[str, SemanticChecker] = {
    "compact-result.schema.json": compact_budget_failures,
    "context-manifest.schema.json": context_budget_failures,
}


def _profile_from_schema_id(schema_id: str, versions: Sequence[str]) -> str:
    matches = [version for version in versions if schema_id.startswith(canonical_base_for(version))]
    if len(matches) != 1:
        _fail(f"Schema identifier is outside the declared profiles: {schema_id}")
    return matches[0]


def _validate_profiles(
    declared_profiles: list[SchemaDocument], expected_versions: list[str]
) -> tuple[list[SchemaDocument], dict[str, tuple[dict[str, SchemaDocument], Any]], int]:
    reports: list[SchemaDocument] = []
    registries: dict[str, tuple[dict[str, SchemaDocument], Any]] = {}
    extension_boundaries = 0
    versions = [_string(profile, "profile_version") for profile in declared_profiles]
    if versions != expected_versions or len(set(versions)) != len(versions):
        _fail("Declared profile order must exactly match expected_profile_versions")

    for profile in declared_profiles:
        version = _string(profile, "profile_version")
        expected_index_path = f"schemas/{version}/schema-index.json"
        if _string(profile, "schema_index") != expected_index_path:
            _fail(f"Profile {version} must use {expected_index_path}")
        index_path = resolve_public_path(expected_index_path)
        expected_index_hash = _string(profile, "schema_index_sha256")
        actual_index_hash = sha256(index_path)
        if actual_index_hash != expected_index_hash:
            _fail(f"Profile {version} schema-index digest differs from the suite")

        schemas = load_schemas(version)
        expected_count = _integer(profile, "schema_count")
        if len(schemas) != expected_count:
            _fail(f"Profile {version} schema count differs from the suite")
        registry = build_registry(schemas)
        registries[version] = (schemas, registry)

        index = load_json(index_path)
        index_schema_id = _string(index, "contract")
        validate_instance(validator_for(index_schema_id, schemas, registry), index)
        resources = _objects(index.get("resources"), "resources")
        if len(resources) != len(schemas):
            _fail(f"Profile {version} index does not cover every schema")

        base = canonical_base_for(version)
        indexed_ids: set[str] = set()
        reference_count = 0
        for resource in resources:
            resource_path = _string(resource, "path")
            schema_path = schema_root_for(version) / resource_path
            schema_id = _string(resource, "schema_id")
            if schema_id != f"{base}{resource_path}":
                _fail(f"Profile {version} index contains a path/identifier mismatch")
            if _string(resource, "sha256") != sha256(schema_path):
                _fail(f"Profile {version} resource digest mismatch: {resource_path}")
            if _string(resource, "media_type") != "application/schema+json":
                _fail(f"Profile {version} resource has the wrong media type: {resource_path}")
            indexed_ids.add(schema_id)

        if indexed_ids != set(schemas):
            _fail(f"Profile {version} index identifiers differ from loaded schemas")

        expected_extension_ref = {"$ref": f"{base}extension.schema.json"}
        for schema_id, document in schemas.items():
            resolver = registry.resolver(base_uri=schema_id)
            for reference in iter_references(document):
                reference_count += 1
                if not reference.startswith(base):
                    _fail(f"Profile {version} has a non-local schema reference: {reference}")
                resolver.lookup(reference)
            for node in iter_schema_nodes(document):
                properties = node.get("properties")
                if isinstance(properties, dict) and "extensions" in properties:
                    extension_boundary = cast(dict[str, object], properties)["extensions"]
                    if extension_boundary != expected_extension_ref:
                        _fail(
                            f"Profile {version} has a non-generic extension boundary in {schema_id}"
                        )
                    extension_boundaries += 1

        reports.append(
            {
                "profile_version": version,
                "schema_count": len(schemas),
                "reference_count": reference_count,
                "schema_index_sha256": actual_index_hash,
            }
        )

    return reports, registries, extension_boundaries


def _semantic_checker(schema_id: str) -> SemanticChecker | None:
    schema_name = schema_id.rsplit("/", 1)[-1]
    return SEMANTIC_CHECKERS.get(schema_name)


def _validate_positive_instances(
    declarations: list[SchemaDocument],
    registries: dict[str, tuple[dict[str, SchemaDocument], Any]],
) -> None:
    for declaration in declarations:
        version = _string(declaration, "profile_version")
        if version not in registries:
            _fail(f"Positive instance uses undeclared profile {version}")
        instance = load_json(resolve_public_path(_string(declaration, "path")))
        schema_id = _string(instance, "contract")
        if not schema_id.startswith(canonical_base_for(version)):
            _fail("Positive instance contract does not match its declared profile")
        schemas, registry = registries[version]
        if schema_id not in schemas:
            _fail(f"Positive instance uses an unregistered schema: {schema_id}")
        validate_instance(validator_for(schema_id, schemas, registry), instance)
        extension_failures = validate_extensions(instance, registry, frozenset(schemas))
        if extension_failures:
            _fail(f"Positive instance failed extension validation: {schema_id}")
        checker = _semantic_checker(schema_id)
        if checker is not None and checker(instance):
            _fail(f"Positive instance failed semantic validation: {schema_id}")


def _strict_json_rejection(path: Path, code: str) -> None:
    try:
        load_json(path)
    except DuplicateKeyError:
        actual = "duplicate-key"
    except ValueError:
        actual = "non-finite-number"
    else:
        _fail(f"Strict JSON negative case unexpectedly decoded: {path.name}")
    if actual != code:
        _fail(f"Strict JSON negative case returned {actual}, expected {code}")


def _validate_negative_cases(
    declarations: list[SchemaDocument],
    versions: list[str],
    registries: dict[str, tuple[dict[str, SchemaDocument], Any]],
) -> dict[str, int]:
    counts = {"schema": 0, "extension_registry": 0, "strict_json": 0, "semantic": 0}
    case_ids: set[str] = set()
    for declaration in declarations:
        path = resolve_public_path(_string(declaration, "path"))
        strict_code = declaration.get("strict_json_code")
        if strict_code is not None:
            if not isinstance(strict_code, str):
                _fail("strict_json_code must be a string")
            _strict_json_rejection(path, strict_code)
            counts["strict_json"] += 1
            continue

        case = load_json(path)
        case_id = _string(case, "case_id")
        if case_id in case_ids:
            _fail(f"Duplicate negative case identifier: {case_id}")
        case_ids.add(case_id)
        if case.get("origin") != "generated" or case.get("role") != "negative":
            _fail(f"Negative case has an invalid data boundary: {case_id}")
        if not _string(case, "purpose").startswith("Reject"):
            _fail(f"Negative case purpose is not rejection-only: {case_id}")

        schema_id = _string(case, "schema_id")
        version = _profile_from_schema_id(schema_id, versions)
        schemas, registry = registries[version]
        instance = load_case_instance(case)
        expected_value = case.get("expected")
        if not isinstance(expected_value, dict):
            _fail(f"Negative case has no expected result: {case_id}")
        expected = cast(SchemaDocument, expected_value)

        if "validator" in expected:
            errors = validation_errors(validator_for(schema_id, schemas, registry), instance)
            matches = [
                error
                for error in flatten_errors(errors)
                if error.validator == expected.get("validator")
                and list(error.absolute_path) == expected.get("instance_path")
                and list(error.absolute_schema_path) == expected.get("schema_path")
            ]
            if not matches:
                _fail(f"Schema negative case did not reach its declared boundary: {case_id}")
            counts["schema"] += 1
            continue

        expected_code = _string(expected, "code")
        validate_instance(validator_for(schema_id, schemas, registry), instance)
        if expected.get("phase") == "extension-registry":
            failures = validate_extensions(instance, registry, frozenset(schemas))
            actual = [(failure.code, list(failure.instance_path)) for failure in failures]
            if actual != [(expected_code, expected.get("instance_path"))]:
                _fail(f"Extension negative case did not fail as declared: {case_id}")
            counts["extension_registry"] += 1
            continue

        checker = _semantic_checker(schema_id)
        if checker is None or checker(instance) != [expected_code]:
            _fail(f"Semantic negative case did not fail as declared: {case_id}")
        counts["semantic"] += 1
    return counts


def _import_roots(source_roots: list[str]) -> set[str]:
    imports: set[str] = set()
    for source_root in source_roots:
        root = resolve_public_path(source_root)
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(alias.name.partition(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    imports.add(node.module.partition(".")[0])
    return imports


def _validate_coupling(
    boundary: SchemaDocument,
    versions: list[str],
    extension_boundaries: int,
) -> SchemaDocument:
    source_roots = _strings(boundary.get("source_roots"), "source_roots")
    allowed_imports = set(_strings(boundary.get("allowed_import_roots"), "allowed_import_roots"))
    expected_dependencies = _strings(
        boundary.get("expected_runtime_dependencies"), "expected_runtime_dependencies"
    )
    expected_versions = _strings(
        boundary.get("expected_profile_versions"), "expected_profile_versions"
    )
    if versions != expected_versions:
        _fail("Loaded profiles differ from the coupling boundary")

    with (PUBLIC_ROOT / "pyproject.toml").open("rb") as handle:
        pyproject = tomllib.load(handle)
    project_value: object = pyproject.get("project")
    if not isinstance(project_value, dict):
        _fail("project must be an object")
    project = cast(SchemaDocument, project_value)
    dependencies_value = project.get("dependencies")
    if not isinstance(dependencies_value, list):
        _fail("project.dependencies must be an array of strings")
    dependency_items = cast(list[object], dependencies_value)
    if not all(isinstance(dependency, str) for dependency in dependency_items):
        _fail("project.dependencies must be an array of strings")
    actual_dependencies = cast(list[str], dependency_items)
    if actual_dependencies != expected_dependencies:
        _fail("Engine runtime dependencies differ from the zero-coupling declaration")

    declared_roots = {resolve_public_path(path) for path in source_roots}
    actual_roots = {
        path.resolve(strict=True)
        for path in (PUBLIC_ROOT / "src").iterdir()
        if path.is_dir() and path.name != "__pycache__"
    }
    if actual_roots != declared_roots:
        _fail("Engine source roots differ from the coupling boundary")

    own_import_roots = {path.name for path in declared_roots}
    import_roots = _import_roots(source_roots)
    external_imports = sorted(import_roots - own_import_roots - allowed_imports)
    if external_imports:
        _fail(f"Engine source has undeclared import roots: {external_imports}")
    if extension_boundaries == 0:
        _fail("No generic extension boundary was found")

    return {
        "result": "pass",
        "runtime_dependency_count": len(actual_dependencies),
        "source_root_count": len(actual_roots),
        "external_import_roots": external_imports,
        "external_schema_reference_count": 0,
        "generic_extension_boundaries": extension_boundaries,
    }


def build_report(suite_path: Path | None = None) -> SchemaDocument:
    selected_suite = (suite_path or PUBLIC_ROOT / "conformance" / "m1-suite.json").resolve(
        strict=True
    )
    suite = load_json(selected_suite)
    if suite.get("suite_version") != 1:
        _fail("Unsupported conformance suite version")

    boundary_value = suite.get("coupling_boundary")
    if not isinstance(boundary_value, dict):
        _fail("coupling_boundary must be an object")
    boundary = cast(SchemaDocument, boundary_value)
    versions = _strings(boundary.get("expected_profile_versions"), "expected_profile_versions")
    profile_reports, registries, extension_boundaries = _validate_profiles(
        _objects(suite.get("profiles"), "profiles"), versions
    )
    positive = _objects(suite.get("positive_instances"), "positive_instances")
    negative = _objects(suite.get("negative_cases"), "negative_cases")
    _validate_positive_instances(positive, registries)
    negative_counts = _validate_negative_cases(negative, versions, registries)
    coupling = _validate_coupling(boundary, versions, extension_boundaries)

    return {
        "report_version": 1,
        "result": "pass",
        "suite_sha256": sha256(selected_suite),
        "profiles": profile_reports,
        "corpus": {
            "positive_instances": len(positive),
            "negative_cases": len(negative),
            "negative_rejections": negative_counts,
        },
        "coupling": coupling,
        "checks": [
            "strict-json-decoding",
            "offline-exact-profile-resolution",
            "schema-index-byte-integrity",
            "positive-instance-validation",
            "negative-case-rejection",
            "semantic-budget-invariants",
            "structural-zero-coupling",
        ],
    }


def serialize_report(report: SchemaDocument) -> str:
    return json.dumps(report, indent=2, sort_keys=True) + "\n"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the deterministic M1 contract and structural coupling suite."
    )
    parser.add_argument(
        "--suite",
        type=Path,
        default=PUBLIC_ROOT / "conformance" / "m1-suite.json",
        help="Suite manifest path.",
    )
    parser.add_argument("--output", type=Path, help="Write the report to this path.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = build_report(cast(Path, args.suite))
    except (ConformanceFailure, KeyError, TypeError, ValueError) as error:
        failure = {"report_version": 1, "result": "fail", "error": str(error)}
        sys.stderr.write(serialize_report(failure))
        return 1

    rendered = serialize_report(report)
    output = cast(Path | None, args.output)
    if output is None:
        sys.stdout.write(rendered)
    else:
        output.write_text(rendered, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
