from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from itertools import pairwise
from types import MappingProxyType
from typing import NoReturn, cast

from .contracts import ContractRegistry
from .errors import ContextError, ContractError
from .lifecycle import CapabilityCard, LifecycleRegistry

REFERENCE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s]+$")
TokenCounter = Callable[[str], int]


def _fail(code: str, message: str) -> NoReturn:
    raise ContextError(code, message)


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        _fail("invalid-context-policy", f"{field_name} must be an object")
    return cast(Mapping[str, object], value)


def _integer(value: object, field_name: str) -> int:
    if type(value) is not int:
        _fail("invalid-context-policy", f"{field_name} must be an integer")
    return value


def _number(value: object, field_name: str) -> float:
    if type(value) not in {int, float, Decimal} or isinstance(value, bool):
        _fail("invalid-context-policy", f"{field_name} must be numeric")
    result = float(cast(int | float | Decimal, value))
    if not math.isfinite(result):
        _fail("invalid-context-policy", f"{field_name} must be finite")
    return result


def _timestamp(value: datetime) -> str:
    if type(value) is not datetime or value.utcoffset() is None:
        _fail("invalid-time", "generated_at must include a UTC offset")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {str(key): _plain(item) for key, item in mapping.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in cast(tuple[object, ...], value)]
    if isinstance(value, list):
        return [_plain(item) for item in cast(list[object], value)]
    return value


def canonical_json(value: object) -> str:
    try:
        return json.dumps(
            _plain(value),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as error:
        raise ContextError("invalid-json-value", "Context value is not strict JSON") from error


def _copy(value: object) -> object:
    return json.loads(canonical_json(value))


def _freeze(value: object) -> object:
    if isinstance(value, dict):
        document = cast(dict[str, object], value)
        return MappingProxyType({key: _freeze(item) for key, item in document.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in cast(list[object], value))
    return value


@dataclass(frozen=True)
class ContextPolicy:
    manifest_ref: str
    max_tools: int
    max_control_fraction: float
    max_cards: int
    max_discovery_tokens: int
    target_schemas: int
    max_schemas: int
    max_activation_fraction: float
    target_inline_tokens: int
    max_inline_tokens: int
    max_inline_bytes: int
    target_total_fraction: float
    warning_total_fraction: float
    intervention_total_fraction: float
    minimum_reasoning_fraction: float

    def __post_init__(self) -> None:
        if REFERENCE_PATTERN.fullmatch(self.manifest_ref) is None:
            _fail("invalid-context-policy", "manifest_ref must be an absolute reference")
        if not 1 <= self.max_tools <= 4 or not 1 <= self.max_cards <= 5:
            _fail("invalid-context-policy", "Control or discovery count is outside profile limits")
        if not 1 <= self.target_schemas <= self.max_schemas <= 8:
            _fail("invalid-context-policy", "Activation limits are inconsistent")
        if not 1 <= self.target_inline_tokens <= 800:
            _fail("invalid-context-policy", "Inline target exceeds the profile limit")
        if not self.target_inline_tokens <= self.max_inline_tokens <= 1500:
            _fail("invalid-context-policy", "Inline token limits are inconsistent")
        if not 1 <= self.max_inline_bytes <= 16384:
            _fail("invalid-context-policy", "Inline byte limit is outside the profile limit")
        if not 0 < self.max_control_fraction <= 0.02:
            _fail("invalid-context-policy", "Control fraction exceeds the profile limit")
        if not 0 < self.max_activation_fraction <= 0.03:
            _fail("invalid-context-policy", "Activation fraction exceeds the profile limit")
        if not (
            0
            < self.target_total_fraction
            <= self.warning_total_fraction
            <= self.intervention_total_fraction
            <= 0.15
        ):
            _fail("invalid-context-policy", "Total context fractions are inconsistent")
        if not 0.20 <= self.minimum_reasoning_fraction <= 1:
            _fail("invalid-context-policy", "Reasoning reserve is outside the profile limit")

    @classmethod
    def from_manifest(
        cls, manifest: Mapping[str, object], contracts: ContractRegistry
    ) -> ContextPolicy:
        contract = manifest.get("contract")
        if not isinstance(contract, str):
            _fail("invalid-context-policy", "Context manifest contract is missing")
        try:
            contracts.validate(contract, manifest)
        except ContractError as error:
            raise ContextError(
                "context-contract-rejected", "Context manifest failed its exact contract"
            ) from error
        budgets = _mapping(manifest.get("budgets"), "budgets")
        control = _mapping(budgets.get("control_surface"), "control_surface")
        discovery = _mapping(budgets.get("discovery"), "discovery")
        activation = _mapping(budgets.get("activation"), "activation")
        inline = _mapping(budgets.get("inline_result"), "inline_result")
        total = _mapping(budgets.get("total_mcp"), "total_mcp")
        manifest_ref = manifest.get("manifest_ref")
        if not isinstance(manifest_ref, str):
            _fail("invalid-context-policy", "manifest_ref is missing")
        return cls(
            manifest_ref=manifest_ref,
            max_tools=_integer(control.get("max_tools"), "max_tools"),
            max_control_fraction=_number(
                control.get("max_context_fraction"), "max_control_fraction"
            ),
            max_cards=_integer(discovery.get("max_cards"), "max_cards"),
            max_discovery_tokens=_integer(discovery.get("max_tokens"), "max_discovery_tokens"),
            target_schemas=_integer(activation.get("target_schemas"), "target_schemas"),
            max_schemas=_integer(activation.get("max_schemas"), "max_schemas"),
            max_activation_fraction=_number(
                activation.get("max_context_fraction"), "max_activation_fraction"
            ),
            target_inline_tokens=_integer(inline.get("target_tokens"), "target_inline_tokens"),
            max_inline_tokens=_integer(inline.get("max_tokens"), "max_inline_tokens"),
            max_inline_bytes=_integer(inline.get("max_utf8_bytes"), "max_inline_bytes"),
            target_total_fraction=_number(total.get("target_fraction"), "target_total_fraction"),
            warning_total_fraction=_number(total.get("warning_fraction"), "warning_total_fraction"),
            intervention_total_fraction=_number(
                total.get("intervention_fraction"), "intervention_total_fraction"
            ),
            minimum_reasoning_fraction=_number(
                total.get("minimum_reasoning_fraction"), "minimum_reasoning_fraction"
            ),
        )


@dataclass(frozen=True)
class ContextMeasurement:
    category: str
    utf8_bytes: int
    tokens: int
    token_fraction: float
    state: str


@dataclass(frozen=True)
class ContextViolation:
    code: str
    category: str
    observed: int | float
    limit: int | float


@dataclass(frozen=True)
class ContextReport:
    tokenizer_ref: str
    model_window_tokens: int
    measurements: tuple[ContextMeasurement, ...]
    violations: tuple[ContextViolation, ...]
    state: str


@dataclass(frozen=True)
class CompactProjection:
    document: Mapping[str, object]
    utf8_bytes: int
    tokens: int | None

    def to_document(self) -> dict[str, object]:
        return cast(dict[str, object], _plain(self.document))


@dataclass(frozen=True)
class RetrievalCase:
    case_id: str
    query: str
    expected_capability_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class RetrievalReport:
    total_cases: int
    passed_cases: int
    recall_at_k: float
    failed_case_ids: tuple[str, ...]


@dataclass(frozen=True)
class LifecycleWorkloadReport:
    turns: int
    peak_active: int
    p95_active: int
    final_active: int
    monotonic_accumulation: bool


class ContextGateway:
    """Exact context measurement and loss-declaring scientific result projection."""

    def __init__(
        self,
        policy: ContextPolicy,
        contracts: ContractRegistry,
        *,
        token_counter: TokenCounter,
        tokenizer_ref: str,
    ) -> None:
        if not callable(token_counter):
            _fail("tokenizer-required", "A host token counter is required")
        if type(tokenizer_ref) is not str or REFERENCE_PATTERN.fullmatch(tokenizer_ref) is None:
            _fail("tokenizer-reference", "tokenizer_ref must be an absolute reference")
        self._policy = policy
        self._contracts = contracts
        self._token_counter = token_counter
        self._tokenizer_ref = tokenizer_ref

    def _tokens(self, text: str) -> int:
        value = self._token_counter(text)
        if type(value) is not int or value < 0:
            _fail("invalid-token-count", "Host token counter returned an invalid count")
        return value

    def _measure(
        self, category: str, value: object, model_window_tokens: int
    ) -> ContextMeasurement:
        if type(model_window_tokens) is not int or model_window_tokens <= 0:
            _fail("invalid-model-window", "Model window must be a positive integer")
        text = canonical_json(value)
        tokens = self._tokens(text)
        fraction = tokens / model_window_tokens
        return ContextMeasurement(
            category,
            len(text.encode("utf-8")),
            tokens,
            fraction,
            "measured",
        )

    def lint(
        self,
        *,
        control_tools: Sequence[Mapping[str, object]],
        discovery_cards: Sequence[Mapping[str, object]],
        active_schemas: Sequence[Mapping[str, object]],
        inline_result: Mapping[str, object] | None,
        historical_mcp_tokens: int,
        model_window_tokens: int,
    ) -> ContextReport:
        if type(historical_mcp_tokens) is not int or historical_mcp_tokens < 0:
            _fail("invalid-history", "Historical MCP tokens must be non-negative")
        measurements = (
            self._measure("control-surface", list(control_tools), model_window_tokens),
            self._measure("discovery", list(discovery_cards), model_window_tokens),
            self._measure("activation", list(active_schemas), model_window_tokens),
            self._measure(
                "inline-result", {} if inline_result is None else inline_result, model_window_tokens
            ),
        )
        violations: list[ContextViolation] = []
        if len(control_tools) > self._policy.max_tools:
            violations.append(
                ContextViolation(
                    "CONTROL_TOOL_LIMIT",
                    "control-surface",
                    len(control_tools),
                    self._policy.max_tools,
                )
            )
        if measurements[0].token_fraction > self._policy.max_control_fraction:
            violations.append(
                ContextViolation(
                    "CONTROL_FRACTION_LIMIT",
                    "control-surface",
                    measurements[0].token_fraction,
                    self._policy.max_control_fraction,
                )
            )
        if len(discovery_cards) > self._policy.max_cards:
            violations.append(
                ContextViolation(
                    "DISCOVERY_CARD_LIMIT",
                    "discovery",
                    len(discovery_cards),
                    self._policy.max_cards,
                )
            )
        if measurements[1].tokens > self._policy.max_discovery_tokens:
            violations.append(
                ContextViolation(
                    "DISCOVERY_TOKEN_LIMIT",
                    "discovery",
                    measurements[1].tokens,
                    self._policy.max_discovery_tokens,
                )
            )
        if len(active_schemas) > self._policy.max_schemas:
            violations.append(
                ContextViolation(
                    "ACTIVE_SCHEMA_LIMIT",
                    "activation",
                    len(active_schemas),
                    self._policy.max_schemas,
                )
            )
        if measurements[2].token_fraction > self._policy.max_activation_fraction:
            violations.append(
                ContextViolation(
                    "ACTIVATION_FRACTION_LIMIT",
                    "activation",
                    measurements[2].token_fraction,
                    self._policy.max_activation_fraction,
                )
            )
        if inline_result is not None:
            if measurements[3].tokens > self._policy.max_inline_tokens:
                violations.append(
                    ContextViolation(
                        "INLINE_TOKEN_LIMIT",
                        "inline-result",
                        measurements[3].tokens,
                        self._policy.max_inline_tokens,
                    )
                )
            if measurements[3].utf8_bytes > self._policy.max_inline_bytes:
                violations.append(
                    ContextViolation(
                        "INLINE_BYTE_LIMIT",
                        "inline-result",
                        measurements[3].utf8_bytes,
                        self._policy.max_inline_bytes,
                    )
                )
        total_tokens = historical_mcp_tokens + sum(item.tokens for item in measurements)
        total_fraction = total_tokens / model_window_tokens
        total_state = "target"
        if total_fraction > self._policy.intervention_total_fraction:
            total_state = "intervention"
            violations.append(
                ContextViolation(
                    "TOTAL_INTERVENTION",
                    "total-mcp",
                    total_fraction,
                    self._policy.intervention_total_fraction,
                )
            )
        elif total_fraction > self._policy.warning_total_fraction:
            total_state = "warning"
        elif total_fraction > self._policy.target_total_fraction:
            total_state = "above-target"
        if total_fraction > 1 - self._policy.minimum_reasoning_fraction:
            violations.append(
                ContextViolation(
                    "REASONING_RESERVE",
                    "total-mcp",
                    total_fraction,
                    1 - self._policy.minimum_reasoning_fraction,
                )
            )
        total = ContextMeasurement(
            "total-mcp",
            sum(item.utf8_bytes for item in measurements),
            total_tokens,
            total_fraction,
            total_state,
        )
        return ContextReport(
            self._tokenizer_ref,
            model_window_tokens,
            (*measurements, total),
            tuple(violations),
            "pass" if not violations else "intervention-required",
        )

    @staticmethod
    def _compact_property(value: Mapping[str, object]) -> dict[str, object] | None:
        raw_value = value.get("value")
        uncertainty = value.get("uncertainty")
        condition_refs = value.get("condition_refs")
        evidence_refs = value.get("evidence_refs")
        if not isinstance(raw_value, Mapping) or not isinstance(uncertainty, Mapping):
            return None
        condition_list = (
            cast(list[object], condition_refs) if isinstance(condition_refs, list) else None
        )
        evidence_list = (
            cast(list[object], evidence_refs) if isinstance(evidence_refs, list) else None
        )
        if condition_list is None or len(condition_list) > 4:
            return None
        if evidence_list is None or not 1 <= len(evidence_list) <= 4:
            return None
        raw_mapping = cast(Mapping[str, object], raw_value)
        uncertainty_mapping = cast(Mapping[str, object], uncertainty)
        if uncertainty_mapping.get("status") not in {"not-reported", "reported"}:
            return None
        raw_document = cast(dict[str, object], _copy(raw_mapping))
        if raw_document.get("value_type") == "number-array":
            items = raw_document.get("value")
            item_list = cast(list[object], items) if isinstance(items, list) else None
            if item_list is None or len(item_list) > 4:
                return None
        if raw_document.get("value_type") == "text":
            text = raw_document.get("value")
            if not isinstance(text, str) or len(text) > 512:
                return None
        required = ("property_ref", "label", "subject_ref")
        if not all(isinstance(value.get(key), str) for key in required):
            return None
        return {
            "property_ref": value["property_ref"],
            "label": value["label"],
            "subject_ref": value["subject_ref"],
            "value": raw_document,
            "uncertainty_status": uncertainty_mapping.get("status"),
            "condition_refs": _copy(condition_list),
            "evidence_refs": _copy(evidence_list),
        }

    def _projection_measurement(self, document: dict[str, object], unit: str) -> int:
        budget = cast(dict[str, object], cast(dict[str, object], document["projection"])["budget"])
        observed = -1
        for _ in range(8):
            budget["observed"] = max(observed, 0)
            text = canonical_json(document)
            measured = len(text.encode("utf-8")) if unit == "utf8-bytes" else self._tokens(text)
            if measured == observed:
                return measured
            observed = measured
        _fail("measurement-unstable", "Projection measurement did not reach a fixed point")

    def project_result(
        self,
        rich_result: Mapping[str, object],
        *,
        generated_at: datetime,
        unit: str = "utf8-bytes",
    ) -> CompactProjection:
        rich = cast(dict[str, object], _copy(rich_result))
        rich_contract = rich.get("contract")
        if not isinstance(rich_contract, str):
            _fail("invalid-rich-result", "Rich result contract is missing")
        try:
            self._contracts.validate(rich_contract, rich)
        except ContractError as error:
            raise ContextError("rich-result-rejected", "Rich result failed its contract") from error
        if unit not in {"utf8-bytes", "tokens"}:
            _fail("invalid-measurement-unit", "Projection unit must be tokens or utf8-bytes")
        entities = cast(list[dict[str, object]], rich["entities"])
        properties = cast(list[dict[str, object]], rich["properties"])
        conditions = cast(list[dict[str, object]], rich["conditions"])
        artifacts = cast(list[dict[str, object]], rich["artifacts"])
        citations = cast(list[dict[str, object]], rich["citations"])
        warnings = cast(list[str], rich["warnings"])
        quality = cast(dict[str, object], rich["quality"])
        limitations = cast(list[str], quality["limitations"])
        compact_properties = [
            item
            for item in (self._compact_property(value) for value in properties)
            if item is not None
        ][:8]
        compact_conditions = [
            item
            for item in (self._compact_property(value) for value in conditions)
            if item is not None
        ][:4]
        document: dict[str, object] = {
            "contract": f"{self._contracts.canonical_base}compact-result.schema.json",
            "profile_version": self._contracts.profile_version,
            "source_result_ref": rich["result_ref"],
            "produced_at": rich["produced_at"],
            "status": rich["status"],
            "entity_refs": [item["entity_ref"] for item in entities[:16]],
            "properties": compact_properties,
            "conditions": compact_conditions,
            "artifact_refs": [item["artifact_ref"] for item in artifacts[:8]],
            "quality": {
                "status": quality["status"],
                "reason": quality["reason"],
                "limitations": limitations[:4],
                "omitted_limitations": max(0, len(limitations) - 4),
            },
            "provenance_ref": cast(dict[str, object], rich["provenance"])["provenance_ref"],
            "citation_refs": [item["citation_ref"] for item in citations[:8]],
            "warnings": warnings[:8],
            "omitted": {},
            "projection": {
                "mode": "compact",
                "source_contract": rich_contract,
                "generated_at": _timestamp(generated_at),
                "selection": "source-order",
                "budget": {
                    "policy_ref": self._policy.manifest_ref,
                    "class": "inline-result",
                    "unit": unit,
                    "limit": self._policy.max_inline_bytes
                    if unit == "utf8-bytes"
                    else self._policy.max_inline_tokens,
                    "observed": 0,
                    "measurement": {"method": unit}
                    if unit == "utf8-bytes"
                    else {"method": "host-tokenizer", "tokenizer_ref": self._tokenizer_ref},
                },
            },
        }
        if "run_ref" in rich:
            document["run_ref"] = rich["run_ref"]

        def update_omissions() -> None:
            counts = {
                "entities": len(entities) - len(cast(list[object], document["entity_refs"])),
                "properties": len(properties) - len(cast(list[object], document["properties"])),
                "conditions": len(conditions) - len(cast(list[object], document["conditions"])),
                "artifacts": len(artifacts) - len(cast(list[object], document["artifact_refs"])),
                "citations": len(citations) - len(cast(list[object], document["citation_refs"])),
                "warnings": len(warnings) - len(cast(list[object], document["warnings"])),
            }
            counts["truncated"] = any(value > 0 for value in counts.values())
            document["omitted"] = counts
            cast(dict[str, object], document["projection"])["selection"] = (
                "source-order" if counts["truncated"] else "all-within-budget"
            )

        update_omissions()
        limit = (
            self._policy.max_inline_bytes
            if unit == "utf8-bytes"
            else self._policy.max_inline_tokens
        )
        observed = self._projection_measurement(document, unit)
        trim_order = ("properties", "conditions", "citation_refs", "warnings", "artifact_refs")
        while observed > limit:
            trimmed = False
            for key in trim_order:
                values = cast(list[object], document[key])
                if values:
                    values.pop()
                    trimmed = True
                    break
            if not trimmed:
                entity_refs = cast(list[object], document["entity_refs"])
                quality_document = cast(dict[str, object], document["quality"])
                quality_limits = cast(list[object], quality_document["limitations"])
                if len(entity_refs) > 1:
                    entity_refs.pop()
                    trimmed = True
                elif quality_limits:
                    quality_limits.pop()
                    quality_document["omitted_limitations"] = len(limitations) - len(quality_limits)
                    trimmed = True
            if not trimmed:
                _fail("projection-too-large", "Irreducible compact result exceeds the budget")
            update_omissions()
            observed = self._projection_measurement(document, unit)
        try:
            self._contracts.validate(cast(str, document["contract"]), document)
        except ContractError as error:
            raise ContextError(
                "compact-result-rejected", "Projected result failed its exact contract"
            ) from error
        text = canonical_json(document)
        tokens = self._tokens(text) if unit == "tokens" else None
        return CompactProjection(
            cast(Mapping[str, object], _freeze(document)),
            len(text.encode("utf-8")),
            tokens,
        )


def evaluate_retrieval(
    lifecycle: LifecycleRegistry,
    cases: Sequence[RetrievalCase],
    *,
    k: int = 5,
) -> RetrievalReport:
    if not cases or type(k) is not int or not 1 <= k <= 5:
        _fail("invalid-retrieval-evaluation", "Retrieval evaluation requires cases and k 1-5")
    passed = 0
    recalled = 0
    relevant = 0
    failed: list[str] = []
    for case in cases:
        cards = lifecycle.discover(case.query, limit=k)
        actual = {card.capability_id for card in cards}
        expected = set(case.expected_capability_ids)
        case_passed = not actual if not expected else expected.issubset(actual)
        if case_passed:
            passed += 1
        else:
            failed.append(case.case_id)
        recalled += len(actual.intersection(expected))
        relevant += len(expected)
    recall = 1.0 if relevant == 0 else recalled / relevant
    return RetrievalReport(len(cases), passed, recall, tuple(failed))


def run_lifecycle_workload(
    lifecycle: LifecycleRegistry,
    capability_ids: Sequence[str],
    *,
    turns: int = 100,
    lease_turns: int = 3,
) -> LifecycleWorkloadReport:
    if not capability_ids or type(turns) is not int or turns <= 0:
        _fail("invalid-lifecycle-workload", "Lifecycle workload requires capabilities and turns")
    counts: list[int] = []
    for turn in range(turns):
        lifecycle.activate(
            capability_ids[turn % len(capability_ids)],
            current_turn=turn,
            lease_turns=lease_turns,
        )
        counts.append(len(lifecycle.active(current_turn=turn)))
    ordered = sorted(counts)
    p95 = ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]
    monotonic = all(left < right for left, right in pairwise(counts))
    return LifecycleWorkloadReport(turns, max(counts), p95, counts[-1], monotonic)


def card_document(card: CapabilityCard) -> dict[str, object]:
    return {
        "capability_id": card.capability_id,
        "title": card.title,
        "description": card.description,
        "effect_tier": card.effect_tier,
        "supports_async": card.supports_async,
    }
