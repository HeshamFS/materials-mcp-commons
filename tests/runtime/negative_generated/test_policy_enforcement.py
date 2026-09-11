from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Barrier
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


def _create_v1_policy_store(state: Path) -> None:
    database = state / PolicyEngine.DATABASE_NAME
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE plans (
                plan_ref TEXT PRIMARY KEY, owner_ref TEXT NOT NULL,
                registration_ref TEXT NOT NULL, capability_id TEXT NOT NULL,
                input_sha256 TEXT NOT NULL, document_json TEXT NOT NULL
            );
            CREATE TABLE approvals (
                approval_ref TEXT PRIMARY KEY, plan_ref TEXT NOT NULL,
                owner_ref TEXT NOT NULL, approver_ref TEXT NOT NULL,
                confirmation_kind TEXT NOT NULL, approved_at TEXT NOT NULL,
                expires_at TEXT NOT NULL, used_grant_ref TEXT,
                FOREIGN KEY(plan_ref) REFERENCES plans(plan_ref) ON DELETE RESTRICT
            );
            CREATE TABLE grants (
                grant_ref TEXT PRIMARY KEY, document_json TEXT NOT NULL,
                consumed_at TEXT, receipt_ref TEXT
            );
            CREATE TABLE quota_usage (
                owner_ref TEXT NOT NULL, policy_sha256 TEXT NOT NULL,
                kind TEXT NOT NULL, used INTEGER NOT NULL,
                PRIMARY KEY(owner_ref, policy_sha256, kind)
            );
            CREATE TABLE audit_events (
                owner_ref TEXT NOT NULL, sequence INTEGER NOT NULL,
                event_type TEXT NOT NULL, subject_ref TEXT NOT NULL,
                occurred_at TEXT NOT NULL, previous_sha256 TEXT NOT NULL,
                event_sha256 TEXT NOT NULL, details_json TEXT NOT NULL,
                PRIMARY KEY(owner_ref, sequence), UNIQUE(event_sha256)
            );
            PRAGMA user_version = 1;
            """
        )


def test_policy_input_hash_preserves_existing_json_and_decimal_lexemes() -> None:
    base = DispatchRequest(
        request_ref="urn:materials-mcp:request:hash-golden",
        registration_ref="urn:materials-mcp:registration:hash-golden",
        capability_id=DISCOVER_CAPABILITY_ID,
        owner_ref=OWNER_REF,
        current_turn=1,
        occurred_at=NOW,
        payload={"query": "private-payload-marker"},
    )
    assert PolicyEngine.input_sha256(base) == (
        "04d7edab39c7a1b5e1407fcca3c6a8e92da8d4c545cb35c8338a68653f944716"
    )
    one_decimal = replace(base, payload={"value": Decimal("1.0")})
    two_decimals = replace(base, payload={"value": Decimal("1.00")})
    exponent = replace(base, payload={"value": Decimal("1E+2")})
    assert PolicyEngine.input_sha256(one_decimal) == (
        "3a7d647740ec6f86b72e0bf3948ab456551e07e9605e3a2785de1c66842ebb48"
    )
    assert PolicyEngine.input_sha256(two_decimals) == (
        "c4116324f2ee169683c21d3c0a344db40d8ffa2b7280e99f2736328442c4213e"
    )
    assert PolicyEngine.input_sha256(exponent) == (
        "9f699670c3b3709d486397490df292c80a15d87ee5bfa29fb86146c78d8e1f27"
    )


def test_generated_r1_requires_exact_single_use_receipt_and_atomic_quota(
    tmp_path: Path,
    loaded_manifest: LoadedManifest,
    contract_registry: ContractRegistry,
    monkeypatch: pytest.MonkeyPatch,
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
        malformed_receipt = replace(receipt, receipt_ref=cast(str, None))
        malformed = dispatcher.dispatch(
            request,
            policy=policy,
            authorization=malformed_receipt,
        )
        assert isinstance(malformed, DispatchFailure)
        invalid_type = dispatcher.dispatch(
            request,
            policy=policy,
            authorization=cast(AuthorizationReceipt, object()),
        )
        assert isinstance(invalid_type, DispatchFailure)
        assert invoked == 0
        engine.verify_receipt(receipt, request, target, policy)
        engine.verify_receipt(receipt, request, target, policy)
        outcome = dispatcher.dispatch(request, policy=policy, authorization=receipt)
        assert isinstance(outcome, DispatchSuccess)
        assert outcome.to_result() == {"cards": []}
        assert invoked == 1
        replay = dispatcher.dispatch(request, policy=policy, authorization=receipt)
        assert isinstance(replay, DispatchFailure)
        assert replay.to_document()["code"] == "AUTHORIZATION_DENIED"
        forged_request = _request(registration_ref, "forged-receipt")
        forged_receipt = replace(
            receipt,
            request_ref=forged_request.request_ref,
            input_sha256=PolicyEngine.input_sha256(forged_request),
        )
        forged_outcome = dispatcher.dispatch(
            forged_request,
            policy=policy,
            authorization=forged_receipt,
        )
        assert isinstance(forged_outcome, DispatchFailure)
        assert forged_outcome.to_document()["code"] == "AUTHORIZATION_DENIED"
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
        assert [event.sequence for event in events] == list(range(13))
        assert events[-1].event_type == "authorization-denied"
        assert events[-1].details["code"] == "quota-denied"
        assert "private-payload-marker" not in str(events)
        locked_error = sqlite3.OperationalError("private database lock detail")
        locked_error.sqlite_errorcode = sqlite3.SQLITE_BUSY  # pyright: ignore[reportAttributeAccessIssue]

        def locked_redemption(*_: object) -> None:
            raise locked_error

        monkeypatch.setattr(engine, "redeem_receipt", locked_redemption)
        locked = dispatcher.dispatch(request, policy=policy, authorization=receipt)
        assert isinstance(locked, DispatchFailure)
        locked_document = locked.to_document()
        assert locked_document["code"] == "AUTHORIZATION_DENIED"
        assert locked_document["retryable"] is True
        assert "private database lock detail" not in str(locked_document)
        assert invoked == 1

        def broken_redemption(*_: object) -> None:
            raise RuntimeError("private authorization failure")

        monkeypatch.setattr(engine, "redeem_receipt", broken_redemption)
        broken = dispatcher.dispatch(request, policy=policy, authorization=receipt)
        assert isinstance(broken, DispatchFailure)
        broken_document = broken.to_document()
        assert broken_document["code"] == "AUTHORIZATION_DENIED"
        assert broken_document["retryable"] is False
        assert "private authorization failure" not in str(broken_document)
        assert invoked == 1


def test_receipt_redemption_is_atomic_across_policy_engines(
    tmp_path: Path,
    loaded_manifest: LoadedManifest,
    contract_registry: ContractRegistry,
) -> None:
    state = tmp_path / "policy"
    state.mkdir()
    lifecycle, _, registration_ref = _runtime(loaded_manifest, contract_registry, "R1")
    target = lifecycle.inspect(DISCOVER_CAPABILITY_ID)
    request = _request(registration_ref, "concurrent-redemption")
    invoked = 0

    def handler(_: HandlerRequest) -> object:
        nonlocal invoked
        invoked += 1
        return {"cards": []}

    first_engine = PolicyEngine(state, contract_registry)
    second_engine = PolicyEngine(state, contract_registry)
    try:
        policy = _policy()
        plan = _plan(first_engine, request, target)
        grant = first_engine.issue_grant(
            request,
            target,
            policy,
            plan,
            issued_at=NOW + timedelta(seconds=1),
            charges=(QuotaCharge("compute", 1),),
        )
        receipt = first_engine.consume(
            grant,
            request,
            target,
            policy,
            consumed_at=NOW + timedelta(seconds=2),
        )
        dispatchers = (
            Dispatcher(lifecycle, contract_registry, first_engine),
            Dispatcher(lifecycle, contract_registry, second_engine),
        )
        for dispatcher in dispatchers:
            dispatcher.bind(registration_ref, DISCOVER_CAPABILITY_ID, handler)

        def invoke(dispatcher: Dispatcher):
            return dispatcher.dispatch(request, policy=policy, authorization=receipt)

        with ThreadPoolExecutor(max_workers=2) as workers:
            outcomes = tuple(workers.map(invoke, dispatchers))
        assert sum(isinstance(outcome, DispatchSuccess) for outcome in outcomes) == 1
        assert sum(isinstance(outcome, DispatchFailure) for outcome in outcomes) == 1
        assert invoked == 1
    finally:
        second_engine.close()
        first_engine.close()


def test_quota_reservation_is_atomic_across_policy_engines(
    tmp_path: Path,
    loaded_manifest: LoadedManifest,
    contract_registry: ContractRegistry,
) -> None:
    state = tmp_path / "policy"
    state.mkdir()
    lifecycle, _, registration_ref = _runtime(loaded_manifest, contract_registry, "R1")
    target = lifecycle.inspect(DISCOVER_CAPABILITY_ID)
    policy = _policy()
    first_engine = PolicyEngine(state, contract_registry)
    try:
        requests = (
            _request(registration_ref, "cross-engine-quota-a"),
            _request(registration_ref, "cross-engine-quota-b"),
        )
        grants = tuple(
            first_engine.issue_grant(
                request,
                target,
                policy,
                _plan(first_engine, request, target),
                issued_at=NOW + timedelta(seconds=1),
                charges=(QuotaCharge("compute", 2),),
            )
            for request in requests
        )
        second_engine = PolicyEngine(state, contract_registry)
        try:
            barrier = Barrier(2)

            def consume_with(engine: PolicyEngine, index: int) -> str:
                barrier.wait()
                try:
                    engine.consume(
                        grants[index],
                        requests[index],
                        target,
                        policy,
                        consumed_at=NOW + timedelta(seconds=2),
                    )
                except PolicyError as error:
                    return error.code
                return "consumed"

            with ThreadPoolExecutor(max_workers=2) as workers:
                futures = (
                    workers.submit(consume_with, first_engine, 0),
                    workers.submit(consume_with, second_engine, 1),
                )
                results = sorted(future.result() for future in futures)
            assert results == ["consumed", "quota-denied"]
        finally:
            second_engine.close()
    finally:
        first_engine.close()


def test_v1_policy_store_migrates_once_and_closes_legacy_receipts(
    tmp_path: Path,
    loaded_manifest: LoadedManifest,
    contract_registry: ContractRegistry,
) -> None:
    state = tmp_path / "policy"
    state.mkdir()
    _create_v1_policy_store(state)
    lifecycle, _, registration_ref = _runtime(loaded_manifest, contract_registry, "R1")
    target = lifecycle.inspect(DISCOVER_CAPABILITY_ID)
    request = _request(registration_ref, "legacy")
    policy = _policy()
    consumed_at = NOW + timedelta(seconds=2)
    consumed_text = consumed_at.isoformat(timespec="microseconds").replace("+00:00", "Z")
    grant_ref = "urn:materials-mcp:grant:legacy-closed"
    plan_ref = "urn:materials-mcp:plan:legacy-closed"
    receipt_material = json.dumps(
        {"consumed_at": consumed_text, "grant_ref": grant_ref},
        separators=(",", ":"),
        sort_keys=True,
    )
    receipt_ref = (
        "urn:materials-mcp:receipt:" + hashlib.sha256(receipt_material.encode("utf-8")).hexdigest()
    )
    grant_document = {
        "request_ref": request.request_ref,
        "registration_ref": request.registration_ref,
        "capability_id": request.capability_id,
        "owner_ref": request.owner_ref,
        "input_sha256": PolicyEngine.input_sha256(request),
        "effect_tier": "R1",
        "plan_ref": plan_ref,
        "policy_sha256": policy.sha256,
        "approval_ref": None,
        "charges": [{"kind": "compute", "units": 1}],
    }
    legacy_details = {
        "charges": [{"kind": "compute", "units": 1}],
        "label": "legacy-µ",
        "plan_ref": plan_ref,
    }
    legacy_details_json = json.dumps(
        legacy_details,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    legacy_event = {
        "details": legacy_details,
        "event_type": "grant-consumed",
        "occurred_at": consumed_text,
        "owner_ref": request.owner_ref,
        "previous_sha256": "0" * 64,
        "sequence": 0,
        "subject_ref": receipt_ref,
    }
    legacy_event_sha256 = hashlib.sha256(
        json.dumps(
            legacy_event,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    database = state / PolicyEngine.DATABASE_NAME
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO grants VALUES (?, ?, ?, ?)",
            (
                grant_ref,
                json.dumps(grant_document, separators=(",", ":"), sort_keys=True),
                consumed_text,
                receipt_ref,
            ),
        )
        connection.execute(
            "INSERT INTO audit_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                request.owner_ref,
                0,
                "grant-consumed",
                receipt_ref,
                consumed_text,
                "0" * 64,
                legacy_event_sha256,
                legacy_details_json,
            ),
        )
    receipt = AuthorizationReceipt(
        receipt_ref,
        grant_ref,
        request.request_ref,
        request.registration_ref,
        request.capability_id,
        request.owner_ref,
        PolicyEngine.input_sha256(request),
        "R1",
        plan_ref,
        policy.sha256,
        consumed_at,
    )

    def open_engine(_: int) -> PolicyEngine:
        return PolicyEngine(state, contract_registry)

    with ThreadPoolExecutor(max_workers=2) as workers:
        opened = tuple(workers.map(open_engine, (0, 1)))
    for engine in opened:
        try:
            with pytest.raises(PolicyError) as closed:
                engine.verify_receipt(receipt, request, target, policy)
            assert closed.value.code == "receipt-legacy-closed"
        finally:
            engine.close()
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (2,)
        assert connection.execute(
            "SELECT receipt_state FROM grants WHERE grant_ref = ?", (grant_ref,)
        ).fetchone() == ("legacy-closed",)
        migration = connection.execute(
            "SELECT details_json FROM schema_migrations WHERE from_version = 1 AND to_version = 2"
        ).fetchone()
    assert migration is not None
    assert json.loads(migration[0])["legacy_closed_receipts"] == 1


def test_cancelled_async_dispatch_cannot_reuse_redeemed_receipt(
    tmp_path: Path,
    loaded_manifest: LoadedManifest,
    contract_registry: ContractRegistry,
) -> None:
    changed = replace(
        loaded_manifest.capabilities[0],
        effect=Effect(
            "R1",
            "bounded-local",
            "Generated cancellation boundary evidence.",
            False,
            False,
            False,
        ),
        supports_async=True,
    )
    manifest = replace(
        loaded_manifest,
        capabilities=(changed, *loaded_manifest.capabilities[1:]),
    )
    lifecycle = LifecycleRegistry()
    registration = lifecycle.register(manifest)
    lifecycle.activate(DISCOVER_CAPABILITY_ID, current_turn=0)
    target = lifecycle.inspect(DISCOVER_CAPABILITY_ID)
    request = _request(registration.registration_ref, "cancelled")
    state = tmp_path / "policy"
    state.mkdir()
    invoked = 0

    async def scenario() -> DispatchFailure:
        nonlocal invoked
        started = asyncio.Event()

        async def handler(_: HandlerRequest) -> object:
            nonlocal invoked
            invoked += 1
            started.set()
            await asyncio.Future()
            return {"cards": []}

        with PolicyEngine(
            state,
            contract_registry,
            clock=lambda: NOW + timedelta(seconds=3),
        ) as engine:
            dispatcher = Dispatcher(lifecycle, contract_registry, engine)
            dispatcher.bind(registration.registration_ref, DISCOVER_CAPABILITY_ID, handler)
            policy = _policy()
            plan = _plan(engine, request, target)
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
            task = asyncio.create_task(
                dispatcher.dispatch_async(request, policy=policy, authorization=receipt)
            )
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            replay = await dispatcher.dispatch_async(
                request,
                policy=policy,
                authorization=receipt,
            )
            assert isinstance(replay, DispatchFailure)
            return replay

    replay = asyncio.run(scenario())
    assert replay.to_document()["code"] == "AUTHORIZATION_DENIED"
    assert invoked == 1


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
    invoked = 0

    def handler(_: HandlerRequest) -> object:
        nonlocal invoked
        invoked += 1
        return {"cards": []}

    clock_time = [NOW + timedelta(seconds=2)]
    with PolicyEngine(
        state,
        contract_registry,
        clock=lambda: clock_time[0],
    ) as engine:
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
        clock_time[0] = NOW + timedelta(minutes=2)
        with pytest.raises(PolicyError) as stale_issue:
            engine.issue_grant(
                request,
                target,
                _policy(),
                plan,
                issued_at=NOW + timedelta(seconds=1),
                approval=approval,
            )
        assert stale_issue.value.code == "approval-required"
        clock_time[0] = NOW + timedelta(seconds=2)
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
        dispatcher = Dispatcher(lifecycle, contract_registry, engine)
        dispatcher.bind(registration_ref, DISCOVER_CAPABILITY_ID, handler)
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
            clock_time[0] = NOW + timedelta(minutes=2)
            with pytest.raises(RunStoreError) as expired_run:
                runs.create_run(
                    request_ref=request.request_ref,
                    target=target,
                    owner=RunOwner(OWNER_REF, "project"),
                    created_at=NOW + timedelta(minutes=2),
                    plan_ref=plan.plan_ref,
                    authorization=receipt,
                )
            assert expired_run.value.code == "authorization-denied"
            clock_time[0] = NOW + timedelta(seconds=2)
            authorized = dispatcher.dispatch(request, policy=policy, authorization=receipt)
            assert isinstance(authorized, DispatchSuccess)
            assert invoked == 1
            with pytest.raises(RunStoreError) as redeemed_run:
                runs.create_run(
                    request_ref=request.request_ref,
                    target=target,
                    owner=RunOwner(OWNER_REF, "project"),
                    created_at=NOW + timedelta(seconds=5),
                    plan_ref=plan.plan_ref,
                    authorization=receipt,
                )
            assert redeemed_run.value.code == "authorization-denied"


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
