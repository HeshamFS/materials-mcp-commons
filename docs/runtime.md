# Engine runtime

Engine distribution `0.1.0a1` implements the first plugin-agnostic runtime boundary: exact profile loading, contained manifest-package validation, registration, bounded discovery, inspection, activation leases, deactivation, and unregistration.

It does not dispatch or execute a capability yet. Registering metadata never creates network, filesystem, compute, cost, or external-write authority.

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

## Evidence boundary

The checked-in positive runtime record describes only discovery and inspection behavior actually implemented by this engine. It is not a scientific backend, concrete integration, or numerical validation case. Generated runtime material exists only under the negative-test namespace and passes only when rejected or safely contained.
