# Engine runtime

Engine distribution `0.1.0a10` implements the plugin-agnostic runtime and Scientist Kit boundary: exact profile loading, contained manifest-package validation, registration, bounded discovery, inspection, activation leases, exact-owner dispatch, deterministic effect planning and authorization, canonical context measurement and projection, durable local run/artifact state, deterministic empty-workspace scaffolding and package construction, structural conformance reports, explicit migration assessment, manifest-derived capability references, an optional official-SDK MCP adapter, metadata-only operational signals, integrity-checked state snapshots, and a machine-checked production-alpha API baseline.

Registering metadata or binding a handler never creates network, filesystem, compute, cost, or external-write authority. R1-R4 dispatch requires a consumed grant whose receipt binds the exact owner, request, registered capability, input digest, effect tier, plan, and immutable policy snapshot. Handlers receive none of the policy state, approvals, or credentials.

## Load an exact profile and package

The caller supplies two explicit local roots:

```python
from pathlib import Path

from materials_mcp_commons import ContractRegistry, ManifestLoader

contracts = ContractRegistry.from_directory(Path("schemas/0.2.0"), "0.2.0")
manifest = ManifestLoader(contracts).load(Path("path/to/package"))
```

The profile root must contain one checksum-indexed exact version. The package root must contain `manifest.json` and every schema resource it declares. Neither loader downloads missing content.

Before returning an immutable `LoadedManifest`, the loader rejects malformed UTF-8/JSON, duplicate members, non-finite numbers, oversized documents, traversal, symlinks, digest or identifier mismatches, invalid schemas, unresolved references, incorrect capability schema roles, and undeclared extensions.

## Register and discover

```python
from materials_mcp_commons import LifecycleRegistry

catalog = LifecycleRegistry()
registration = catalog.register(manifest)
cards = catalog.discover("structure", limit=3)
detail = catalog.inspect(cards[0].capability_id)
```

Registration is idempotent only for the same identity, version, and manifest bytes. A different snapshot under an existing identity or a repeated capability identifier fails closed. Discovery searches immutable local metadata and returns at most the configured card limit in deterministic score/title/identifier order.

## Activation leases

```python
activation = catalog.activate(
    detail.capability.capability_id,
    current_turn=12,
    lease_turns=20,
)
active = catalog.active(current_turn=13)
catalog.deactivate(activation.capability_id, current_turn=14)
```

Turns are non-negative, monotonic logical values supplied by the host. Re-activation explicitly renews a lease. Expired entries are removed before a transition; a full active set evicts the earliest expiry, using capability identity as a stable tie-breaker. An active capability prevents its owning registration from being removed.

`LifecyclePolicy.from_context_manifest` derives card, activation, and lease limits from a profile 0.2.0 context manifest after that manifest has passed contract validation. Values cannot exceed the accepted profile ceilings.

## Bind and dispatch an R0 capability

Executable handlers are composed explicitly and are never imported from manifest data. A binding belongs to one exact registration and capability. Dispatch additionally requires a live activation and validates the input before invocation and the result before returning it.

```python
from datetime import UTC, datetime

from materials_mcp_commons import (
    DISCOVER_CAPABILITY_ID,
    DispatchRequest,
    Dispatcher,
    EngineControlHandlers,
)

controls = EngineControlHandlers(catalog)
dispatcher = Dispatcher(catalog, contracts)
dispatcher.bind(registration.registration_ref, DISCOVER_CAPABILITY_ID, controls.discover)
catalog.activate(DISCOVER_CAPABILITY_ID, current_turn=0)

outcome = dispatcher.dispatch(
    DispatchRequest(
        request_ref="urn:example:request:1",
        registration_ref=registration.registration_ref,
        capability_id=DISCOVER_CAPABILITY_ID,
        owner_ref="urn:example:owner:project",
        current_turn=1,
        occurred_at=datetime.now(UTC),
        payload={"query": "structure", "limit": 3},
    )
)
```

The handler sees an immutable detached request containing only identity and validated JSON data. Before copying or schema validation, dispatch limits payloads to 65,536 compact JSON bytes, depth 32, and 4,096 nodes. Failures contain bounded cause, stage, evidence, retryability, corrective action, and the caller-supplied occurrence time; raw handler and authorization-resolver exceptions are withheld. Synchronous and asynchronous declarations are enforced at the dispatch entry points.

## Plan and authorize effects

`PolicyEngine` stores immutable operation plans, approvals, grants, quota usage, and an owner-separated audit chain in a fixed SQLite database beneath an explicit existing state root. Plan identity includes the owner and exact registration plus the contract-valid plan document. The document binds the capability, declared effect, input SHA-256, ordered steps and targets, exact permissions, expected outputs, estimates, risks, and R4 recovery procedure.

Permissions reject wildcard names and scopes. R1 requires exact permissions and any declared quota but no approval. R2 and R3 require an unexpired standard-or-strong approval. R4 requires strong confirmation and recovery. An approval can authorize only one grant; a grant can be consumed only once. Consumption reserves all quota charges atomically and returns an immutable receipt. A failed replay, binding check, approval check, permission check, or quota reservation fails closed.

The dispatcher accepts effectful work only when its `PolicyEngine` verifies that exact durable receipt immediately before handler invocation. R2-R4 run creation applies the same durable receipt check. No quota is silently refunded when an authorized operation is abandoned or fails.

Audit records contain hashes and references rather than request payloads, credentials, or secrets. Each owner has a monotonic sequence and SHA-256 link to the previous event. The complete chain is verified whenever the store opens and before audit records are returned; corruption prevents further use.

## Measure and bound context

`ContextPolicy.from_manifest` validates and snapshots the exact profile 0.2.0 context declaration. `ContextGateway` serializes measured values as strict canonical JSON and reports exact UTF-8 bytes. Token measurements require both a caller-supplied host tokenizer callback and an absolute tokenizer reference; the engine never estimates tokens from characters or bytes and has no tokenizer runtime dependency.

The linter measures control tools, discovery cards, active schemas, an optional inline result, historical MCP tokens, and the total footprint against an explicit model-window size. Hard count, byte, token, fraction, intervention, and reasoning-reserve violations remain separately identifiable.

Rich-to-compact projection validates the authoritative ResultBundle first, copies only source values and references in source order, records every omission, and measures the complete contract-valid projection. If the candidate exceeds its byte or identified-token budget, whole optional entries are removed from the end; serialized JSON and scientific scalars are never byte-truncated. An irreducible envelope that cannot fit fails explicitly.

The runtime also provides deterministic retrieval and 100-turn lifecycle evaluators. The checked-in positive corpus covers only actual engine-owned discovery and inspection behavior, including no-tool cases. It does not claim scientific-domain retrieval breadth; that evidence belongs to later real plugins.

## Author without inventing a plugin

The authoring SDK creates an empty installable scientist workspace and builds a declarative plugin package only from complete caller-authored capability, effect, rights, extension, and schema specifications. Schema bytes are preserved, resource hashes are computed, manifest output is deterministic, and the staged package must pass the same exact-profile loader used at runtime before it is published to a fresh destination.

The SDK does not generate a sample capability, handler, backend, scientific result, or trust claim and does not execute plugin code. See the [Scientist Kit guide](authoring.md).

`PluginConformanceRunner` produces a path-free, timestamp-free report from the validated package snapshot and repeats registration to prove stable identity. `build_versioned_matrix` evaluates only explicit local exact-version profiles and packages, while `assess_plugin_migration` compares two separately valid caller-supplied packages without mutating either one. Capability-reference Markdown is generated solely from the validated manifest. All of these checks are declarative and code-execution-free; none establish backend, security, interoperability, or scientific validity.

## Durable runs and artifacts

`RunStore` persists exact owner-scoped run snapshots and their complete sequence history in a fixed SQLite database beneath an explicit state root. Creation is deterministic and idempotent for one request identity. Updates require the expected sequence and non-decreasing explicit timestamps; terminal states are immutable. `deltas` supports bounded reconnect reads, `recover_incomplete` reconstructs nonterminal work after restart, and `cancel` records an explicit cancellation state without claiming remote-job termination.

Artifact registration uses a contained relative path beneath a separate explicit artifact root. The store validates provenance and artifact documents, computes size and SHA-256 from actual bytes, attaches the reference transactionally, and rechecks path containment and bytes on every retrieval. It never copies, deletes, executes, or retrieves artifact content over a network. R2-R4 run records require the same exact consumed authorization receipt and preserve its plan reference.

## Evidence boundary

The checked-in positive runtime record describes only discovery, inspection, and dispatch behavior actually implemented by this engine. It is not a scientific backend, concrete integration, or numerical validation case. Generated runtime material exists only under the negative-test namespace and passes only when rejected or safely contained.
