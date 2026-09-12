from __future__ import annotations

import asyncio
from pathlib import Path
from typing import cast

from materials_mcp_commons import ContractRegistry, PolicyEngine

from materials_mcp_optimade import CAPABILITY_IDS, PROFILE_VERSION
from materials_mcp_optimade.host import build_mcp_runtime

PLUGIN_ROOT = Path(__file__).parents[1]
PUBLIC_ROOT = PLUGIN_ROOT.parents[1]
PROFILE_ROOT = PUBLIC_ROOT / "schemas" / PROFILE_VERSION


def _roots(tmp_path: Path) -> tuple[Path, Path]:
    export_root = tmp_path / "exports"
    policy_root = tmp_path / "policy"
    export_root.mkdir()
    policy_root.mkdir()
    return export_root, policy_root


def test_host_rejects_invalid_export_before_authorization_or_write(tmp_path: Path) -> None:
    contracts = ContractRegistry.from_directory(PROFILE_ROOT, PROFILE_VERSION)
    export_root, policy_root = _roots(tmp_path)
    with PolicyEngine(policy_root, contracts) as policy_engine:
        runtime = build_mcp_runtime(
            contracts,
            export_root,
            policy_engine,
            owner_ref="urn:materials-mcp:owner:host-negative-input",
        )

        async def exercise() -> dict[str, object]:
            await runtime.host.activate(CAPABILITY_IDS["records_export"])
            return cast(
                dict[str, object],
                await runtime.host.execute(
                    runtime.registration_ref,
                    CAPABILITY_IDS["records_export"],
                    {"provider_id": "nmd"},
                ),
            )

        result = asyncio.run(exercise())

    error = cast(dict[str, object], result["error"])
    assert result["ok"] is False
    assert error["code"] == "AUTHORIZATION_DENIED"
    assert list(export_root.iterdir()) == []


def test_host_r1_quota_is_durable_even_when_provider_rights_deny_write(tmp_path: Path) -> None:
    contracts = ContractRegistry.from_directory(PROFILE_ROOT, PROFILE_VERSION)
    export_root, policy_root = _roots(tmp_path)
    payload: dict[str, object] = {
        "provider_id": "mp",
        "database_id": "mp",
        "entry_type": "structures",
        "entry_id": "mp-733539",
        "format": "optimade-json",
        "destination": "must-not-exist.json",
        "overwrite": False,
    }
    with PolicyEngine(policy_root, contracts) as policy_engine:
        runtime = build_mcp_runtime(
            contracts,
            export_root,
            policy_engine,
            owner_ref="urn:materials-mcp:owner:host-quota-negative",
            export_quota=1,
        )

        async def exercise() -> tuple[dict[str, object], dict[str, object]]:
            await runtime.host.activate(CAPABILITY_IDS["records_export"])
            first = await runtime.host.execute(
                runtime.registration_ref,
                CAPABILITY_IDS["records_export"],
                payload,
            )
            second = await runtime.host.execute(
                runtime.registration_ref,
                CAPABILITY_IDS["records_export"],
                payload,
            )
            return cast(dict[str, object], first), cast(dict[str, object], second)

        first, second = asyncio.run(exercise())

    assert cast(dict[str, object], first["error"])["code"] == "HANDLER_REJECTED"
    assert cast(dict[str, object], second["error"])["code"] == "AUTHORIZATION_DENIED"
    assert not (export_root / "must-not-exist.json").exists()


def test_inactive_export_does_not_consume_the_only_quota_unit(tmp_path: Path) -> None:
    contracts = ContractRegistry.from_directory(PROFILE_ROOT, PROFILE_VERSION)
    export_root, policy_root = _roots(tmp_path)
    payload: dict[str, object] = {
        "provider_id": "mp",
        "database_id": "mp",
        "entry_type": "structures",
        "entry_id": "mp-733539",
        "format": "optimade-json",
        "destination": "must-not-exist.json",
        "overwrite": False,
    }
    with PolicyEngine(policy_root, contracts) as policy_engine:
        runtime = build_mcp_runtime(
            contracts,
            export_root,
            policy_engine,
            owner_ref="urn:materials-mcp:owner:inactive-quota-negative",
            export_quota=1,
        )

        async def exercise() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
            inactive = await runtime.host.execute(
                runtime.registration_ref,
                CAPABILITY_IDS["records_export"],
                payload,
            )
            await runtime.host.activate(CAPABILITY_IDS["records_export"])
            first_active = await runtime.host.execute(
                runtime.registration_ref,
                CAPABILITY_IDS["records_export"],
                payload,
            )
            second_active = await runtime.host.execute(
                runtime.registration_ref,
                CAPABILITY_IDS["records_export"],
                payload,
            )
            return (
                cast(dict[str, object], inactive),
                cast(dict[str, object], first_active),
                cast(dict[str, object], second_active),
            )

        inactive, first_active, second_active = asyncio.run(exercise())

    assert cast(dict[str, object], inactive["error"])["code"] == "TARGET_UNAVAILABLE"
    assert cast(dict[str, object], first_active["error"])["code"] == "HANDLER_REJECTED"
    assert cast(dict[str, object], second_active["error"])["code"] == "AUTHORIZATION_DENIED"
    assert not (export_root / "must-not-exist.json").exists()
