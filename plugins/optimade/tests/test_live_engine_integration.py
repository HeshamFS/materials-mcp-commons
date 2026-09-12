from __future__ import annotations

import asyncio
import hashlib
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from materials_mcp_commons import (
    ContractRegistry,
    Dispatcher,
    DispatchFailure,
    DispatchRequest,
    DispatchSuccess,
    EngineMCPHost,
    LifecycleRegistry,
    Permission,
    PolicyEngine,
    PolicySnapshot,
    QuotaCharge,
    QuotaLimit,
    create_mcp_server,
)
from mcp import StdioServerParameters
from mcp.client import Client

from materials_mcp_optimade import (
    CAPABILITY_IDS,
    EXPORT_PROVENANCE_SCHEMA,
    PROFILE_VERSION,
    OptimadeClient,
    OptimadeExporter,
    OptimadeHandlers,
    bind_handlers,
)
from materials_mcp_optimade.contracts import load_declarative_manifest

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("MATERIALS_MCP_LIVE") != "1",
        reason="Set MATERIALS_MCP_LIVE=1 to run fixed-provider live evidence",
    ),
]

PLUGIN_ROOT = Path(__file__).parents[1]
PUBLIC_ROOT = PLUGIN_ROOT.parents[1]
PROFILE_ROOT = PUBLIC_ROOT / "schemas" / PROFILE_VERSION
OWNER_REF = "urn:materials-mcp:owner:optimade-live-engine"
NOMAD_RECORD = "C1YUj8LENValWcMQ3Y0aUH5acDmX"


def _request(
    registration_ref: str,
    capability_id: str,
    payload: dict[str, object],
    *,
    suffix: str,
    occurred_at: datetime,
) -> DispatchRequest:
    return DispatchRequest(
        request_ref=f"urn:materials-mcp:request:optimade-{suffix}",
        registration_ref=registration_ref,
        capability_id=capability_id,
        owner_ref=OWNER_REF,
        current_turn=1,
        occurred_at=occurred_at,
        payload=payload,
    )


def _register(
    artifact_root: Path,
    policy_engine: PolicyEngine | None = None,
) -> tuple[LifecycleRegistry, Dispatcher, str]:
    contracts = ContractRegistry.from_directory(PROFILE_ROOT, PROFILE_VERSION)
    lifecycle = LifecycleRegistry()
    registration = lifecycle.register(load_declarative_manifest(PROFILE_ROOT))
    dispatcher = Dispatcher(lifecycle, contracts, policy_engine)
    handlers = OptimadeHandlers(OptimadeClient(), OptimadeExporter(artifact_root))
    assert len(bind_handlers(dispatcher, registration.registration_ref, handlers)) == 7
    return lifecycle, dispatcher, registration.registration_ref


def test_live_exact_record_dispatches_through_actual_engine_contracts(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    lifecycle, dispatcher, registration_ref = _register(tmp_path)
    capability_id = CAPABILITY_IDS["structures_get"]
    lifecycle.activate(capability_id, current_turn=0)
    request = _request(
        registration_ref,
        capability_id,
        {
            "provider_id": "nmd",
            "database_id": "nmd",
            "entry_id": NOMAD_RECORD,
            "response_fields": ["chemical_formula_reduced", "elements", "nelements"],
            "include": [],
        },
        suffix="engine-get",
        occurred_at=now,
    )

    outcome = dispatcher.dispatch(request)
    assert isinstance(outcome, DispatchSuccess)
    result = cast(dict[str, object], outcome.to_result())
    assert result["status"] == "complete"
    assert len(cast(list[object], result["entities"])) == 1


def test_live_export_requires_engine_r1_receipt_then_provider_rights(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    policy_root = tmp_path / "policy"
    artifact_root = tmp_path / "artifacts"
    policy_root.mkdir()
    artifact_root.mkdir()
    contracts = ContractRegistry.from_directory(PROFILE_ROOT, PROFILE_VERSION)
    with PolicyEngine(policy_root, contracts) as policy_engine:
        lifecycle, dispatcher, registration_ref = _register(artifact_root, policy_engine)
        capability_id = CAPABILITY_IDS["records_export"]
        lifecycle.activate(capability_id, current_turn=0)
        payload: dict[str, object] = {
            "provider_id": "nmd",
            "database_id": "nmd",
            "entry_type": "structures",
            "entry_id": NOMAD_RECORD,
            "format": "cif",
            "destination": "authorized-nomad.cif",
            "overwrite": False,
        }
        request = _request(
            registration_ref,
            capability_id,
            payload,
            suffix="authorized-export",
            occurred_at=now,
        )
        denied = dispatcher.dispatch(request)
        assert isinstance(denied, DispatchFailure)
        assert denied.to_document()["code"] == "EFFECT_POLICY_REQUIRED"
        assert not (artifact_root / "authorized-nomad.cif").exists()

        target = lifecycle.inspect(capability_id)
        destination_scope = "urn:materials-mcp:workspace-export:authorized-nomad.cif"
        permission = Permission("write", destination_scope)
        plan = policy_engine.create_plan(
            request,
            target,
            steps=(
                {
                    "step_id": "persist",
                    "action": "write",
                    "description": "Write one rights-cleared NOMAD CIF beneath the export root.",
                    "targets": [destination_scope],
                },
            ),
            permissions=(permission,),
            expected_outputs=({"role": "output", "media_type": "chemical/x-cif"},),
            estimates=(
                {
                    "kind": "storage",
                    "value": {
                        "value_type": "integer",
                        "value": 1,
                        "unit": {"system": "UCUM", "identifier": "1", "symbol": "1"},
                    },
                },
            ),
            risks=("Provider rights and source response must remain current and exact.",),
        )
        policy = PolicySnapshot(
            OWNER_REF,
            (permission,),
            (QuotaLimit("export-artifacts", 1),),
        )
        grant = policy_engine.issue_grant(
            request,
            target,
            policy,
            plan,
            issued_at=now + timedelta(seconds=1),
            charges=(QuotaCharge("export-artifacts", 1),),
        )
        receipt = policy_engine.consume(
            grant,
            request,
            target,
            policy,
            consumed_at=now + timedelta(seconds=2),
        )
        outcome = dispatcher.dispatch(request, policy=policy, authorization=receipt)
        assert isinstance(outcome, DispatchSuccess)
        artifact = cast(dict[str, object], outcome.to_result())
        content = (artifact_root / "authorized-nomad.cif").read_bytes()
        assert artifact["sha256"] == hashlib.sha256(content).hexdigest()
        extension = cast(dict[str, dict[str, object]], artifact["extensions"])[
            EXPORT_PROVENANCE_SCHEMA
        ]
        load_declarative_manifest(PROFILE_ROOT).validate(EXPORT_PROVENANCE_SCHEMA, extension)


def test_live_exact_record_executes_over_actual_mcp_wire_contract(tmp_path: Path) -> None:
    lifecycle, dispatcher, registration_ref = _register(tmp_path)
    capability_id = CAPABILITY_IDS["structures_get"]
    host = EngineMCPHost(
        lifecycle,
        dispatcher,
        owner_ref="urn:materials-mcp:owner:optimade-live-mcp",
    )
    server = create_mcp_server(host)

    async def exercise() -> None:
        async with Client(server) as mcp_client:
            activation = await mcp_client.call_tool(
                "materials_activate", {"capability_id": capability_id}
            )
            assert activation.is_error is False
            execution = await mcp_client.call_tool(
                "materials_execute",
                {
                    "registration_ref": registration_ref,
                    "capability_id": capability_id,
                    "payload": {
                        "provider_id": "nmd",
                        "database_id": "nmd",
                        "entry_id": NOMAD_RECORD,
                        "response_fields": ["chemical_formula_reduced", "nelements"],
                        "include": [],
                    },
                },
            )
            assert execution.is_error is False
            wire = cast(dict[str, object], execution.structured_content)
            assert wire["ok"] is True
            result = cast(dict[str, object], wire["result"])
            assert result["status"] == "complete"
            assert len(cast(list[object], result["entities"])) == 1

    asyncio.run(exercise())
    assert host.health().bindings == 7


def test_live_standalone_stdio_host_executes_r0_and_rights_gated_r1(tmp_path: Path) -> None:
    export_root = tmp_path / "exports"
    policy_root = tmp_path / "policy"
    export_root.mkdir()
    policy_root.mkdir()
    destination = export_root / "stdio-nomad.cif"

    async def exercise() -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "materials_mcp_optimade.host",
                "--profile-root",
                str(PROFILE_ROOT),
                "--export-root",
                str(export_root),
                "--policy-root",
                str(policy_root),
                "--export-quota",
                "1",
            ],
        )
        async with Client(parameters, read_timeout_seconds=60) as mcp_client:
            listed = await mcp_client.list_tools()
            assert [tool.name for tool in listed.tools] == [
                "materials_discover",
                "materials_inspect",
                "materials_activate",
                "materials_execute",
            ]
            inspected = await mcp_client.call_tool(
                "materials_inspect",
                {"capability_id": CAPABILITY_IDS["structures_get"]},
            )
            inspection = cast(dict[str, object], inspected.structured_content)
            assert inspection["ok"] is True
            registration_ref = cast(str, inspection["registration_ref"])

            for capability_id in (
                CAPABILITY_IDS["structures_get"],
                CAPABILITY_IDS["records_export"],
            ):
                activation = await mcp_client.call_tool(
                    "materials_activate", {"capability_id": capability_id}
                )
                assert cast(dict[str, object], activation.structured_content)["ok"] is True

            exact = await mcp_client.call_tool(
                "materials_execute",
                {
                    "registration_ref": registration_ref,
                    "capability_id": CAPABILITY_IDS["structures_get"],
                    "payload": {
                        "provider_id": "nmd",
                        "database_id": "nmd",
                        "entry_id": NOMAD_RECORD,
                        "response_fields": ["chemical_formula_reduced", "nelements"],
                        "include": [],
                    },
                },
            )
            assert cast(dict[str, object], exact.structured_content)["ok"] is True

            exported = await mcp_client.call_tool(
                "materials_execute",
                {
                    "registration_ref": registration_ref,
                    "capability_id": CAPABILITY_IDS["records_export"],
                    "payload": {
                        "provider_id": "nmd",
                        "database_id": "nmd",
                        "entry_type": "structures",
                        "entry_id": NOMAD_RECORD,
                        "format": "cif",
                        "destination": destination.name,
                        "overwrite": False,
                    },
                },
            )
            document = cast(dict[str, object], exported.structured_content)
            assert document["ok"] is True
            artifact = cast(dict[str, object], document["result"])
            assert artifact["sha256"] == hashlib.sha256(destination.read_bytes()).hexdigest()

    asyncio.run(exercise())
    assert destination.exists()
