from __future__ import annotations

from pathlib import Path

from mcp.server.mcpserver import MCPServer

from materials_mcp_commons import (
    DISCOVER_CAPABILITY_ID,
    INSPECT_CAPABILITY_ID,
    ContractRegistry,
    Dispatcher,
    EngineControlHandlers,
    EngineMCPHost,
    LifecycleRegistry,
    ManifestLoader,
    create_mcp_server,
)


def build_server() -> MCPServer[object]:
    public_root = Path(__file__).parents[2]
    contracts = ContractRegistry.from_directory(public_root / "schemas" / "0.2.0", "0.2.0")
    manifest = ManifestLoader(contracts).load(
        public_root / "tests" / "runtime" / "positive-project" / "engine-lifecycle"
    )
    lifecycle = LifecycleRegistry()
    registration = lifecycle.register(manifest)
    controls = EngineControlHandlers(lifecycle)
    dispatcher = Dispatcher(lifecycle, contracts)
    dispatcher.bind(registration.registration_ref, DISCOVER_CAPABILITY_ID, controls.discover)
    dispatcher.bind(registration.registration_ref, INSPECT_CAPABILITY_ID, controls.inspect)
    host = EngineMCPHost(
        lifecycle,
        dispatcher,
        owner_ref="urn:materials-mcp:owner:stdio-host-fixture",
    )
    return create_mcp_server(host)


def main() -> None:
    server = build_server()
    server.run("stdio")


if __name__ == "__main__":
    main()
