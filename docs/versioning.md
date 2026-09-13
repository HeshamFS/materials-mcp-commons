# Versioning and compatibility

Materials MCP Commons versions the engine distribution and the Materials MCP Profile independently.

## Engine version

The Python distribution began at `0.1.0a0` under PEP 440. Engine `0.1.0a9` was the first frozen production-alpha API candidate. Protocol checks exposed open-world schemas and an incomplete host-error envelope, corrected in `0.1.0a10`; `0.1.0a11` completed the discriminated outputs. Version a12 added exact durable receipt binding and atomic at-most-once redemption. Integration checks then exposed inactive host calls reaching a stateful authorization resolver before dispatch rejected the missing lease. Engine `0.1.0a13` supersedes a12 by moving live exact activation ahead of resolver invocation while preserving the public API shape and error registry. The alpha marker communicates remaining release and scope risk; it does not lower requirements for compatibility review, scientific validity, provenance, security, reproducibility, or real-system evidence.

The exact supported Python, console, profile, and protocol surfaces are recorded in the [machine-readable API baseline](../conformance/public-api.json) and explained in the [API compatibility guide](api-compatibility.md). Engine and profile versions remain independent.

### Engine 0.1.0a9 to 0.1.0a10

Authors must update the exact engine pin and regenerate their API/conformance evidence. Embedders must stop sending unknown top-level MCP arguments, handle the complete profile structured-error envelope, and treat the frozen public error-code registry and callable awaitability as compatibility surfaces. Capability-specific nested payload semantics are unchanged. Dispatch payloads above the documented byte, depth, or node ceilings now fail before handler invocation.

### Engine 0.1.0a10 to 0.1.0a11

Authors must update the exact engine pin and regenerate API/conformance evidence again. MCP clients can now validate a direct two-branch output: `ok: true` requires every operation-specific success field and excludes `error`; `ok: false` requires `error` and excludes success fields. The error branch constrains codes to the public registry and carries the profile's bounds for evidence, references, stages, text, timestamps, and extensions. Impossible, incomplete, mixed, or unknown-code envelopes that the a10 advertised schema accepted are rejected by a11.

### Engine 0.1.0a11 to 0.1.0a12

Authors must update the exact engine pin and regenerate API/conformance evidence. Effectful dispatch now atomically redeems an exact durable receipt once; caller-modified receipt fields and receipt replay fail closed. `PolicyEngine.verify_receipt` remains non-redeeming while retaining denial auditing, and the additive `redeem_receipt` method is the dispatch authorization boundary. Policy database schema 2 transactionally migrates schema-1 stores and closes previously consumed receipts because their execution history cannot be proven. Recovery can create, inspect, and restore schema-1 policy snapshots and migrates them on first open. The MCP execute success envelope now permits any JSON root under `result`; Decimal and other values that cannot preserve their validated JSON type on the MCP wire are rejected with the existing structured result-schema error.

### Engine 0.1.0a12 to 0.1.0a13

Authors must update the exact engine pin and regenerate API/conformance evidence. The MCP host now resolves a live exact activation at the request turn before invoking any authorization resolver. Missing, expired, or mismatched activations still return the dispatcher's stable `TARGET_UNAVAILABLE` structured error, but can no longer reserve quota or consume a grant. Authorization that has already been consumed for a live target retains a12's at-most-once and non-refund semantics. Exported names, signatures, MCP schemas, console mappings, profile support, and policy/state formats are otherwise unchanged.

## Contract version

Contract source versions use exact Semantic Versioning directories, beginning with `schemas/0.1.0/`. Published directories are immutable and there is no `latest` alias. Engine releases declare the exact profile versions they accept and emit; support is never inferred from a mutable alias.

JSON Schema Draft 2020-12 is normative. The 0.1.0 line contains 16 root schemas whose absolute identifiers use:

`https://schemas.autonomouslab.io/materials-mcp/0.1.0/{resource-name}.schema.json`

Its `schema-index.json` pins the exact identifier, path, media type, and SHA-256 digest of every schema. Implementations resolve registered resources locally and fail closed rather than relying on implicit network retrieval. The canonical HTTPS host exists for durable distribution and human/tool discovery, not as a validation-time dependency.

After an exact-version resource or index is publicly distributed, its bytes and meaning are permanent. Corrections and additions use a new exact profile version. Branch names, mutable aliases, query strings, fragments, and local paths are not contract identifiers.

## Exact profile lines

| Profile | Classification | Instance behavior | Status |
|---|---|---|---|
| `0.1.0` | Initial minimum contracts | Exact 0.1.0 identifiers required | Published and immutable |
| `0.2.0` | Additive minor successor | Explicit migration from 0.1.0 required | Source and conformance line; publication requires a separate clean deployment gate |

Profile 0.2.0 carries fifteen scientific and control-plane schema families forward, evolves the version-specific schema index with predecessor metadata, and adds compact-result, context-manifest, and compatibility schemas.

## Compatibility classification

The 0.1.0-to-0.2.0 transition is:

- `minor` at the profile version level;
- `additive` at the resource-set level;
- `carried-contracts-preserved` at the scientific/control data-model level; and
- `migration-required` at the instance-validation level.

An unchanged 0.1.0 document is not a 0.2.0 document. Exact `contract` and `profile_version` values deliberately prevent silent cross-version validation.

For the fifteen carried scientific/control contracts, migration rewrites only the exact profile version and version-local core schema identifiers. It does not change scientific values, units, entities, conditions, artifacts, quality, provenance, citations, warnings, effects, or extension payloads. A migrated schema-index instance additionally receives the required predecessor declaration.

The executable compatibility declaration is in [`../tests/contracts/profile-0.2.0/profile-compatibility.json`](../tests/contracts/profile-0.2.0/profile-compatibility.json). The registered real migration and compact projection are documented in the [positive corpus](../tests/contracts/positive-real/cod-9013102/README.md).

Normative contract sources are distributed separately from the Python engine package so their version and CC BY 4.0 licensing remain explicit.

See [the contract guide](contracts.md) for profile semantics and [canonical schema hosting](schema-hosting.md) for distribution and integrity verification.
