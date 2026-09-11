from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from materials_mcp_commons import (
    DISCOVER_CAPABILITY_ID,
    CapabilityDetail,
    ContractRegistry,
    DispatchRequest,
    LifecycleRegistry,
    LoadedManifest,
    Permission,
    PolicyEngine,
    RunOwner,
    RunStore,
    StateRecovery,
)

PUBLIC_ROOT = Path(__file__).parents[2]
OWNER_REF = "urn:materials-mcp:owner:state-recovery-evidence"


def _target(loaded_manifest: LoadedManifest) -> CapabilityDetail:
    lifecycle = LifecycleRegistry()
    lifecycle.register(loaded_manifest)
    return lifecycle.inspect(DISCOVER_CAPABILITY_ID)


def test_real_engine_state_snapshots_and_restores_to_fresh_root(
    tmp_path: Path,
    loaded_manifest: LoadedManifest,
    contract_registry: ContractRegistry,
) -> None:
    state_root = tmp_path / "live-state"
    state_root.mkdir()
    snapshot_root = tmp_path / "snapshot"
    restored_root = tmp_path / "restored-state"
    now = datetime.now(UTC)
    target = _target(loaded_manifest)
    request = DispatchRequest(
        request_ref="urn:materials-mcp:request:state-recovery-evidence",
        registration_ref=target.registration_ref,
        capability_id=target.capability.capability_id,
        owner_ref=OWNER_REF,
        current_turn=1,
        occurred_at=now,
        payload={"query": "recovery"},
    )
    recovery = StateRecovery()

    with (
        PolicyEngine(state_root, contract_registry) as policy,
        RunStore(state_root, PUBLIC_ROOT, contract_registry) as runs,
    ):
        plan = policy.create_plan(
            request,
            target,
            steps=(
                {
                    "step_id": "discover",
                    "action": "invoke",
                    "description": "Invoke the actual engine discovery control.",
                    "targets": [DISCOVER_CAPABILITY_ID],
                },
            ),
            permissions=(Permission("invoke", DISCOVER_CAPABILITY_ID),),
            expected_outputs=({"role": "result", "media_type": "application/json"},),
        )
        run = runs.create_run(
            request_ref=request.request_ref,
            target=target,
            owner=RunOwner(OWNER_REF, "project"),
            created_at=now,
            plan_ref=plan.plan_ref,
        )
        snapshot = recovery.create_snapshot(state_root, snapshot_root)
        assert [database.name for database in snapshot.databases] == [
            RunStore.DATABASE_NAME,
            PolicyEngine.DATABASE_NAME,
        ]

    inspected = recovery.inspect_snapshot(snapshot_root)
    assert inspected == snapshot
    assert recovery.restore(snapshot_root, restored_root) == snapshot

    with PolicyEngine(restored_root, contract_registry) as restored_policy:
        events = restored_policy.audit_events(OWNER_REF)
        assert len(events) == 1
        assert events[0].event_type == "plan-created"
        assert events[0].subject_ref == plan.plan_ref
    with RunStore(restored_root, PUBLIC_ROOT, contract_registry) as restored_runs:
        recovered = restored_runs.recover_incomplete(OWNER_REF)
        assert recovered == (run,)
        assert restored_runs.latest(run.run_ref, OWNER_REF) == run
