# MCP host adapter

The engine's MCP adapter is optional. Install `materials-mcp-commons[mcp-host]` to compose an MCP server with the official Python SDK v2; the base package remains usable for contracts, authoring, conformance, lifecycle, policy, runs, and direct embedding without a protocol stack.

The adapter is an explicit composition boundary. An embedding application constructs and validates its contract registry, loads only packages it has selected, registers them, binds handlers, and then passes its `LifecycleRegistry` and `Dispatcher` to `EngineMCPHost`. The adapter does not scan entry points, import plugin code, download profiles, choose a package, or create a policy engine.

## Bounded tool surface

`create_mcp_server(host)` exposes exactly four tools:

| Tool | Role |
|---|---|
| `materials_discover` | Return a bounded set of compact cards from already registered capabilities |
| `materials_inspect` | Return the exact registered capability, schema, effect, and implementation identity |
| `materials_activate` | Create or renew one logical-turn capability lease |
| `materials_execute` | Dispatch one exact active registration/capability pair through input, policy, handler, and output checks |

Registered plugin capabilities remain data behind discovery and the generic execute tool. Adding packages therefore does not expand the always-visible MCP tool list.

The host serializes activation and execution transitions so concurrent protocol requests cannot present decreasing logical turns to the lifecycle registry. This initial production-alpha boundary favors deterministic lease and authorization behavior over parallel handler throughput.

## Identity and authorization

`owner_ref` is trusted host configuration. It is not an MCP tool argument. All four top-level tool schemas are closed and the host rejects unknown top-level arguments rather than allowing the SDK to ignore them. Tool arguments also cannot supply a policy snapshot, approval, grant, receipt, state path, transport setting, or telemetry sink. Only the capability-specific nested `payload` remains open for validation by its exact declared schema.

All host and dispatcher failures use the exact profile structured-error envelope with cause, stage, evidence, retryability, corrective next action, and occurrence time. The stable public code inventory is frozen in `conformance/public-api.json`; raw resolver, handler, and internal exception text is never returned.

R0 execution uses the normal dispatcher without authorization material. For R1-R4, the embedding application may provide an `AuthorizationResolver`. The resolver receives the immutable exact dispatch request and inspected target, and must return the policy snapshot and already-consumed authorization receipt for that request. The dispatcher performs the final exact binding check. A missing, rejected, or failing resolver produces a sanitized failure before the handler is invoked.

## Supported transport boundary

The checked host evidence uses the official SDK client both in process and through a real stdio subprocess. Stdio is the supported local subprocess transport for this slice. The library does not configure global logging and operational event sinks never write to protocol stdout.

The SDK can create a Streamable HTTP ASGI application, but Materials MCP Commons does not yet declare an HTTP deployment supported. A network host requires an application-specific authenticated-principal resolver, explicit SDK transport-security allowlists, TLS/reverse-proxy controls, body/time/resource limits, and an executed host-environment gate. Never expose a fixed local `owner_ref` to anonymous network callers.

## Operational signals

`OperationObserver` records four bounded operation classes and success/failure counters. Each event can include an effect tier, stable error code, duration, and SHA-256 of a capability reference. It never includes payloads, results, owner identity, full request/run references, authorization documents, local paths, or raw exception text. Sink failures are contained and counted in `dropped_sink_events`; they do not change the tool result.

`host.health()` is an in-process diagnostic containing status, exact dispatcher profile, registration count, binding count, and aggregate metrics. It is not registered as an MCP tool or unauthenticated HTTP route.

See the [operations runbook](operations-runbook.md), [state recovery guide](state-recovery.md), and [threat model](threat-model.md) before hosting the adapter.
