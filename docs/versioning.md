# Versioning and compatibility

Materials MCP Commons versions the engine distribution and the Materials MCP Profile independently.

## Engine version

The Python distribution began at `0.1.0a0` under PEP 440. Engine `0.1.0a9` was the first frozen production-alpha API candidate; `0.1.0a10` supersedes it after independent review found open-world protocol schemas and an incomplete host-error envelope. The alpha marker communicates remaining release and scope risk; it does not lower requirements for compatibility review, scientific validity, provenance, security, reproducibility, or real-system evidence.

The exact supported Python, console, profile, and protocol surfaces are recorded in the [machine-readable API baseline](../conformance/public-api.json) and explained in the [API compatibility guide](api-compatibility.md). Engine and profile versions remain independent.

### Engine 0.1.0a9 to 0.1.0a10

Authors must update the exact engine pin and regenerate their API/conformance evidence. Embedders must stop sending unknown top-level MCP arguments, handle the complete profile structured-error envelope, and treat the frozen public error-code registry and callable awaitability as compatibility surfaces. Capability-specific nested payload semantics are unchanged. Dispatch payloads above the documented byte, depth, or node ceilings now fail before handler invocation.

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
