from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import cast

from mcp import StdioServerParameters
from mcp.client import Client
from mcp_types import TextContent

from materials_mcp_commons import (
    DISCOVER_CAPABILITY_ID,
    INSPECT_CAPABILITY_ID,
    ContractRegistry,
    Dispatcher,
    EngineControlHandlers,
    EngineMCPHost,
    LifecycleRegistry,
    LoadedManifest,
    OperationEvent,
    OperationObserver,
    create_mcp_server,
)

EXPECTED_TOOLS = [
    "materials_discover",
    "materials_inspect",
    "materials_activate",
    "materials_execute",
]


def _host(
    loaded_manifest: LoadedManifest,
    contract_registry: ContractRegistry,
    *,
    events: list[OperationEvent] | None = None,
) -> tuple[EngineMCPHost, str]:
    lifecycle = LifecycleRegistry()
    registration = lifecycle.register(loaded_manifest)
    controls = EngineControlHandlers(lifecycle)
    dispatcher = Dispatcher(lifecycle, contract_registry)
    dispatcher.bind(registration.registration_ref, DISCOVER_CAPABILITY_ID, controls.discover)
    dispatcher.bind(registration.registration_ref, INSPECT_CAPABILITY_ID, controls.inspect)
    observer = OperationObserver(events.append if events is not None else None)
    return (
        EngineMCPHost(
            lifecycle,
            dispatcher,
            owner_ref="urn:materials-mcp:owner:mcp-host-test",
            observer=observer,
        ),
        registration.registration_ref,
    )


def test_actual_engine_controls_work_through_in_process_mcp(
    loaded_manifest: LoadedManifest,
    contract_registry: ContractRegistry,
) -> None:
    events: list[OperationEvent] = []
    host, registration_ref = _host(loaded_manifest, contract_registry, events=events)
    server = create_mcp_server(host)

    async def exercise() -> None:
        async with Client(server) as client:
            listed = await client.list_tools()
            assert [tool.name for tool in listed.tools] == EXPECTED_TOOLS
            for tool in listed.tools:
                assert tool.input_schema["additionalProperties"] is False
                assert tool.output_schema is not None
                assert tool.output_schema["additionalProperties"] is False
            execute_tool = next(tool for tool in listed.tools if tool.name == "materials_execute")
            properties = cast(dict[str, object], execute_tool.input_schema["properties"])
            assert set(properties) == {"registration_ref", "capability_id", "payload"}
            assert "owner_ref" not in execute_tool.input_schema
            assert "authorization" not in execute_tool.input_schema

            rejected = await client.call_tool(
                "materials_discover",
                {"limit": 2, "owner_ref": "urn:materials-mcp:owner:untrusted"},
            )
            assert rejected.is_error is True
            assert rejected.structured_content is None
            assert isinstance(rejected.content[0], TextContent)
            assert "unexpected top-level arguments: owner_ref" in rejected.content[0].text

            discovery = await client.call_tool("materials_discover", {"limit": 2})
            assert discovery.is_error is False
            discovery_document = cast(dict[str, object], discovery.structured_content)
            assert discovery_document["ok"] is True
            assert len(cast(list[object], discovery_document["cards"])) == 2

            activation = await client.call_tool(
                "materials_activate", {"capability_id": DISCOVER_CAPABILITY_ID}
            )
            assert activation.is_error is False
            activation_document = cast(dict[str, object], activation.structured_content)
            assert activation_document["registration_ref"] == registration_ref

            execution = await client.call_tool(
                "materials_execute",
                {
                    "registration_ref": registration_ref,
                    "capability_id": DISCOVER_CAPABILITY_ID,
                    "payload": {"query": "inspection metadata", "limit": 1},
                },
            )
            assert execution.is_error is False
            execution_document = cast(dict[str, object], execution.structured_content)
            assert execution_document["ok"] is True
            result = cast(dict[str, object], execution_document["result"])
            cards = cast(list[dict[str, object]], result["cards"])
            assert [card["capability_id"] for card in cards] == [INSPECT_CAPABILITY_ID]

            inactive = await client.call_tool(
                "materials_execute",
                {
                    "registration_ref": registration_ref,
                    "capability_id": INSPECT_CAPABILITY_ID,
                    "payload": {"capability_id": DISCOVER_CAPABILITY_ID},
                },
            )
            inactive_document = cast(dict[str, object], inactive.structured_content)
            assert inactive_document["ok"] is False
            error = cast(dict[str, object], inactive_document["error"])
            assert error["code"] == "TARGET_UNAVAILABLE"

    asyncio.run(exercise())

    event_text = json.dumps([event.to_document() for event in events], sort_keys=True)
    assert "mcp-host-test" not in event_text
    assert "inspection metadata" not in event_text
    assert registration_ref not in event_text
    assert [event.operation for event in events] == [
        "discover",
        "activate",
        "execute",
        "execute",
    ]
    assert events[-1].error_code == "TARGET_UNAVAILABLE"
    health = host.health().to_document()
    assert health["status"] == "ready"
    assert health["registrations"] == 1
    assert health["bindings"] == 2
    assert "owner" not in json.dumps(health, sort_keys=True)


def test_host_failure_uses_exact_profile_structured_error(
    loaded_manifest: LoadedManifest,
    contract_registry: ContractRegistry,
) -> None:
    host, _ = _host(loaded_manifest, contract_registry)
    document = host.inspect("urn:materials-mcp:capability:not-registered")
    error = cast(dict[str, object], document.get("error"))
    assert document["ok"] is False
    assert error["code"] == "INSPECTION_FAILED"
    assert error["cause"]
    assert len(cast(list[object], error["evidence"])) == 1
    contract_registry.validate(cast(str, error["contract"]), error)


def test_actual_stdio_subprocess_lists_and_calls_bounded_tools() -> None:
    fixture = Path(__file__).with_name("host_fixture.py")

    async def exercise() -> None:
        parameters = StdioServerParameters(command=sys.executable, args=[str(fixture)])
        async with Client(parameters, read_timeout_seconds=15) as client:
            listed = await client.list_tools()
            assert [tool.name for tool in listed.tools] == EXPECTED_TOOLS
            result = await client.call_tool("materials_discover", {"query": "discover"})
            document = cast(dict[str, object], result.structured_content)
            assert document["ok"] is True
            cards = cast(list[dict[str, object]], document["cards"])
            assert cards[0]["capability_id"] == DISCOVER_CAPABILITY_ID

    asyncio.run(exercise())
