from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from materials_mcp_commons import (
    DISCOVER_CAPABILITY_ID,
    CapabilityDetail,
    ContractRegistry,
    Effect,
    LifecycleRegistry,
    LoadedManifest,
    RunOwner,
    RunStore,
    RunStoreError,
)

PUBLIC_ROOT = Path(__file__).parents[3]
NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)
OWNER = RunOwner("urn:materials-mcp:owner:negative-one", "project")
OTHER = RunOwner("urn:materials-mcp:owner:negative-two", "project")


def _target(manifest: LoadedManifest) -> CapabilityDetail:
    lifecycle = LifecycleRegistry()
    lifecycle.register(manifest)
    return lifecycle.inspect(DISCOVER_CAPABILITY_ID)


def _store(tmp_path: Path, contracts: ContractRegistry) -> RunStore:
    state = tmp_path / "state"
    artifacts = tmp_path / "artifacts"
    state.mkdir(parents=True)
    artifacts.mkdir(parents=True)
    return RunStore(state, artifacts, contracts)


def _provenance(run_ref: str, source: Path) -> dict[str, object]:
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    source_ref = f"urn:materials-mcp:negative-source:{digest}"
    return {
        "provenance_ref": f"urn:materials-mcp:negative-provenance:{digest}",
        "activity_ref": run_ref,
        "activity_type": "analysis",
        "started_at": "2026-09-11T12:00:00Z",
        "ended_at": "2026-09-11T12:01:00Z",
        "producer": {
            "producer_ref": "urn:materials-mcp:producer:negative-boundary",
            "name": "Generated negative boundary producer",
            "version": "1",
        },
        "inputs": [source_ref],
        "parameters": [],
        "environment": {"status": "not-applicable", "reason": "Negative boundary case."},
        "sources": [
            {
                "source_ref": source_ref,
                "source_type": "other",
                "title": "Generated negative boundary source",
                "uri": source_ref,
                "version": digest,
                "retrieved_at": "2026-09-11T12:00:00Z",
                "rights": {
                    "basis": "license",
                    "identifier": "CC0-1.0",
                    "uri": "https://creativecommons.org/publicdomain/zero/1.0/",
                    "redistribution": "permitted",
                    "attribution": "Generated negative test only",
                },
                "size_bytes": source.stat().st_size,
                "sha256": digest,
                "transformations": [
                    {"operation": "other", "source_locator": "negative", "target_pointer": ""}
                ],
                "citation_refs": ["urn:materials-mcp:citation:negative"],
            }
        ],
    }


def test_generated_owner_sequence_time_and_terminal_boundaries_fail_closed(
    tmp_path: Path,
    loaded_manifest: LoadedManifest,
    contract_registry: ContractRegistry,
) -> None:
    with _store(tmp_path, contract_registry) as store:
        created = store.create_run(
            request_ref="urn:materials-mcp:negative-request:lifecycle",
            target=_target(loaded_manifest),
            owner=OWNER,
            created_at=NOW,
        )
        with pytest.raises(RunStoreError) as owner_failure:
            store.latest(created.run_ref, OTHER.owner_ref)
        assert owner_failure.value.code == "run-not-found"
        running = store.transition(
            created.run_ref,
            OWNER.owner_ref,
            expected_sequence=0,
            state="running",
            updated_at=NOW + timedelta(seconds=1),
        )
        with pytest.raises(RunStoreError) as sequence:
            store.transition(
                created.run_ref,
                OWNER.owner_ref,
                expected_sequence=0,
                state="running",
                updated_at=NOW + timedelta(seconds=2),
            )
        assert sequence.value.code == "sequence-conflict"
        with pytest.raises(RunStoreError) as time_failure:
            store.transition(
                created.run_ref,
                OWNER.owner_ref,
                expected_sequence=running.sequence,
                state="running",
                updated_at=NOW,
            )
        assert time_failure.value.code == "time-regression"
        with pytest.raises(RunStoreError) as missing_result:
            store.transition(
                created.run_ref,
                OWNER.owner_ref,
                expected_sequence=running.sequence,
                state="succeeded",
                updated_at=NOW + timedelta(seconds=2),
            )
        assert missing_result.value.code == "missing-result"
        with pytest.raises(RunStoreError) as missing_error:
            store.transition(
                created.run_ref,
                OWNER.owner_ref,
                expected_sequence=running.sequence,
                state="failed",
                updated_at=NOW + timedelta(seconds=2),
            )
        assert missing_error.value.code == "missing-error"
        cancelled = store.cancel(
            created.run_ref,
            OWNER.owner_ref,
            expected_sequence=running.sequence,
            updated_at=NOW + timedelta(seconds=2),
        )
        with pytest.raises(RunStoreError) as terminal:
            store.transition(
                created.run_ref,
                OWNER.owner_ref,
                expected_sequence=cancelled.sequence,
                state="running",
                updated_at=NOW + timedelta(seconds=3),
            )
        assert terminal.value.code == "terminal-run"


def test_generated_request_conflict_and_effect_policy_fail_closed(
    tmp_path: Path,
    loaded_manifest: LoadedManifest,
    contract_registry: ContractRegistry,
) -> None:
    with _store(tmp_path, contract_registry) as store:
        store.create_run(
            request_ref="urn:materials-mcp:negative-request:conflict",
            target=_target(loaded_manifest),
            owner=OWNER,
            created_at=NOW,
        )
        with pytest.raises(RunStoreError) as conflict:
            store.create_run(
                request_ref="urn:materials-mcp:negative-request:conflict",
                target=_target(loaded_manifest),
                owner=OTHER,
                created_at=NOW,
            )
        assert conflict.value.code == "request-conflict"
        capability = loaded_manifest.capabilities[0]
        effectful = replace(
            capability,
            effect=Effect("R2", "compute-or-cost", "Negative boundary.", True, True, False),
        )
        detail = replace(_target(loaded_manifest), capability=effectful)
        with pytest.raises(RunStoreError) as policy:
            store.create_run(
                request_ref="urn:materials-mcp:negative-request:effect",
                target=detail,
                owner=OWNER,
                created_at=NOW,
            )
        assert policy.value.code == "effect-policy-required"


def test_generated_artifact_traversal_drift_and_owner_access_fail_closed(
    tmp_path: Path,
    loaded_manifest: LoadedManifest,
    contract_registry: ContractRegistry,
) -> None:
    source = tmp_path / "source.json"
    source.write_text(json.dumps({"negative": True}), encoding="utf-8")
    with _store(tmp_path / "store", contract_registry) as store:
        created = store.create_run(
            request_ref="urn:materials-mcp:negative-request:artifact",
            target=_target(loaded_manifest),
            owner=OWNER,
            created_at=NOW,
        )
        running = store.transition(
            created.run_ref,
            OWNER.owner_ref,
            expected_sequence=0,
            state="running",
            updated_at=NOW + timedelta(seconds=1),
        )
        with pytest.raises(RunStoreError) as traversal:
            store.attach_artifact(
                created.run_ref,
                OWNER.owner_ref,
                expected_sequence=running.sequence,
                updated_at=NOW + timedelta(seconds=2),
                relative_path="../source.json",
                uri="urn:materials-mcp:negative-artifact:traversal",
                media_type="application/json",
                role="diagnostic",
                access_scope="workspace",
                provenance=_provenance(created.run_ref, source),
            )
        assert traversal.value.code == "unsafe-artifact-path"
        artifact_file = tmp_path / "store" / "artifacts" / "negative.json"
        shutil.copyfile(source, artifact_file)
        with pytest.raises(RunStoreError) as provenance_owner:
            store.attach_artifact(
                created.run_ref,
                OWNER.owner_ref,
                expected_sequence=running.sequence,
                updated_at=NOW + timedelta(seconds=2),
                relative_path="negative.json",
                uri="urn:materials-mcp:negative-artifact:provenance-owner",
                media_type="application/json",
                role="diagnostic",
                access_scope="workspace",
                provenance=_provenance("urn:materials-mcp:run:wrong", source),
            )
        assert provenance_owner.value.code == "provenance-ownership"
        attached = store.attach_artifact(
            created.run_ref,
            OWNER.owner_ref,
            expected_sequence=running.sequence,
            updated_at=NOW + timedelta(seconds=2),
            relative_path="negative.json",
            uri="urn:materials-mcp:negative-artifact:drift",
            media_type="application/json",
            role="diagnostic",
            access_scope="workspace",
            provenance=_provenance(created.run_ref, source),
        )
        with pytest.raises(RunStoreError) as hidden:
            store.artifact(attached.artifact.artifact_ref, OTHER.owner_ref)
        assert hidden.value.code == "artifact-not-found"
        artifact_file.write_text("changed", encoding="utf-8")
        with pytest.raises(RunStoreError) as drift:
            store.artifact(attached.artifact.artifact_ref, OWNER.owner_ref)
        assert drift.value.code == "artifact-integrity"


def test_generated_symlinked_artifact_and_incompatible_store_are_rejected(
    tmp_path: Path,
    loaded_manifest: LoadedManifest,
    contract_registry: ContractRegistry,
) -> None:
    state = tmp_path / "state"
    artifacts = tmp_path / "artifacts"
    state.mkdir()
    artifacts.mkdir()
    database = state / RunStore.DATABASE_NAME
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA user_version = 99")
    connection.close()
    with pytest.raises(RunStoreError) as version:
        RunStore(state, artifacts, contract_registry)
    assert version.value.code == "store-version-incompatible"

    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    link = artifacts / "linked.json"
    try:
        os.symlink(target, link)
    except OSError as error:
        pytest.skip(f"File symlink creation unavailable: {error.winerror}")
    state_two = tmp_path / "state-two"
    state_two.mkdir()
    with RunStore(state_two, artifacts, contract_registry) as store:
        created = store.create_run(
            request_ref="urn:materials-mcp:negative-request:symlink",
            target=_target(loaded_manifest),
            owner=OWNER,
            created_at=NOW,
        )
        running = store.transition(
            created.run_ref,
            OWNER.owner_ref,
            expected_sequence=0,
            state="running",
            updated_at=NOW + timedelta(seconds=1),
        )
        with pytest.raises(RunStoreError) as symlink:
            store.attach_artifact(
                created.run_ref,
                OWNER.owner_ref,
                expected_sequence=running.sequence,
                updated_at=NOW + timedelta(seconds=2),
                relative_path="linked.json",
                uri="urn:materials-mcp:negative-artifact:symlink",
                media_type="application/json",
                role="diagnostic",
                access_scope="workspace",
                provenance=_provenance(created.run_ref, target),
            )
        assert symlink.value.code == "unsafe-artifact-path"
