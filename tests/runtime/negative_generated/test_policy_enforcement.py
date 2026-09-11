from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from materials_mcp_commons import (
    DISCOVER_CAPABILITY_ID,
    AuthorizationGrant,
    AuthorizationReceipt,
    ContractRegistry,
    Dispatcher,
    DispatchFailure,
    DispatchRequest,
    DispatchSuccess,
    Effect,
    HandlerRequest,
    LifecycleRegistry,
    LoadedManifest,
    Permission,
    PolicyEngine,
    PolicyError,
    PolicySnapshot,
    QuotaCharge,
    QuotaLimit,
    RunOwner,
    RunStore,
    RunStoreError,
)

PUBLIC_ROOT = Path(__file__).parents[3]
NOW = datetime(2026, 9, 11, 13, 0, tzinfo=UTC)
OWNER_REF = "urn:materials-mcp:owner:generated-policy-tests"


def _runtime(
    loaded_manifest: LoadedManifest,
    contracts: ContractRegistry,
    tier: str,
) -> tuple[LifecycleRegistry, Dispatcher, str]:
    settings = {
        "R1": ("bounded-local", False, False, False),
        "R2": ("compute-or-cost", True, True, False),
        "R4": ("destructive", True, True, True),
    }
    category, plan_required, approval_required, strong_required = settings[tier]
    changed = replace(
        loaded_manifest.capabilities[0],
        effect=Effect(
            tier,
            category,
            "Generated effect used only to prove the policy rejection boundary.",
            plan_required,
            approval_required,
            strong_required,
        ),
    )
    manifest = replace(loaded_manifest, capabilities=(changed, *loaded_manifest.capabilities[1:]))
    lifecycle = LifecycleRegistry()
    registration = lifecycle.register(manifest)
    lifecycle.activate(DISCOVER_CAPABILITY_ID, current_turn=0)
    return lifecycle, Dispatcher(lifecycle, contracts), registration.registration_ref


def _request(registration_ref: str, suffix: str = "one") -> DispatchRequest:
    return DispatchRequest(
        request_ref=f"urn:materials-mcp:request:generated-policy-{suffix}",
        registration_ref=registration_ref,
        capability_id=DISCOVER_CAPABILITY_ID,
        owner_ref=OWNER_REF,
        current_turn=1,
        occurred_at=NOW,
        payload={"query": "private-payload-marker"},
    )


def _plan(
    engine: PolicyEngine,
    request: DispatchRequest,
    target: object,
    *,
    recovery: dict[str, object] | None = None,
):
    from materials_mcp_commons import CapabilityDetail

    return engine.create_plan(
        request,
        cast(CapabilityDetail, target),
        steps=(
            {
                "step_id": "execute",
                "action": "invoke",
                "description": "Invoke the exact generated boundary-test target.",
                "targets": [request.capability_id],
            },
        ),
        permissions=(Permission("invoke", request.capability_id),),
        expected_outputs=({"role": "result", "media_type": "application/json"},),
        estimates=(
            {
                "kind": "compute",
                "value": {
                    "value_type": "integer",
                    "value": 1,
                    "unit": {"system": "UCUM", "identifier": "1", "symbol": "1"},
                },
            },
        ),
        risks=("Generated effect must never escape the isolated rejection test.",),
        recovery=recovery,
    )


def _policy() -> PolicySnapshot:
    return PolicySnapshot(
        OWNER_REF,
        (Permission("invoke", DISCOVER_CAPABILITY_ID),),
        (QuotaLimit("compute", 2),),
    )


def test_generated_r1_requires_exact_single_use_receipt_and_atomic_quota(
    tmp_path: Path,
    loaded_manifest: LoadedManifest,
    contract_registry: ContractRegistry,
) -> None:
    state = tmp_path / "policy"
    state.mkdir()
    lifecycle, _, registration_ref = _runtime(loaded_manifest, contract_registry, "R1")
    target = lifecycle.inspect(DISCOVER_CAPABILITY_ID)
    request = _request(registration_ref)
    invoked = 0

    def handler(_: HandlerRequest) -> object:
        nonlocal invoked
        invoked += 1
        return {"cards": []}

    with PolicyEngine(state, contract_registry) as engine:
        dispatcher = Dispatcher(lifecycle, contract_registry, engine)
        dispatcher.bind(registration_ref, DISCOVER_CAPABILITY_ID, handler)
        denied = dispatcher.dispatch(request)
        assert isinstance(denied, DispatchFailure)
        assert denied.to_document()["code"] == "EFFECT_POLICY_REQUIRED"
        plan = _plan(engine, request, target)
        assert plan.to_document()["approval"] == {
            "status": "not-required",
            "confirmation_kind": "none",
            "prompt": "No confirmation is required for this effect tier.",
        }
        policy = _policy()
        grant = engine.issue_grant(
            request,
            target,
            policy,
            plan,
            issued_at=NOW + timedelta(seconds=1),
            charges=(QuotaCharge("compute", 1),),
        )
        receipt = engine.consume(
            grant,
            request,
            target,
            policy,
            consumed_at=NOW + timedelta(seconds=2),
        )
        assert isinstance(receipt, AuthorizationReceipt)
        outcome = dispatcher.dispatch(request, policy=policy, authorization=receipt)
        assert isinstance(outcome, DispatchSuccess)
        assert outcome.to_result() == {"cards": []}
        assert invoked == 1
        mismatched = dispatcher.dispatch(
            _request(registration_ref, "mismatch"),
            policy=policy,
            authorization=receipt,
        )
        assert isinstance(mismatched, DispatchFailure)
        assert mismatched.to_document()["code"] == "AUTHORIZATION_DENIED"
        assert invoked == 1
        with pytest.raises(PolicyError, match="single-use") as replay:
            engine.consume(
                grant,
                request,
                target,
                policy,
                consumed_at=NOW + timedelta(seconds=3),
            )
        assert replay.value.code == "grant-consumed"
        contenders: list[tuple[AuthorizationGrant, DispatchRequest]] = []
        for suffix in ("quota-a", "quota-b"):
            contender_request = _request(registration_ref, suffix)
            contender_grant = engine.issue_grant(
                contender_request,
                target,
                policy,
                plan,
                issued_at=NOW + timedelta(seconds=4),
                charges=(QuotaCharge("compute", 1),),
            )
            contenders.append((contender_grant, contender_request))

        def consume_contender(index: int) -> str:
            contender_grant, contender_request = contenders[index]
            try:
                engine.consume(
                    contender_grant,
                    contender_request,
                    target,
                    policy,
                    consumed_at=NOW + timedelta(seconds=5),
                )
            except PolicyError as error:
                return error.code
            return "consumed"

        with ThreadPoolExecutor(max_workers=2) as workers:
            results = sorted(workers.map(consume_contender, (0, 1)))
        assert results == ["consumed", "quota-denied"]
        events = engine.audit_events(OWNER_REF)
        assert [event.sequence for event in events] == list(range(9))
        assert events[-1].event_type == "authorization-denied"
        assert events[-1].details["code"] == "quota-denied"
        assert "private-payload-marker" not in str(events)


def test_generated_r2_approval_expiry_scope_quota_and_run_boundary(
    tmp_path: Path,
    loaded_manifest: LoadedManifest,
    contract_registry: ContractRegistry,
) -> None:
    state = tmp_path / "state"
    artifacts = tmp_path / "artifacts"
    state.mkdir()
    artifacts.mkdir()
    lifecycle, _, registration_ref = _runtime(loaded_manifest, contract_registry, "R2")
    target = lifecycle.inspect(DISCOVER_CAPABILITY_ID)
    request = _request(registration_ref, "approved")
    with PolicyEngine(state, contract_registry) as engine:
        plan = _plan(engine, request, target)
        with pytest.raises(PolicyError) as weak:
            engine.approve(
                plan,
                approver_ref="urn:materials-mcp:approver:test",
                confirmation_kind="none",
                approved_at=NOW,
                expires_at=NOW + timedelta(minutes=1),
            )
        assert weak.value.code == "approval-strength"
        approval = engine.approve(
            plan,
            approver_ref="urn:materials-mcp:approver:test",
            confirmation_kind="strong",
            approved_at=NOW,
            expires_at=NOW + timedelta(minutes=1),
        )
        with pytest.raises(PolicyError) as denied_scope:
            engine.issue_grant(
                request,
                target,
                PolicySnapshot(OWNER_REF, (Permission("other", "urn:test:scope"),), ()),
                plan,
                issued_at=NOW + timedelta(seconds=1),
                approval=approval,
            )
        assert denied_scope.value.code == "permission-denied"
        policy = _policy()
        grant = engine.issue_grant(
            request,
            target,
            policy,
            plan,
            issued_at=NOW + timedelta(seconds=1),
            approval=approval,
            charges=(QuotaCharge("compute", 2),),
        )
        with pytest.raises(PolicyError) as reused_approval:
            engine.issue_grant(
                _request(registration_ref, "approval-reuse"),
                target,
                policy,
                plan,
                issued_at=NOW + timedelta(seconds=2),
                approval=approval,
            )
        assert reused_approval.value.code == "approval-invalid"
        receipt = engine.consume(
            grant,
            request,
            target,
            policy,
            consumed_at=NOW + timedelta(seconds=2),
        )
        with RunStore(state, artifacts, contract_registry, engine) as runs:
            created = runs.create_run(
                request_ref=request.request_ref,
                target=target,
                owner=RunOwner(OWNER_REF, "project"),
                created_at=NOW + timedelta(seconds=3),
                plan_ref=plan.plan_ref,
                authorization=receipt,
            )
            assert created.to_document()["plan_ref"] == plan.plan_ref
            with pytest.raises(RunStoreError) as forged:
                runs.create_run(
                    request_ref="urn:materials-mcp:request:forged",
                    target=target,
                    owner=RunOwner(OWNER_REF, "project"),
                    created_at=NOW + timedelta(seconds=4),
                    plan_ref=plan.plan_ref,
                    authorization=receipt,
                )
            assert forged.value.code == "authorization-denied"


def test_generated_r4_requires_recovery_and_audit_tampering_fails_reopen(
    tmp_path: Path,
    loaded_manifest: LoadedManifest,
    contract_registry: ContractRegistry,
) -> None:
    state = tmp_path / "policy"
    state.mkdir()
    lifecycle, _, registration_ref = _runtime(loaded_manifest, contract_registry, "R4")
    target = lifecycle.inspect(DISCOVER_CAPABILITY_ID)
    request = _request(registration_ref, "destructive")
    with PolicyEngine(state, contract_registry) as engine:
        with pytest.raises(PolicyError) as missing_recovery:
            _plan(engine, request, target)
        assert missing_recovery.value.code == "plan-contract-rejected"
        plan = _plan(
            engine,
            request,
            target,
            recovery={"available": True, "procedure": "Restore the isolated test fixture."},
        )
        approval_document = cast(dict[str, object], plan.to_document()["approval"])
        assert approval_document["confirmation_kind"] == "strong"

    database = state / PolicyEngine.DATABASE_NAME
    connection = sqlite3.connect(database)
    connection.execute("UPDATE audit_events SET details_json = ?", ('{"changed":true}',))
    connection.commit()
    connection.close()
    with pytest.raises(PolicyError) as corruption:
        PolicyEngine(state, contract_registry)
    assert corruption.value.code == "audit-corruption"


def test_policy_value_guards_reject_wildcards_duplicates_and_unsafe_state(
    tmp_path: Path,
    contract_registry: ContractRegistry,
) -> None:
    with pytest.raises(PolicyError):
        Permission("invoke", "*")
    with pytest.raises(PolicyError):
        QuotaCharge("compute", 0)
    with pytest.raises(PolicyError):
        QuotaLimit("compute", -1)
    permission = Permission("invoke", "urn:test:scope")
    with pytest.raises(PolicyError):
        PolicySnapshot(OWNER_REF, (permission, permission), ())
    with pytest.raises(PolicyError):
        PolicySnapshot(
            OWNER_REF,
            (permission,),
            (QuotaLimit("compute", 1), QuotaLimit("compute", 2)),
        )
    with pytest.raises(PolicyError):
        PolicyEngine(tmp_path / "missing", contract_registry)
