# Contract line 0.1.0

This directory is the normative source for the first Materials MCP Profile contract line. It defines plugin-agnostic scientific records and control-plane envelopes; it does not define or select a concrete integration.

## Resource inventory

| Resource | Purpose |
|---|---|
| [`common.schema.json`](common.schema.json) | Shared bounded identifiers, strings, timestamps, versions, digests, and primitive definitions |
| [`extension.schema.json`](extension.schema.json) | Additive payload map keyed by exact registered extension-schema identifiers |
| [`entity.schema.json`](entity.schema.json) | Stable typed scientific subjects and external identifiers |
| [`scientific-value.schema.json`](scientific-value.schema.json) | Bounded scalar, short-vector, text, or artifact-backed values with mandatory units for numeric values |
| [`scientific-property.schema.json`](scientific-property.schema.json) | Subject-linked values with conditions, uncertainty state, and evidence references |
| [`artifact.schema.json`](artifact.schema.json) | Typed, checksummed references to scientific content kept outside model context |
| [`quality-assessment.schema.json`](quality-assessment.schema.json) | Explicit assessment state, criteria, evidence, and limitations without an implicit trust claim |
| [`citation.schema.json`](citation.schema.json) | Bounded bibliographic references |
| [`provenance.schema.json`](provenance.schema.json) | Sources, rights, checksums, transformations, producer, parameters, and execution context |
| [`effect.schema.json`](effect.schema.json) | R0-R4 effect classification and required planning/approval posture |
| [`operation-plan.schema.json`](operation-plan.schema.json) | Deterministic steps, targets, permissions, approvals, outputs, estimates, risks, and recovery |
| [`run-record.schema.json`](run-record.schema.json) | Durable, reconnectable run identity and state |
| [`structured-error.schema.json`](structured-error.schema.json) | Cause, stage, evidence, retryability, and corrective next action |
| [`result-bundle.schema.json`](result-bundle.schema.json) | Complete scientific result record from which bounded projections are derived |
| [`plugin-manifest.schema.json`](plugin-manifest.schema.json) | Declarative generic plugin identity, capabilities, contracts, effects, and extension resources |
| [`schema-index.schema.json`](schema-index.schema.json) | Contract for the version resource inventory |

[`schema-index.json`](schema-index.json) is the index instance. It records the exact canonical identifier, relative path, SHA-256 digest, and media type of every normative schema resource in this directory.

## Validation invariants

- Root identifiers equal `https://schemas.autonomouslab.io/materials-mcp/0.1.0/{filename}`.
- Every reference stays inside the exact 0.1.0 canonical base and resolves from a pre-registered local registry.
- Core objects are closed. Domain-specific data enters only through explicit `extensions` maps.
- An extension key is the exact HTTPS identifier of its registered schema; its payload is validated in a second, fail-closed phase.
- Strict JSON parsing rejects duplicate member names and non-finite numbers before schema validation.
- Large or binary scientific outputs remain artifact references rather than inline model context.
- The checksum index must match the source bytes exactly.

The executable reference checks and corpus policy are documented in [`../../tests/contracts/`](../../tests/contracts/README.md). A source directory is not, by itself, a release or trust-level claim.
