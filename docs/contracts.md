# Materials MCP Profile 0.1.0 contracts

The 0.1.0 contract line is a plugin-agnostic, language-neutral set of JSON Schema Draft 2020-12 resources. It defines the minimum scientific record and control-plane boundaries needed before runtime or concrete integration work can safely begin.

The normative sources are [`schemas/0.1.0/`](../schemas/0.1.0/README.md). The [resource index](../schemas/0.1.0/schema-index.json) pins every schema by canonical identifier, relative path, media type, and SHA-256 digest.

## Contract families

- **Scientific identity and values:** entity, scientific value, scientific property, and explicit conditions.
- **Evidence and records:** artifact, citation, provenance, quality assessment, and the rich result bundle.
- **Controlled work:** effect, deterministic operation plan, durable run record, and structured error.
- **Generic extensibility:** declarative plugin manifest and exact-schema extension maps.
- **Distribution integrity:** common definitions, schema-index contract, and checksum-pinned index instance.

The rich ResultBundle is the complete scientific record. Future compact model-facing output is a bounded projection of that record, not an alternative scientific source of truth.

## Scientific-record invariants

- Numeric values require explicit units. A unit carries a system, machine identifier, and display symbol.
- Short vectors are bounded; large arrays, meshes, trajectories, logs, and binary content are represented through artifact references.
- A property identifies its subject, conditions, uncertainty state, and evidence.
- Missing uncertainty is explicit, for example `not-reported` with a reason; it is not silently interpreted as zero.
- Artifacts include stable identity, URI, media type, byte size, SHA-256, role, access scope, and provenance reference.
- Provenance records producer, activity, inputs, parameters, environment, source rights, source checksums, transformations, and citations.
- Quality is an explicit assessment with criteria and limitations. Schema-valid does not mean scientifically Validated.
- Structured failures include cause, stage, evidence, retryability, and a corrective next action.

## Effect policy

The effect contract fixes the following posture:

| Tier | Category | Plan | Approval | Strong confirmation |
|---|---|---:|---:|---:|
| R0 | Read-only | No | No | No |
| R1 | Bounded local | No | No | No |
| R2 | Compute or cost | Yes | Yes | No |
| R3 | External write | Yes | Yes | No |
| R4 | Destructive | Yes | Yes | Yes |

An effectful run cannot weaken these booleans. R2-R4 plans expose deterministic steps, targets, permissions, expected outputs, estimates, risks, and recovery information where required.

## Closed core and registered extensions

Core records reject undeclared fields. Domain-specific additions use an explicit `extensions` object whose keys are exact HTTPS identifiers for registered extension schemas.

Validation has two fail-closed phases:

1. Validate the core record against an exact 0.1.0 root schema.
2. Resolve each extension key from the caller's pre-registered schema registry and validate its payload.

An unknown extension, a core schema misused as an extension, or an invalid extension payload fails validation. The validator does not retrieve missing schemas from the network.

## Deterministic validation

The reference checks:

1. decode UTF-8 JSON strictly, rejecting duplicate object members and non-finite numbers;
2. verify the exact Draft 2020-12 dialect and path-derived root identifier;
3. meta-validate every schema and reject unknown schema keywords;
4. resolve every `$ref` from the exact local registry with implicit retrieval disabled;
5. validate the core instance and all registered extensions; and
6. verify that the schema index matches every source byte.

Run the executable contract suite with:

```console
uv sync --locked --all-groups
uv run pytest tests/contracts
```

## Evidence boundary

The [positive corpus](../tests/contracts/positive-real/README.md) contains only registered, provenance-traceable real records. The [generated-negative corpus](../tests/contracts/negative-generated/README.md) exists only to prove rejection or safe failure. A fixture that passes these contracts is Conformant evidence for the tested boundary; it is not, by itself, runtime verification or independent scientific validation.

## Deliberately outside this implementation slice

This contract set does not yet implement runtime loading or dispatch, context-card and compact-projection behavior, host compatibility, or any concrete integration. Those layers must build on these contracts without introducing backend-specific fields into the core.
