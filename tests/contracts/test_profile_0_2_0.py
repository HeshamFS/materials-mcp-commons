from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema.exceptions import ValidationError

from tests.contracts.support import (
    CORPUS_ROOT,
    SchemaDocument,
    apply_add_mutation,
    build_registry,
    canonical_base_for,
    flatten_errors,
    iter_references,
    load_case_instance,
    load_json,
    load_schemas,
    schema_root_for,
    sha256,
    validate_instance,
    validation_errors,
    validator_for,
)
from tools.run_conformance import compact_budget_failures, context_budget_failures

PROFILE_VERSION = "0.2.0"
PREDECESSOR_VERSION = "0.1.0"
CANONICAL_BASE = canonical_base_for(PROFILE_VERSION)
PREDECESSOR_BASE = canonical_base_for(PREDECESSOR_VERSION)
SCHEMA_ROOT = schema_root_for(PROFILE_VERSION)
PROFILE_CASE_ROOT = CORPUS_ROOT / "profile-0.2.0"
POSITIVE_ROOT = CORPUS_ROOT / "positive-real" / "cod-9013102"
NEGATIVE_ROOT = CORPUS_ROOT / "negative-generated"

EXPECTED_SCHEMA_FILES = {
    "artifact.schema.json",
    "citation.schema.json",
    "common.schema.json",
    "compact-result.schema.json",
    "context-manifest.schema.json",
    "effect.schema.json",
    "entity.schema.json",
    "extension.schema.json",
    "operation-plan.schema.json",
    "plugin-manifest.schema.json",
    "profile-compatibility.schema.json",
    "provenance.schema.json",
    "quality-assessment.schema.json",
    "result-bundle.schema.json",
    "run-record.schema.json",
    "schema-index.schema.json",
    "scientific-property.schema.json",
    "scientific-value.schema.json",
    "structured-error.schema.json",
}


@pytest.fixture(scope="module")
def schemas_0_2_0() -> dict[str, SchemaDocument]:
    return load_schemas(PROFILE_VERSION)


@pytest.fixture(scope="module")
def registry_0_2_0(schemas_0_2_0: dict[str, SchemaDocument]) -> Any:
    return build_registry(schemas_0_2_0)


def _normalize_schema_version(value: object) -> object:
    if isinstance(value, str):
        return value.replace(PROFILE_VERSION, PREDECESSOR_VERSION)
    if isinstance(value, list):
        return [_normalize_schema_version(item) for item in cast(list[object], value)]
    if isinstance(value, dict):
        object_value = cast(dict[str, object], value)
        return {key: _normalize_schema_version(item) for key, item in object_value.items()}
    return value


def test_schema_set_is_exact_meta_valid_and_path_identified(
    schemas_0_2_0: dict[str, SchemaDocument],
) -> None:
    actual_files = {path.name for path in SCHEMA_ROOT.glob("*.schema.json")}
    assert actual_files == EXPECTED_SCHEMA_FILES
    assert set(schemas_0_2_0) == {f"{CANONICAL_BASE}{name}" for name in EXPECTED_SCHEMA_FILES}


def test_every_reference_is_exact_version_local_and_resolvable(
    schemas_0_2_0: dict[str, SchemaDocument], registry_0_2_0: Any
) -> None:
    for schema_id, document in schemas_0_2_0.items():
        resolver = registry_0_2_0.resolver(base_uri=schema_id)
        for reference in iter_references(document):
            assert reference.startswith(CANONICAL_BASE)
            resolver.lookup(reference)


def test_successor_schema_index_is_complete_and_checksum_pinned(
    schemas_0_2_0: dict[str, SchemaDocument], registry_0_2_0: Any
) -> None:
    index = load_json(SCHEMA_ROOT / "schema-index.json")
    schema_id = cast(str, index["contract"])
    validate_instance(validator_for(schema_id, schemas_0_2_0, registry_0_2_0), index)

    resources = cast(list[dict[str, object]], index["resources"])
    assert len(resources) == len(EXPECTED_SCHEMA_FILES)
    assert [resource["path"] for resource in resources] == sorted(EXPECTED_SCHEMA_FILES)
    for resource in resources:
        path = SCHEMA_ROOT / cast(str, resource["path"])
        assert resource["schema_id"] == f"{CANONICAL_BASE}{path.name}"
        assert resource["sha256"] == sha256(path)
        assert resource["media_type"] == "application/schema+json"

    predecessor = cast(dict[str, object], index["predecessor"])
    assert predecessor == {
        "profile_version": "0.1.0",
        "schema_index": f"{PREDECESSOR_BASE}schema-index.json",
        "publication_commit": "0bbece30da4df0aba0867033931c88a0e3a73515",
        "change_level": "minor",
        "resource_compatibility": "additive",
        "instance_validation": "migration-required",
        "compatibility_contract": f"{CANONICAL_BASE}profile-compatibility.schema.json",
    }


def test_compatibility_declaration_partitions_the_successor_resources(
    schemas_0_2_0: dict[str, SchemaDocument], registry_0_2_0: Any
) -> None:
    declaration = load_json(PROFILE_CASE_ROOT / "profile-compatibility.json")
    validate_instance(
        validator_for(cast(str, declaration["contract"]), schemas_0_2_0, registry_0_2_0),
        declaration,
    )

    carried = set(cast(list[str], declaration["carried_resources"]))
    changed = set(cast(list[str], declaration["changed_resources"]))
    added = set(cast(list[str], declaration["added_resources"]))
    assert carried | changed | added == EXPECTED_SCHEMA_FILES
    assert not (carried & changed or carried & added or changed & added)

    for resource_name in sorted(carried):
        predecessor = load_json(schema_root_for(PREDECESSOR_VERSION) / resource_name)
        successor = load_json(SCHEMA_ROOT / resource_name)
        assert _normalize_schema_version(successor) == predecessor


def test_registered_real_result_migrates_without_scientific_content_change(
    schemas_0_2_0: dict[str, SchemaDocument], registry_0_2_0: Any
) -> None:
    predecessor = load_json(POSITIVE_ROOT / "result-bundle.json")
    expected_successor = load_json(POSITIVE_ROOT / "result-bundle-0.2.0.json")
    migrated = copy.deepcopy(predecessor)
    migrated["contract"] = f"{CANONICAL_BASE}result-bundle.schema.json"
    migrated["profile_version"] = PROFILE_VERSION

    assert migrated == expected_successor
    validate_instance(
        validator_for(cast(str, expected_successor["contract"]), schemas_0_2_0, registry_0_2_0),
        expected_successor,
    )
    with pytest.raises(ValidationError):
        validate_instance(
            validator_for(
                f"{CANONICAL_BASE}result-bundle.schema.json",
                schemas_0_2_0,
                registry_0_2_0,
            ),
            predecessor,
        )


def test_successor_real_corpus_registration_pins_derived_instances() -> None:
    registration = load_json(POSITIVE_ROOT / "registration-0.2.0.json")
    assert registration["corpus_role"] == "positive-real"
    assert registration["profile_version"] == PROFILE_VERSION
    migration = cast(dict[str, object], registration["migration"])
    assert migration == {
        "from_profile": PREDECESSOR_VERSION,
        "to_profile": PROFILE_VERSION,
        "strategy": "exact-identifier-rewrite",
        "scientific_content_changed": False,
    }

    instances = cast(list[dict[str, object]], registration["instances"])
    for instance in instances:
        path = POSITIVE_ROOT / cast(str, instance["path"])
        assert instance["size_bytes"] == path.stat().st_size
        assert instance["sha256"] == sha256(path)
        assert load_json(path)["contract"] == instance["schema_id"]


def test_context_manifest_respects_cross_field_budget_invariants(
    schemas_0_2_0: dict[str, SchemaDocument], registry_0_2_0: Any
) -> None:
    manifest = load_json(PROFILE_CASE_ROOT / "context-manifest.json")
    validate_instance(
        validator_for(cast(str, manifest["contract"]), schemas_0_2_0, registry_0_2_0),
        manifest,
    )
    assert context_budget_failures(manifest) == []


def test_compact_result_is_a_bounded_loss_declaring_source_projection(
    schemas_0_2_0: dict[str, SchemaDocument], registry_0_2_0: Any
) -> None:
    rich = load_json(POSITIVE_ROOT / "result-bundle-0.2.0.json")
    compact_path = POSITIVE_ROOT / "compact-result-0.2.0.json"
    compact = load_json(compact_path)
    context_manifest = load_json(PROFILE_CASE_ROOT / "context-manifest.json")
    validate_instance(
        validator_for(cast(str, compact["contract"]), schemas_0_2_0, registry_0_2_0),
        compact,
    )

    assert compact["source_result_ref"] == rich["result_ref"]
    assert compact["produced_at"] == rich["produced_at"]
    assert compact["status"] == rich["status"]

    rich_entities = cast(list[dict[str, Any]], rich["entities"])
    assert cast(list[str], compact["entity_refs"]) == [
        cast(str, entity["entity_ref"]) for entity in rich_entities
    ]

    for collection_name in ("properties", "conditions"):
        rich_items = cast(list[dict[str, Any]], rich[collection_name])
        compact_items = cast(list[dict[str, Any]], compact[collection_name])
        assert [item["property_ref"] for item in compact_items] == [
            item["property_ref"] for item in rich_items[: len(compact_items)]
        ]
        for projected, source in zip(compact_items, rich_items, strict=False):
            assert projected["label"] == source["label"]
            assert projected["subject_ref"] == source["subject_ref"]
            assert projected["value"] == source["value"]
            assert projected["condition_refs"] == source["condition_refs"]
            assert projected["evidence_refs"] == source["evidence_refs"]
            assert (
                projected["uncertainty_status"]
                == cast(dict[str, Any], source["uncertainty"])["status"]
            )

    rich_artifacts = cast(list[dict[str, Any]], rich["artifacts"])
    assert cast(list[str], compact["artifact_refs"]) == [
        cast(str, artifact["artifact_ref"]) for artifact in rich_artifacts
    ]
    rich_citations = cast(list[dict[str, Any]], rich["citations"])
    assert cast(list[str], compact["citation_refs"]) == [
        cast(str, citation["citation_ref"]) for citation in rich_citations
    ]
    assert compact["provenance_ref"] == cast(dict[str, Any], rich["provenance"])["provenance_ref"]

    rich_quality = cast(dict[str, Any], rich["quality"])
    compact_quality = cast(dict[str, Any], compact["quality"])
    assert compact_quality["status"] == rich_quality["status"]
    assert compact_quality["reason"] == rich_quality["reason"]
    assert compact_quality["limitations"] == rich_quality["limitations"][:2]
    assert compact_quality["omitted_limitations"] == len(rich_quality["limitations"]) - 2

    omitted = cast(dict[str, Any], compact["omitted"])
    assert omitted == {
        "entities": len(rich_entities) - len(cast(list[object], compact["entity_refs"])),
        "properties": len(cast(list[object], rich["properties"]))
        - len(cast(list[object], compact["properties"])),
        "conditions": len(cast(list[object], rich["conditions"]))
        - len(cast(list[object], compact["conditions"])),
        "artifacts": len(rich_artifacts) - len(cast(list[object], compact["artifact_refs"])),
        "citations": len(rich_citations) - len(cast(list[object], compact["citation_refs"])),
        "warnings": len(cast(list[object], rich["warnings"]))
        - len(cast(list[object], compact["warnings"])),
        "truncated": True,
    }

    projection = cast(dict[str, Any], compact["projection"])
    budget = cast(dict[str, Any], projection["budget"])
    inline_budget = cast(
        dict[str, Any], cast(dict[str, Any], context_manifest["budgets"])["inline_result"]
    )
    assert budget["policy_ref"] == context_manifest["manifest_ref"]
    assert budget["limit"] == inline_budget["max_utf8_bytes"]
    assert budget["observed"] == compact_path.stat().st_size
    assert compact_budget_failures(compact) == []


@pytest.mark.parametrize(
    "case_path",
    sorted(NEGATIVE_ROOT.glob("NG-0009-*.json")) + sorted(NEGATIVE_ROOT.glob("NG-0010-*.json")),
)
def test_generated_successor_schema_boundary_case_is_rejected(
    case_path: Path,
    schemas_0_2_0: dict[str, SchemaDocument],
    registry_0_2_0: Any,
) -> None:
    case = load_json(case_path)
    instance = load_case_instance(case)
    expected = cast(dict[str, object], case["expected"])
    errors = validation_errors(
        validator_for(cast(str, case["schema_id"]), schemas_0_2_0, registry_0_2_0), instance
    )
    assert errors, f"{case_path.name} unexpectedly validated"
    matching = [
        error
        for error in flatten_errors(errors)
        if error.validator == expected["validator"]
        and list(error.absolute_path) == expected["instance_path"]
        and list(error.absolute_schema_path) == expected["schema_path"]
    ]
    assert matching


@pytest.mark.parametrize(
    ("case_name", "checker"),
    [
        ("NG-0011-compact-observed-over-limit.json", compact_budget_failures),
        ("NG-0012-context-target-over-maximum.json", context_budget_failures),
        ("NG-0013-context-fraction-order.json", context_budget_failures),
    ],
)
def test_generated_cross_field_budget_case_fails_closed(
    case_name: str,
    checker: Any,
    schemas_0_2_0: dict[str, SchemaDocument],
    registry_0_2_0: Any,
) -> None:
    case = load_json(NEGATIVE_ROOT / case_name)
    instance = load_case_instance(case)
    validate_instance(
        validator_for(cast(str, case["schema_id"]), schemas_0_2_0, registry_0_2_0), instance
    )
    expected = cast(dict[str, object], case["expected"])
    assert checker(instance) == [expected["code"]]


def test_mutating_successor_case_does_not_change_registered_real_records() -> None:
    original = load_json(POSITIVE_ROOT / "compact-result-0.2.0.json")
    before_mutation = copy.deepcopy(original)
    mutated = apply_add_mutation(original, "/projection/budget/observed", 8193)
    assert original == before_mutation
    assert (
        cast(dict[str, Any], cast(dict[str, Any], mutated["projection"])["budget"])["observed"]
        == 8193
    )
