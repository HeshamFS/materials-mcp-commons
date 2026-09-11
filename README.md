# Materials MCP Commons

Materials MCP Commons is an open, interoperable foundation for exposing materials-science data, simulations, workflows, and computing capabilities through the Model Context Protocol (MCP).

The project is being built around six invariants:

- a plugin-agnostic engine before any provider- or solver-specific plugin;
- real, provenance-traceable scientific data and real scientific systems;
- versioned, language-neutral contracts before backend-specific adapters;
- focused federated servers rather than one unrestricted server;
- bounded model context through progressive capability discovery and artifact references;
- evidence-backed Conformant, Verified, and Validated trust levels.

## Status

Active development. No production-alpha release has been published yet.

The first release is intended to be a research-grade production alpha with a deliberately bounded, evidence-complete capability set. Alpha denotes API and scope evolution; it does not relax scientific-validity, provenance, security, or reproducibility requirements.

## Engine-first scope

- Materials MCP Profile and conformance tooling
- Generic plugin manifest, lifecycle, dispatch boundary, and Scientist Kit
- Context Gateway minimum
- Shared artifact, structure, and durable-run services
- Generic effect, permission, plan, provenance, and policy enforcement
- Production packaging, observability, recovery, and host interoperability

The engine is implemented and gated before concrete plugins are selected or named. Later plugins are separately packaged and must not become dependencies or special cases in the engine core. The final plugin phase uses only real authorized systems and provenance-traceable data. Mocked scientific backends and fabricated scientific results are not accepted as implementation or release evidence.

## Documentation

Public documentation begins in [`docs/`](docs/README.md).

The repository now contains:

- an installable, typed Python alpha package with audited generic JSON Schema runtime dependencies;
- the immutable 0.1.0 contract line and additive 0.2.0 successor, each with a checksum-pinned resource index;
- an offline, fail-closed conformance harness;
- a deterministic multi-version conformance report and structural zero-coupling audit;
- strict offline profile/package validation and deterministic registration, discovery, inspection, and activation leases;
- exact-owner dispatch with immutable typed requests, two-sided schema validation, and contract-valid structured failures;
- deterministic operation plans, exact scoped permissions, expiring single-use approvals, atomic quotas, and tamper-evident policy audit;
- canonical context measurement with identified host tokenizers, bounded linting, real-source compact projection, retrieval evaluation, and long-session lease checks;
- deterministic empty-workspace scaffolding and exact-profile declarative package building without generated capabilities, handlers, or scientific results;
- deterministic plugin-package and versioned compatibility reports, explicit migration assessment, and manifest-derived capability references without plugin-code execution;
- durable owner-isolated run events, reconnect/cancellation, and hash-verified artifact/provenance records;
- an optional official-SDK MCP adapter with four bounded tools, trusted host-side identity/authorization injection, and real in-process/stdio protocol tests;
- metadata-only operational events, bounded health metrics, and integrity-checked non-overwriting SQLite state snapshots/restores;
- one registered real positive scientific record, its lossless successor migration and bounded compact projection, and an isolated generated-negative rejection corpus; and
- an independently deployable Cloudflare Worker boundary for the canonical schema hostname.

Start with the [runtime guide](docs/runtime.md), [production-alpha API compatibility guide](docs/api-compatibility.md), [support boundary](docs/support.md), [MCP host guide](docs/mcp-host.md), [operations runbook](docs/operations-runbook.md), [state recovery guide](docs/state-recovery.md), [threat model](docs/threat-model.md), [Scientist Kit authoring guide](docs/authoring.md), [contract guide](docs/contracts.md), [versioning policy](docs/versioning.md), [scientific evidence policy](docs/scientific-evidence.md), and [schema-hosting guide](docs/schema-hosting.md). Effectful dispatch is available only through the exact policy boundary; remote scheduling, network-host authentication, and concrete integrations are not implemented yet.

## Author and maintainer

Hesham Salama

## Licensing

Source code is licensed under the [Apache License 2.0](LICENSE). Project-authored documentation and specifications are licensed under [CC BY 4.0](LICENSE-DOCS.md). Third-party dependencies, datasets, models, and scientific systems retain their own terms.
