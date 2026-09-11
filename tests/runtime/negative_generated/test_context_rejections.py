from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest

from materials_mcp_commons import (
    ContextError,
    ContextGateway,
    ContextPolicy,
    ContractRegistry,
    LifecycleRegistry,
    LoadedManifest,
    RetrievalCase,
    canonical_json,
    evaluate_retrieval,
    run_lifecycle_workload,
)
from materials_mcp_commons.contracts import load_json_object

PUBLIC_ROOT = Path(__file__).parents[3]
NOW = datetime(2026, 9, 11, 16, 0, tzinfo=UTC)
TOKENIZER_REF = "urn:materials-mcp:generated-negative-tokenizer"


def _json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _policy(contracts: ContractRegistry) -> ContextPolicy:
    document = load_json_object(PUBLIC_ROOT / "tests/contracts/profile-0.2.0/context-manifest.json")
    return ContextPolicy.from_manifest(document, contracts)


def test_generated_context_policy_tokenizer_and_json_guards_fail_closed(
    contract_registry: ContractRegistry,
) -> None:
    context_path = PUBLIC_ROOT / "tests/contracts/profile-0.2.0/context-manifest.json"
    invalid = load_json_object(context_path)
    budgets = cast(dict[str, object], invalid["budgets"])
    control = cast(dict[str, object], budgets["control_surface"])
    control["max_tools"] = 5
    with pytest.raises(ContextError) as rejected:
        ContextPolicy.from_manifest(invalid, contract_registry)
    assert rejected.value.code == "context-contract-rejected"

    policy = _policy(contract_registry)
    with pytest.raises(ContextError) as bad_ref:
        ContextGateway(policy, contract_registry, token_counter=len, tokenizer_ref="relative")
    assert bad_ref.value.code == "tokenizer-reference"
    with pytest.raises(ContextError) as non_json:
        canonical_json({"value": object()})
    assert non_json.value.code == "invalid-json-value"
    with pytest.raises(ContextError):
        canonical_json({"value": float("nan")})


def test_generated_linter_reports_each_budget_boundary(
    contract_registry: ContractRegistry,
) -> None:
    gateway = ContextGateway(
        _policy(contract_registry),
        contract_registry,
        token_counter=lambda text: len(text.encode("utf-8")),
        tokenizer_ref=TOKENIZER_REF,
    )
    report = gateway.lint(
        control_tools=tuple({"tool": str(index), "body": "x" * 100} for index in range(5)),
        discovery_cards=tuple({"card": str(index), "body": "x" * 100} for index in range(6)),
        active_schemas=tuple({"schema": str(index), "body": "x" * 100} for index in range(9)),
        inline_result={"body": "x" * 9000},
        historical_mcp_tokens=20,
        model_window_tokens=100,
    )
    codes = {violation.code for violation in report.violations}
    assert codes == {
        "CONTROL_TOOL_LIMIT",
        "CONTROL_FRACTION_LIMIT",
        "DISCOVERY_CARD_LIMIT",
        "DISCOVERY_TOKEN_LIMIT",
        "ACTIVE_SCHEMA_LIMIT",
        "ACTIVATION_FRACTION_LIMIT",
        "INLINE_TOKEN_LIMIT",
        "INLINE_BYTE_LIMIT",
        "TOTAL_INTERVENTION",
        "REASONING_RESERVE",
    }
    assert report.state == "intervention-required"
    with pytest.raises(ContextError) as invalid_window:
        gateway.lint(
            control_tools=(),
            discovery_cards=(),
            active_schemas=(),
            inline_result=None,
            historical_mcp_tokens=0,
            model_window_tokens=0,
        )
    assert invalid_window.value.code == "invalid-model-window"


def test_generated_projection_rejects_invalid_irreducible_and_unstable_inputs(
    contract_registry: ContractRegistry,
) -> None:
    policy = _policy(contract_registry)
    gateway = ContextGateway(
        policy,
        contract_registry,
        token_counter=lambda text: len(text),
        tokenizer_ref=TOKENIZER_REF,
    )
    with pytest.raises(ContextError) as invalid_rich:
        gateway.project_result({}, generated_at=NOW)
    assert invalid_rich.value.code == "invalid-rich-result"
    rich = _json(PUBLIC_ROOT / "tests/contracts/positive-real/cod-9013102/result-bundle-0.2.0.json")
    with pytest.raises(ContextError) as invalid_unit:
        gateway.project_result(rich, generated_at=NOW, unit="characters")
    assert invalid_unit.value.code == "invalid-measurement-unit"
    tiny = replace(policy, max_inline_bytes=1)
    with pytest.raises(ContextError) as irreducible:
        ContextGateway(
            tiny,
            contract_registry,
            token_counter=lambda text: len(text),
            tokenizer_ref=TOKENIZER_REF,
        ).project_result(rich, generated_at=NOW)
    assert irreducible.value.code == "projection-too-large"

    calls = 0

    def unstable(_: str) -> int:
        nonlocal calls
        calls += 1
        return calls

    with pytest.raises(ContextError) as unstable_measurement:
        ContextGateway(
            policy,
            contract_registry,
            token_counter=unstable,
            tokenizer_ref=TOKENIZER_REF,
        ).project_result(rich, generated_at=NOW, unit="tokens")
    assert unstable_measurement.value.code == "measurement-unstable"


def test_generated_unprojectable_value_is_omitted_not_truncated(
    contract_registry: ContractRegistry,
) -> None:
    rich = _json(PUBLIC_ROOT / "tests/contracts/positive-real/cod-9013102/result-bundle-0.2.0.json")
    first = cast(list[dict[str, Any]], rich["properties"])[0]
    first["value"] = {
        "value_type": "number-array",
        "value": [1.0, 2.0, 3.0, 4.0, 5.0],
        "unit": {"system": "UCUM", "identifier": "1", "symbol": "1"},
    }
    projected = ContextGateway(
        _policy(contract_registry),
        contract_registry,
        token_counter=lambda text: len(text),
        tokenizer_ref=TOKENIZER_REF,
    ).project_result(rich, generated_at=NOW)
    document = projected.to_document()
    omitted = cast(dict[str, object], document["omitted"])
    assert omitted["properties"] == 1
    assert omitted["truncated"] is True
    assert all(
        item["property_ref"] != first["property_ref"]
        for item in cast(list[dict[str, object]], document["properties"])
    )


def test_generated_retrieval_and_workload_input_boundaries(
    loaded_manifest: LoadedManifest,
) -> None:
    lifecycle = LifecycleRegistry()
    lifecycle.register(loaded_manifest)
    with pytest.raises(ContextError):
        evaluate_retrieval(lifecycle, ())
    failed = evaluate_retrieval(
        lifecycle,
        (RetrievalCase("missing", "weather forecast", ("urn:missing:capability",)),),
    )
    assert failed.passed_cases == 0
    assert failed.recall_at_k == 0.0
    assert failed.failed_case_ids == ("missing",)
    with pytest.raises(ContextError):
        run_lifecycle_workload(lifecycle, (), turns=100)
