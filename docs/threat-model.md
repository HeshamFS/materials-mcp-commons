# Engine host threat model

This production-alpha threat model covers the generic engine, its optional local MCP adapter, durable SQLite state, and package/contract boundaries. It does not certify a future concrete plugin, remote scientific service, identity provider, or network deployment.

| Threat | Control | Residual boundary |
|---|---|---|
| Model input claims another owner or supplies an approval | Owner identity and authorization resolver are constructor-side host dependencies, never tool arguments; the policy engine rechecks exact owner, request, target, input, plan, policy, and receipt bindings | The embedding application must authenticate its principal before constructing or selecting a host instance |
| Unbounded plugin tools consume host context | Four fixed control tools; registered capabilities remain cards and inspected data behind generic execution | Host-specific tool descriptions/tokenization still require measurement in the selected release hosts |
| Capability or handler substitution | Exact registration/capability ownership, activation lease, profile equality, and handler binding | The embedding application remains responsible for selecting and loading authorized package roots |
| Invalid input or result crosses the boundary | Offline exact-profile input and result validation with structured failure documents | Schema conformance is not scientific correctness |
| Handler exception leaks secrets | Raw exceptions are contained; host failures and events use stable codes and sanitized text | Private operator diagnostics, if added by an embedding application, need their own redaction/access policy |
| Effectful work bypasses approval, quota, or at-most-once execution | R1-R4 require the policy engine; every receipt field is checked against the durable grant and the receipt is atomically redeemed once before handler invocation; absent or replayed authorization fails closed | The host application must implement the real approval UX, provide a trustworthy policy clock, and protect its durable policy state |
| Telemetry leaks scientific or identity data | Metadata-only events, pseudonymous capability digest, aggregate health, no payload/result/owner/path/receipt fields | Timing and operation class remain observable to the selected sink operator |
| Stdio logs corrupt the protocol stream | The library configures no global logger and sends no telemetry to stdout; the official SDK owns the wire | Embedding code and handlers must also keep stdout clean |
| Network host accepts anonymous fixed identity | No network runner or anonymous HTTP owner mapping is provided | Streamable HTTP requires a separately accepted authenticated deployment boundary and executed security gate |
| Corrupt or substituted state is restored | Exact snapshot member set, SQLite integrity/foreign-key checks, schema versions, size limits, SHA-256, fresh-target-only restore | Snapshots are integrity manifests, not signed authenticity proofs; protect them with operator access controls |
| Snapshot loses artifact bytes | Database snapshot explicitly excludes artifact content; run retrieval rechecks artifact SHA-256 | Operators must coordinate storage-native artifact backups with state snapshots |
| Dependency compromise or drift | Protocol SDK is optional and version-bounded; exact development graph is locked; build artifacts use strict allowlists | Every release still needs refreshed vulnerability, license, and provenance checks |
| Resource exhaustion | Bounded cards, leases, schemas, dispatch payload bytes/depth/nodes, recovery sizes, and serialized host transitions | Handler CPU, memory, external cost, and HTTP limits belong to the embedding/deployment layer |

Trust labels remain separate: protocol and operational checks may support `Conformant`, but only applicable backend and scientific evidence can support `Verified` or `Validated`.
