from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from mcp.client import Client

from materials_mcp_commons import (
    DISCOVER_CAPABILITY_ID,
    AuthorizationReceipt,
    ContractRegistry,
    Dispatcher,
    DispatchRequest,
    Effect,
    EngineMCPHost,
    HandlerRequest,
    LifecycleRegistry,
    LoadedManifest,
    Permission,
    PolicyEngine,
    PolicyError,
    PolicySnapshot,
    QuotaCharge,
    QuotaLimit,
    create_mcp_server,
)
from materials_mcp_commons.lifecycle import CapabilityDetail

NOW = datetime(2026, 9, 12, 9, 0, tzinfo=UTC)
OWNER_REF = "urn:materials-mcp:owner:generated-host-authorization"


@pytest.mark.parametrize("activation_state", ["inactive", "expired"])
def test_generated_unavailable_effect_never_reaches_authorization_resolver(
    activation_state: str,
    loaded_manifest: LoadedManifest,
    contract_registry: ContractRegistry,
) -> None:
    changed = replace(
        loaded_manifest.capabilities[0],
        effect=Effect(
            "R1",
            "bounded-local",
            "Generated effect used only to verify pre-authorization activation.",
            False,
            False,
            False,
        ),
    )
    manifest = replace(
        loaded_manifest,
        capabilities=(changed, *loaded_manifest.capabilities[1:]),
    )
    lifecycle = LifecycleRegistry()
    registration = lifecycle.register(manifest)
    if activation_state == "expired":
        lifecycle.activate(DISCOVER_CAPABILITY_ID, current_turn=0, lease_turns=1)
    dispatcher = Dispatcher(lifecycle, contract_registry)
    resolver_calls = 0
    handler_calls = 0

    def handler(_: HandlerRequest) -> object:
        nonlocal handler_calls
        handler_calls += 1
        return {"cards": []}

    def resolver(
        request: DispatchRequest, target: CapabilityDetail
    ) -> tuple[PolicySnapshot, AuthorizationReceipt]:
        del request, target
        nonlocal resolver_calls
        resolver_calls += 1
        raise AssertionError("inactive target reached authorization")

    dispatcher.bind(registration.registration_ref, DISCOVER_CAPABILITY_ID, handler)
    host = EngineMCPHost(
        lifecycle,
        dispatcher,
        owner_ref=OWNER_REF,
        authorization_resolver=resolver,
        clock=lambda: NOW,
        request_ref_factory=lambda: f"urn:materials-mcp:request:generated-host-{activation_state}",
    )

    result = asyncio.run(host.execute(registration.registration_ref, DISCOVER_CAPABILITY_ID, {}))
    error = cast(dict[str, object], result.get("error"))
    assert error["code"] == "TARGET_UNAVAILABLE"
    assert resolver_calls == 0
    assert handler_calls == 0


def test_generated_host_authorization_success_replay_and_resolver_failure_are_contained(
    tmp_path: Path,
    loaded_manifest: LoadedManifest,
    contract_registry: ContractRegistry,
) -> None:
    changed = replace(
        loaded_manifest.capabilities[0],
        effect=Effect(
            "R1",
            "bounded-local",
            "Generated effect used only to verify the host authorization boundary.",
            False,
            False,
            False,
        ),
    )
    manifest = replace(
        loaded_manifest,
        capabilities=(changed, *loaded_manifest.capabilities[1:]),
    )
    lifecycle = LifecycleRegistry()
    registration = lifecycle.register(manifest)
    lifecycle.activate(DISCOVER_CAPABILITY_ID, current_turn=0)
    state = tmp_path / "policy"
    state.mkdir()
    invoked = 0

    def handler(_: HandlerRequest) -> object:
        nonlocal invoked
        invoked += 1
        return {"cards": []}

    with PolicyEngine(state, contract_registry) as policy_engine:
        dispatcher = Dispatcher(lifecycle, contract_registry, policy_engine)
        dispatcher.bind(registration.registration_ref, DISCOVER_CAPABILITY_ID, handler)
        policy = PolicySnapshot(
            OWNER_REF,
            (Permission("invoke", DISCOVER_CAPABILITY_ID),),
            (QuotaLimit("compute", 2),),
        )
        receipt: AuthorizationReceipt | None = None

        def resolver(
            request: DispatchRequest, target: CapabilityDetail
        ) -> tuple[PolicySnapshot, AuthorizationReceipt]:
            nonlocal receipt
            if receipt is not None:
                return policy, receipt
            plan = policy_engine.create_plan(
                request,
                target,
                steps=(
                    {
                        "step_id": "execute",
                        "action": "invoke",
                        "description": "Invoke the generated host boundary target.",
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
                risks=("Generated boundary evidence must remain isolated.",),
            )
            grant = policy_engine.issue_grant(
                request,
                target,
                policy,
                plan,
                issued_at=NOW + timedelta(seconds=1),
                charges=(QuotaCharge("compute", 1),),
            )
            receipt = policy_engine.consume(
                grant,
                request,
                target,
                policy,
                consumed_at=NOW + timedelta(seconds=2),
            )
            return policy, receipt

        request_refs = iter(
            (
                "urn:materials-mcp:request:generated-host-authorized",
                "urn:materials-mcp:request:generated-host-replay",
            )
        )
        host = EngineMCPHost(
            lifecycle,
            dispatcher,
            owner_ref=OWNER_REF,
            authorization_resolver=resolver,
            clock=lambda: NOW,
            request_ref_factory=lambda: next(request_refs),
        )

        async def exercise() -> None:
            async with Client(create_mcp_server(host)) as client:
                first = await client.call_tool(
                    "materials_execute",
                    {
                        "registration_ref": registration.registration_ref,
                        "capability_id": DISCOVER_CAPABILITY_ID,
                        "payload": {},
                    },
                )
                first_document = cast(dict[str, object], first.structured_content)
                assert first_document == {"ok": True, "result": {"cards": []}}

                replay = await client.call_tool(
                    "materials_execute",
                    {
                        "registration_ref": registration.registration_ref,
                        "capability_id": DISCOVER_CAPABILITY_ID,
                        "payload": {},
                    },
                )
                replay_document = cast(dict[str, object], replay.structured_content)
                replay_error = cast(dict[str, object], replay_document["error"])
                assert replay_error["code"] == "AUTHORIZATION_DENIED"

        asyncio.run(exercise())
        assert invoked == 1

        def broken_resolver(
            request: DispatchRequest, target: CapabilityDetail
        ) -> tuple[PolicySnapshot, AuthorizationReceipt]:
            del request, target
            raise RuntimeError("private-resolver-secret")

        broken = EngineMCPHost(
            lifecycle,
            dispatcher,
            owner_ref=OWNER_REF,
            authorization_resolver=broken_resolver,
            initial_turn=2,
            clock=lambda: NOW,
            request_ref_factory=lambda: "urn:materials-mcp:request:generated-host-broken",
        )
        failed = asyncio.run(
            broken.execute(registration.registration_ref, DISCOVER_CAPABILITY_ID, {})
        )
        failed_error = cast(dict[str, object], failed.get("error"))
        assert failed_error["code"] == "AUTHORIZATION_RESOLVER_FAILED"
        assert "private-resolver-secret" not in json.dumps(failed, sort_keys=True)
        assert invoked == 1

        def denied_resolver(
            request: DispatchRequest, target: CapabilityDetail
        ) -> tuple[PolicySnapshot, AuthorizationReceipt]:
            del request, target
            raise PolicyError("quota-denied", "private-policy-reason")

        denied = EngineMCPHost(
            lifecycle,
            dispatcher,
            owner_ref=OWNER_REF,
            authorization_resolver=denied_resolver,
            initial_turn=3,
            clock=lambda: NOW,
            request_ref_factory=lambda: "urn:materials-mcp:request:generated-host-denied",
        )
        denied_result = asyncio.run(
            denied.execute(registration.registration_ref, DISCOVER_CAPABILITY_ID, {})
        )
        denied_error = cast(dict[str, object], denied_result.get("error"))
        assert denied_error["code"] == "AUTHORIZATION_DENIED"
        assert "private-policy-reason" not in json.dumps(denied_result, sort_keys=True)
