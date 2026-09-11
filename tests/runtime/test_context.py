from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import tiktoken

from materials_mcp_commons import (
    DISCOVER_CAPABILITY_ID,
    INSPECT_CAPABILITY_ID,
    ContextGateway,
    ContextPolicy,
    ContractRegistry,
    LifecycleRegistry,
    LoadedManifest,
    RetrievalCase,
    canonical_json,
    card_document,
    evaluate_retrieval,
    run_lifecycle_workload,
)
from materials_mcp_commons.contracts import load_json_object

PUBLIC_ROOT = Path(__file__).parents[2]
TOKENIZER_REF = "https://github.com/openai/tiktoken/tree/0.14.0#o200k_base"
GENERATED_AT = datetime(2026, 9, 11, 16, 0, tzinfo=UTC)


def _json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _gateway(contracts: ContractRegistry) -> ContextGateway:
    manifest = load_json_object(PUBLIC_ROOT / "tests/contracts/profile-0.2.0/context-manifest.json")
    policy = ContextPolicy.from_manifest(manifest, contracts)
    encoding = tiktoken.get_encoding("o200k_base")
    return ContextGateway(
        policy,
        contracts,
        token_counter=lambda text: len(encoding.encode(text)),
        tokenizer_ref=TOKENIZER_REF,
    )


def test_actual_engine_context_lint_uses_identified_tokenizer(
    loaded_manifest: LoadedManifest,
    contract_registry: ContractRegistry,
) -> None:
    lifecycle = LifecycleRegistry()
    lifecycle.register(loaded_manifest)
    cards = lifecycle.discover(limit=5)
    control_tools = [card_document(card) for card in cards]
    schema_root = PUBLIC_ROOT / "tests/runtime/positive-project/engine-lifecycle/schemas"
    active_schemas = [_json(path) for path in sorted(schema_root.glob("*.schema.json"))]
    compact = _json(
        PUBLIC_ROOT / "tests/contracts/positive-real/cod-9013102/compact-result-0.2.0.json"
    )
    gateway = _gateway(contract_registry)
    report = gateway.lint(
        control_tools=control_tools,
        discovery_cards=control_tools,
        active_schemas=active_schemas,
        inline_result=compact,
        historical_mcp_tokens=0,
        model_window_tokens=128_000,
    )

    assert report.tokenizer_ref == TOKENIZER_REF
    assert report.state == "pass"
    assert report.violations == ()
    assert [measurement.category for measurement in report.measurements] == [
        "control-surface",
        "discovery",
        "activation",
        "inline-result",
        "total-mcp",
    ]
    assert report.measurements[-1].token_fraction < 0.10
    assert report.measurements[1].tokens <= 500
    assert report.measurements[3].tokens <= 1500
    assert report.measurements[3].utf8_bytes == len(canonical_json(compact).encode("utf-8"))


def test_real_cod_result_projects_only_exact_source_values_and_references(
    contract_registry: ContractRegistry,
) -> None:
    rich = _json(PUBLIC_ROOT / "tests/contracts/positive-real/cod-9013102/result-bundle-0.2.0.json")
    gateway = _gateway(contract_registry)
    byte_projection = gateway.project_result(rich, generated_at=GENERATED_AT)
    document = byte_projection.to_document()
    budget = cast(dict[str, Any], cast(dict[str, Any], document["projection"])["budget"])
    assert budget["measurement"] == {"method": "utf8-bytes"}
    assert budget["observed"] == byte_projection.utf8_bytes
    assert byte_projection.utf8_bytes == len(canonical_json(document).encode("utf-8"))
    source_properties = cast(list[dict[str, Any]], rich["properties"])
    projected_properties = cast(list[dict[str, Any]], document["properties"])
    assert projected_properties
    for projected, source in zip(projected_properties, source_properties, strict=False):
        assert projected["property_ref"] == source["property_ref"]
        assert projected["value"] == source["value"]
        assert projected["condition_refs"] == source["condition_refs"]
        assert projected["evidence_refs"] == source["evidence_refs"]
    assert document["source_result_ref"] == rich["result_ref"]
    assert document["provenance_ref"] == rich["provenance"]["provenance_ref"]
    assert document["artifact_refs"] == [item["artifact_ref"] for item in rich["artifacts"]]

    token_projection = gateway.project_result(rich, generated_at=GENERATED_AT, unit="tokens")
    token_document = token_projection.to_document()
    token_budget = cast(
        dict[str, Any], cast(dict[str, Any], token_document["projection"])["budget"]
    )
    assert token_budget["observed"] == token_projection.tokens
    assert token_budget["measurement"] == {
        "method": "host-tokenizer",
        "tokenizer_ref": TOKENIZER_REF,
    }


def test_actual_catalog_retrieval_and_100_turn_lifecycle_are_bounded(
    loaded_manifest: LoadedManifest,
) -> None:
    lifecycle = LifecycleRegistry()
    lifecycle.register(loaded_manifest)
    corpus = _json(PUBLIC_ROOT / "tests/runtime/positive-project/engine-context/query-corpus.json")
    cases = tuple(
        RetrievalCase(
            case_id=cast(str, item["case_id"]),
            query=cast(str, item["query"]),
            expected_capability_ids=tuple(cast(list[str], item["expected_capability_ids"])),
        )
        for item in cast(list[dict[str, object]], corpus["cases"])
    )
    retrieval = evaluate_retrieval(lifecycle, cases, k=5)
    assert retrieval.total_cases == 4
    assert retrieval.passed_cases == 4
    assert retrieval.recall_at_k == 1.0
    assert retrieval.failed_case_ids == ()

    workload = run_lifecycle_workload(
        lifecycle,
        (DISCOVER_CAPABILITY_ID, INSPECT_CAPABILITY_ID),
        turns=100,
        lease_turns=3,
    )
    assert workload.turns == 100
    assert workload.peak_active == 2
    assert workload.p95_active == 2
    assert workload.final_active == 2
    assert not workload.monotonic_accumulation
