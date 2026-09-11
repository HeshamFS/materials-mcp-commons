from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
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
    ManifestLoader,
    RetrievalCase,
    card_document,
    evaluate_retrieval,
    run_lifecycle_workload,
)
from materials_mcp_commons.contracts import load_json_object

PUBLIC_ROOT = Path(__file__).parents[1]
TOKENIZER_REF = "https://github.com/openai/tiktoken/tree/0.14.0#o200k_base"
MODEL_WINDOW_TOKENS = 128_000


def _json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def build_context_report(public_root: Path = PUBLIC_ROOT) -> dict[str, object]:
    contracts = ContractRegistry.from_directory(public_root / "schemas/0.2.0", "0.2.0")
    context_document = load_json_object(
        public_root / "tests/contracts/profile-0.2.0/context-manifest.json"
    )
    policy = ContextPolicy.from_manifest(context_document, contracts)
    encoding = tiktoken.get_encoding("o200k_base")
    gateway = ContextGateway(
        policy,
        contracts,
        token_counter=lambda text: len(encoding.encode(text)),
        tokenizer_ref=TOKENIZER_REF,
    )
    manifest_root = public_root / "tests/runtime/positive-project/engine-lifecycle"
    manifest = ManifestLoader(contracts).load(manifest_root)
    lifecycle = LifecycleRegistry()
    lifecycle.register(manifest)
    cards = lifecycle.discover(limit=5)
    card_documents = [card_document(card) for card in cards]
    active_schemas = [
        _json(path) for path in sorted((manifest_root / "schemas").glob("*.schema.json"))
    ]
    compact = _json(
        public_root / "tests/contracts/positive-real/cod-9013102/compact-result-0.2.0.json"
    )
    lint = gateway.lint(
        control_tools=card_documents,
        discovery_cards=card_documents,
        active_schemas=active_schemas,
        inline_result=compact,
        historical_mcp_tokens=0,
        model_window_tokens=MODEL_WINDOW_TOKENS,
    )
    rich = _json(public_root / "tests/contracts/positive-real/cod-9013102/result-bundle-0.2.0.json")
    declared_at = cast(str, context_document["declared_at"])
    generated_at = datetime.fromisoformat(declared_at.replace("Z", "+00:00"))
    byte_projection = gateway.project_result(rich, generated_at=generated_at)
    token_projection = gateway.project_result(rich, generated_at=generated_at, unit="tokens")
    corpus = _json(public_root / "tests/runtime/positive-project/engine-context/query-corpus.json")
    cases = tuple(
        RetrievalCase(
            cast(str, item["case_id"]),
            cast(str, item["query"]),
            tuple(cast(list[str], item["expected_capability_ids"])),
        )
        for item in cast(list[dict[str, object]], corpus["cases"])
    )
    retrieval = evaluate_retrieval(lifecycle, cases, k=5)
    workload = run_lifecycle_workload(
        lifecycle,
        (DISCOVER_CAPABILITY_ID, INSPECT_CAPABILITY_ID),
        turns=100,
        lease_turns=3,
    )
    byte_document = byte_projection.to_document()
    token_document = token_projection.to_document()
    return {
        "report_version": 1,
        "scope": "actual-engine-control-plane",
        "context_policy_ref": policy.manifest_ref,
        "tokenizer_ref": TOKENIZER_REF,
        "model_window_tokens": MODEL_WINDOW_TOKENS,
        "lint": {
            "state": lint.state,
            "violations": [asdict(item) for item in lint.violations],
            "measurements": [asdict(item) for item in lint.measurements],
        },
        "projection": {
            "source_result_ref": rich["result_ref"],
            "utf8_bytes": byte_projection.utf8_bytes,
            "byte_omissions": byte_document["omitted"],
            "tokens": token_projection.tokens,
            "token_omissions": token_document["omitted"],
        },
        "retrieval": {
            "total_cases": retrieval.total_cases,
            "passed_cases": retrieval.passed_cases,
            "recall_at_k": retrieval.recall_at_k,
            "failed_case_ids": list(retrieval.failed_case_ids),
        },
        "lifecycle": asdict(workload),
        "limitations": [
            "This report covers actual engine control capabilities, not scientific-domain breadth.",
            "Token measurements apply only to the exact identified tokenizer and model window.",
        ],
    }


def serialize_context_report(report: dict[str, object]) -> str:
    return json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    print(serialize_context_report(build_context_report()), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
