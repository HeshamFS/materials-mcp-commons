# Engine runtime

Engine distribution `0.1.0a3` implements the plugin-agnostic runtime boundary: exact profile loading, contained manifest-package validation, registration, bounded discovery, inspection, activation leases, exact-owner R0 dispatch, durable local run/artifact state, deactivation, and unregistration.

Registering metadata or binding a handler never creates network, filesystem, compute, cost, or external-write authority. This release executes only R0 capabilities; R1-R4 fail closed until the later planning, permission, approval, quota, and audit boundary exists.

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
        current_turn=1,
        occurred_at=datetime.now(UTC),
        payload={"query": "structure", "limit": 3},
    )
)
```

The handler sees an immutable detached request containing only identity and validated JSON data. Failures contain bounded cause, stage, evidence, retryability, corrective action, and the caller-supplied occurrence time; raw handler exceptions are withheld. Synchronous and asynchronous declarations are enforced at the dispatch entry points.

## Durable runs and artifacts

`RunStore` persists exact owner-scoped run snapshots and their complete sequence history in a fixed SQLite database beneath an explicit state root. Creation is deterministic and idempotent for one request identity. Updates require the expected sequence and non-decreasing explicit timestamps; terminal states are immutable. `deltas` supports bounded reconnect reads, `recover_incomplete` reconstructs nonterminal work after restart, and `cancel` records an explicit cancellation state without claiming remote-job termination.

Artifact registration uses a contained relative path beneath a separate explicit artifact root. The store validates provenance and artifact documents, computes size and SHA-256 from actual bytes, attaches the reference transactionally, and rechecks path containment and bytes on every retrieval. It never copies, deletes, executes, or retrieves artifact content over a network. Run creation remains limited to R0/R1 until the effect-policy runtime is implemented.

## Evidence boundary

The checked-in positive runtime record describes only discovery, inspection, and dispatch behavior actually implemented by this engine. It is not a scientific backend, concrete integration, or numerical validation case. Generated runtime material exists only under the negative-test namespace and passes only when rejected or safely contained.
