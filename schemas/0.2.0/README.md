# Contract line 0.2.0

This directory is the normative source for the additive successor to the immutable 0.1.0 Materials MCP Profile. It carries the original plugin-agnostic scientific and control-plane contracts forward and adds context and compact-projection contracts. It does not define or select a concrete integration.

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
| [`compact-result.schema.json`](compact-result.schema.json) | Bounded, omission-aware projection linked to an authoritative rich result |
| [`context-manifest.schema.json`](context-manifest.schema.json) | Discovery, activation, lease, result, and total-context budget declaration |
| [`profile-compatibility.schema.json`](profile-compatibility.schema.json) | Machine-validatable 0.1.0-to-0.2.0 compatibility and migration policy |
| [`schema-index.schema.json`](schema-index.schema.json) | Contract for the version resource inventory |

[`schema-index.json`](schema-index.json) is the index instance. It records the exact canonical identifier, relative path, SHA-256 digest, and media type of every normative schema resource in this directory.

## Validation invariants

- Root identifiers equal `https://schemas.autonomouslab.io/materials-mcp/0.2.0/{filename}`.
- Every reference stays inside the exact 0.2.0 canonical base and resolves from a pre-registered local registry.
- Core objects are closed. Domain-specific data enters only through explicit `extensions` maps.
- An extension key is the exact HTTPS identifier of its registered schema; its payload is validated in a second, fail-closed phase.
- Strict JSON parsing rejects duplicate member names and non-finite numbers before schema validation.
- Large or binary scientific outputs remain artifact references rather than inline model context.
- Compact output declares its rich source, selection rule, budget measurement, and every omitted count.
- Token budgets require an identified host tokenizer; deterministic byte measurements use UTF-8 JSON.
- The checksum index must match the source bytes exactly.

## Compatibility with 0.1.0

Profile 0.2.0 is an additive minor successor. Fifteen carried scientific and control-plane schema families preserve their data requirements, but exact-version instances require migration because `contract`, `profile_version`, and version-local core schema identifiers change. The schema-index contract additionally requires predecessor metadata. Scientific migration changes no value, unit, entity, condition, artifact, quality state, provenance statement, citation, warning, effect, or extension payload.

The compact result is not a competing scientific record. The linked rich 0.2.0 ResultBundle remains authoritative, and nonzero omission counts make truncation explicit.

The executable reference checks and corpus policy are documented in [`../../tests/contracts/`](../../tests/contracts/README.md). A source directory is not, by itself, a release or trust-level claim.
