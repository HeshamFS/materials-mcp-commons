from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from materials_mcp_commons import (
    ContractRegistry,
    PolicyEngine,
    RunStore,
    StateRecovery,
    StateRecoveryError,
)


def _snapshot(tmp_path: Path, contract_registry: ContractRegistry) -> tuple[StateRecovery, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    state_root = tmp_path / "generated-state"
    state_root.mkdir()
    with (
        PolicyEngine(state_root, contract_registry),
        RunStore(state_root, tmp_path, contract_registry),
    ):
        pass
    recovery = StateRecovery()
    snapshot_root = tmp_path / "generated-snapshot"
    recovery.create_snapshot(state_root, snapshot_root)
    return recovery, snapshot_root


def test_generated_partial_and_extra_snapshot_sets_are_rejected(
    tmp_path: Path,
    contract_registry: ContractRegistry,
) -> None:
    recovery, snapshot_root = _snapshot(tmp_path, contract_registry)
    (snapshot_root / PolicyEngine.DATABASE_NAME).unlink()
    with pytest.raises(StateRecoveryError) as partial:
        recovery.inspect_snapshot(snapshot_root)
    assert partial.value.code == "snapshot-rejected"

    recovery, snapshot_root = _snapshot(tmp_path / "extra-case", contract_registry)
    (snapshot_root / "unexpected.txt").write_text("generated boundary", encoding="utf-8")
    with pytest.raises(StateRecoveryError) as extra:
        recovery.inspect_snapshot(snapshot_root)
    assert extra.value.code == "snapshot-rejected"


def test_generated_corruption_and_store_version_are_rejected(
    tmp_path: Path,
    contract_registry: ContractRegistry,
) -> None:
    recovery, snapshot_root = _snapshot(tmp_path, contract_registry)
    database = snapshot_root / RunStore.DATABASE_NAME
    database.write_bytes(b"generated-corrupt-sqlite")
    with pytest.raises(StateRecoveryError) as corrupt:
        recovery.inspect_snapshot(snapshot_root)
    assert corrupt.value.code == "database-integrity-failed"

    version_case = tmp_path / "version-case"
    version_case.mkdir()
    recovery, snapshot_root = _snapshot(version_case, contract_registry)
    database = snapshot_root / PolicyEngine.DATABASE_NAME
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA user_version = 999")
    with pytest.raises(StateRecoveryError) as incompatible:
        recovery.inspect_snapshot(snapshot_root)
    assert incompatible.value.code == "store-version-incompatible"


def test_generated_restore_never_overwrites_existing_target(
    tmp_path: Path,
    contract_registry: ContractRegistry,
) -> None:
    recovery, snapshot_root = _snapshot(tmp_path, contract_registry)
    target = tmp_path / "existing-target"
    target.mkdir()
    marker = target / "preserve.txt"
    marker.write_text("preserve", encoding="utf-8")

    with pytest.raises(StateRecoveryError) as existing:
        recovery.restore(snapshot_root, target)
    assert existing.value.code == "restore-exists"
    assert marker.read_text(encoding="utf-8") == "preserve"
