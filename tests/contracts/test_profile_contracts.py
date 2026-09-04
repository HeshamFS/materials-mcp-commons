from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import pytest
from referencing.exceptions import Unresolvable

from tests.contracts.support import (
    CANONICAL_BASE,
    CORPUS_ROOT,
    SCHEMA_ROOT,
    DuplicateKeyError,
    SchemaDocument,
    apply_add_mutation,
    build_registry,
    flatten_errors,
    iter_references,
    load_case_instance,
    load_json,
    load_schemas,
    sha256,
    validate_extensions,
    validate_instance,
    validation_errors,
    validator_for,
)

EXPECTED_SCHEMA_FILES = {
    "artifact.schema.json",
    "citation.schema.json",
    "common.schema.json",
    "effect.schema.json",
    "entity.schema.json",
    "extension.schema.json",
    "operation-plan.schema.json",
    "plugin-manifest.schema.json",
    "provenance.schema.json",
    "quality-assessment.schema.json",
    "result-bundle.schema.json",
    "run-record.schema.json",
    "schema-index.schema.json",
    "scientific-property.schema.json",
    "scientific-value.schema.json",
    "structured-error.schema.json",
}
POSITIVE_ROOT = CORPUS_ROOT / "positive-real" / "cod-9013102"
NEGATIVE_ROOT = CORPUS_ROOT / "negative-generated"


@pytest.fixture(scope="module")
def schemas() -> dict[str, SchemaDocument]:
    return load_schemas()


@pytest.fixture(scope="module")
def registry(schemas: dict[str, SchemaDocument]) -> Any:
    return build_registry(schemas)


def test_schema_set_is_exact_meta_valid_and_path_identified(
    schemas: dict[str, SchemaDocument],
) -> None:
    actual_files = {path.name for path in SCHEMA_ROOT.glob("*.schema.json")}
    assert actual_files == EXPECTED_SCHEMA_FILES
    assert set(schemas) == {f"{CANONICAL_BASE}{name}" for name in EXPECTED_SCHEMA_FILES}


def test_every_reference_is_absolute_version_local_and_resolvable(
    schemas: dict[str, SchemaDocument], registry: Any
) -> None:
    for schema_id, document in schemas.items():
        resolver = registry.resolver(base_uri=schema_id)
        for reference in iter_references(document):
            assert reference.startswith(CANONICAL_BASE)
            resolver.lookup(reference)


@pytest.mark.parametrize(
    "reference",
    [
        "missing.schema.json",
        "file:///generated-negative/missing.schema.json",
        "https://schemas.autonomouslab.io/materials-mcp/9.9.9/missing.schema.json",
        "https://invalid.example/generated-negative/missing.schema.json",
    ],
)
def test_offline_registry_denies_unregistered_references(registry: Any, reference: str) -> None:
    resolver = registry.resolver(base_uri=f"{CANONICAL_BASE}result-bundle.schema.json")
    with pytest.raises(Unresolvable):
        resolver.lookup(reference)


def test_schema_index_is_valid_complete_and_checksum_pinned(
    schemas: dict[str, SchemaDocument], registry: Any
) -> None:
    index = load_json(SCHEMA_ROOT / "schema-index.json")
    schema_id = cast(str, index["contract"])
    validate_instance(validator_for(schema_id, schemas, registry), index)

    resources = cast(list[dict[str, object]], index["resources"])
    assert len(resources) == len(EXPECTED_SCHEMA_FILES)
    assert [resource["path"] for resource in resources] == sorted(EXPECTED_SCHEMA_FILES)
    for resource in resources:
        path = SCHEMA_ROOT / cast(str, resource["path"])
        assert resource["schema_id"] == f"{CANONICAL_BASE}{path.name}"
        assert resource["sha256"] == sha256(path)
        assert resource["media_type"] == "application/schema+json"


def test_positive_registration_integrity_and_rights() -> None:
    registration = load_json(POSITIVE_ROOT / "registration.json")
    source = cast(dict[str, object], registration["source"])
    mirror = cast(dict[str, object], registration["local_source_mirror"])
    instance = cast(dict[str, object], registration["instance"])
    mirror_path = POSITIVE_ROOT / cast(str, mirror["path"])
    instance_path = POSITIVE_ROOT / cast(str, instance["path"])

    assert registration["corpus_role"] == "positive-real"
    assert source["immutable_uri"] == "https://www.crystallography.net/cod/9013102.cif@291877"
    assert source["revision"] == "291877"
    assert source["rights"] == {
        "identifier": "CC0-1.0",
        "uri": "https://creativecommons.org/publicdomain/zero/1.0/",
        "redistribution": "permitted",
        "attribution": (
            "Acknowledge B. N. Dutta and the original structural-data sources as "
            "requested by the Crystallography Open Database."
        ),
    }
    assert mirror["size_bytes"] == mirror_path.stat().st_size
    assert mirror["sha256"] == sha256(mirror_path)
    assert instance["size_bytes"] == instance_path.stat().st_size
    assert instance["sha256"] == sha256(instance_path)

    mirror_bytes = mirror_path.read_bytes()
    assert mirror_bytes.endswith(b"\n")
    assert len(mirror_bytes[:-1]) == source["size_bytes"]
    assert hashlib.sha256(mirror_bytes[:-1]).hexdigest() == source["sha256"]


def test_real_positive_result_validates_and_has_closed_internal_links(
    schemas: dict[str, SchemaDocument], registry: Any
) -> None:
    result = load_json(POSITIVE_ROOT / "result-bundle.json")
    schema_id = cast(str, result["contract"])
    validate_instance(validator_for(schema_id, schemas, registry), result)
    assert validate_extensions(result, registry, frozenset(schemas)) == []

    entities = cast(list[dict[str, object]], result["entities"])
    properties = cast(list[dict[str, object]], result["properties"])
    conditions = cast(list[dict[str, object]], result["conditions"])
    artifacts = cast(list[dict[str, object]], result["artifacts"])
    citations = cast(list[dict[str, object]], result["citations"])
    provenance = cast(dict[str, object], result["provenance"])

    entity_refs = {entity["entity_ref"] for entity in entities}
    condition_refs = {condition["property_ref"] for condition in conditions}
    artifact_refs = {artifact["artifact_ref"] for artifact in artifacts}
    citation_refs = {citation["citation_ref"] for citation in citations}
    assert len(entity_refs) == len(entities)
    assert len(condition_refs) == len(conditions)
    assert len(artifact_refs) == len(artifacts)
    assert len(citation_refs) == len(citations)
    for scientific_property in [*properties, *conditions]:
        assert scientific_property["subject_ref"] in entity_refs
        assert set(cast(list[object], scientific_property["condition_refs"])) <= condition_refs
        assert set(cast(list[object], scientific_property["evidence_refs"])) <= artifact_refs

    sources = cast(list[dict[str, object]], provenance["sources"])
    assert artifacts[0]["uri"] == sources[0]["uri"]
    assert artifacts[0]["size_bytes"] == sources[0]["size_bytes"]
    assert artifacts[0]["sha256"] == sources[0]["sha256"]
    assert set(cast(list[object], sources[0]["citation_refs"])) <= citation_refs
    assert datetime.fromisoformat(cast(str, provenance["started_at"])) <= datetime.fromisoformat(
        cast(str, provenance["ended_at"])
    )


def test_real_positive_values_are_exact_source_projections() -> None:
    source_text = (POSITIVE_ROOT / "source.cif").read_text(encoding="utf-8")
    result = load_json(POSITIVE_ROOT / "result-bundle.json")
    properties = cast(list[dict[str, object]], result["properties"])
    conditions = cast(list[dict[str, object]], result["conditions"])

    expected_tags = {
        "_cell_length_a": "5.4304",
        "_cell_length_b": "5.4304",
        "_cell_length_c": "5.4304",
        "_cell_angle_alpha": "90",
        "_cell_angle_beta": "90",
        "_cell_angle_gamma": "90",
        "_cell_volume": "160.138",
        "_diffrn_ambient_temperature": "298.15",
    }
    for tag, expected in expected_tags.items():
        match = re.search(rf"(?m)^{re.escape(tag)}\s+(\S+)\s*$", source_text)
        assert match is not None
        assert match.group(1) == expected

    projected_values = [
        cast(dict[str, object], scientific_property["value"])["value"]
        for scientific_property in properties
    ]
    assert [str(value) for value in projected_values] == [
        "5.4304",
        "5.4304",
        "5.4304",
        "90",
        "90",
        "90",
        "160.138",
    ]
    assert str(cast(dict[str, object], conditions[0]["value"])["value"]) == "298.15"


def test_generated_negative_cases_have_only_rejection_roles() -> None:
    for path in sorted(NEGATIVE_ROOT.glob("NG-*.json")):
        case = load_json(path)
        assert case["origin"] == "generated"
        assert case["role"] == "negative"
        assert cast(str, case["purpose"]).startswith("Reject")


@pytest.mark.parametrize("case_path", sorted(NEGATIVE_ROOT.glob("NG-000[1-5]-*.json")))
def test_generated_schema_negative_case_is_rejected(
    case_path: Path,
    schemas: dict[str, SchemaDocument],
    registry: Any,
) -> None:
    case = load_json(case_path)
    expected = cast(dict[str, object], case["expected"])
    instance = load_case_instance(case)
    schema_id = cast(str, case["schema_id"])
    errors = validation_errors(validator_for(schema_id, schemas, registry), instance)
    assert errors, f"{case_path.name} unexpectedly validated"

    matching = [
        error
        for error in flatten_errors(errors)
        if error.validator == expected["validator"]
        and list(error.absolute_path) == expected["instance_path"]
        and list(error.absolute_schema_path) == expected["schema_path"]
    ]
    assert matching, [
        (error.validator, list(error.absolute_path), list(error.absolute_schema_path))
        for error in flatten_errors(errors)
    ]


def test_unregistered_extension_is_rejected_after_core_validation(
    schemas: dict[str, SchemaDocument], registry: Any
) -> None:
    case = load_json(NEGATIVE_ROOT / "NG-0006-unregistered-extension.json")
    instance = load_case_instance(case)
    schema_id = cast(str, case["schema_id"])
    validate_instance(validator_for(schema_id, schemas, registry), instance)

    expected = cast(dict[str, object], case["expected"])
    failures = validate_extensions(instance, registry, frozenset(schemas))
    assert [(failure.code, list(failure.instance_path)) for failure in failures] == [
        (expected["code"], expected["instance_path"])
    ]


@pytest.mark.parametrize(
    ("path", "exception_type"),
    [
        (NEGATIVE_ROOT / "NG-0007-duplicate-key.json.txt", DuplicateKeyError),
        (NEGATIVE_ROOT / "NG-0008-non-finite-number.json.txt", ValueError),
    ],
)
def test_strict_json_loader_rejects_non_interoperable_json(
    path: Path, exception_type: type[Exception]
) -> None:
    with pytest.raises(exception_type):
        load_json(path)


def test_mutation_helper_does_not_modify_the_real_positive_record() -> None:
    original = load_json(POSITIVE_ROOT / "result-bundle.json")
    mutated = apply_add_mutation(original, "/generated-invalid-field", True)
    assert "generated-invalid-field" not in original
    assert mutated["generated-invalid-field"] is True
