# Materials MCP Profile contracts

The Materials MCP Profile is a plugin-agnostic, language-neutral set of JSON Schema Draft 2020-12 resources. The immutable 0.1.0 line defines the minimum scientific record and control-plane boundaries. Its additive 0.2.0 successor preserves those scientific/control records and adds compact-result, context-budget, and compatibility contracts.

The normative sources are [`schemas/0.1.0/`](../schemas/0.1.0/README.md) and [`schemas/0.2.0/`](../schemas/0.2.0/README.md). Each exact line has a resource index that pins every schema by canonical identifier, relative path, media type, and SHA-256 digest.

## Contract families

- **Scientific identity and values:** entity, scientific value, scientific property, and explicit conditions.
- **Evidence and records:** artifact, citation, provenance, quality assessment, and the rich result bundle.
- **Controlled work:** effect, deterministic operation plan, durable run record, and structured error.
- **Generic extensibility:** declarative plugin manifest and exact-schema extension maps.
- **Context and projection in 0.2.0:** a bounded compact result, context budget manifest, and explicit predecessor compatibility declaration.
- **Distribution integrity:** common definitions, schema-index contract, and checksum-pinned index instance.

The rich ResultBundle is the complete scientific record. A compact model-facing result is a bounded projection of that record, not an alternative scientific source of truth.

## Compact result and context budgets

Profile 0.2.0 requires every compact result to identify its rich source record and source contract, retain bounded scientific values and evidence links, state the selection rule, declare all omitted counts, and record the applied budget measurement. Nonzero omission counts require `truncated: true`.

The context manifest bounds the always-visible control surface, discovery cards, active schemas, inline result, total MCP footprint, and lease behavior. Its baseline ceilings are four control tools, five discovery cards, eight active schemas, 500 discovery tokens, and 1,500 inline-result tokens. Token counts require the runtime host's identified tokenizer. Checked-in fixtures use exact UTF-8 byte measurement and do not pretend a byte count is a model token count.

Large arrays, trajectories, meshes, logs, and binary content remain artifact references. The compact projection never embeds them.

## Scientific-record invariants

- Numeric values require explicit units. A unit carries a system, machine identifier, and display symbol.
- Short vectors are bounded; large arrays, meshes, trajectories, logs, and binary content are represented through artifact references.
- A property identifies its subject, conditions, uncertainty state, and evidence.
- Missing uncertainty is explicit, for example `not-reported` with a reason; it is not silently interpreted as zero.
- Artifacts include stable identity, URI, media type, byte size, SHA-256, role, access scope, and provenance reference.
- Provenance records producer, activity, inputs, parameters, environment, source rights, source checksums, transformations, and citations.
- Quality records the assessment status, criteria, and limitations for the reported result.
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

1. Validate the core record against one exact supported profile root schema.
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

The higher-level [M1 conformance suite](../conformance/README.md) runs both profile lines, every declared positive and negative case, semantic budget checks, schema-index integrity, and the structural zero-coupling audit:

```console
uv run python -m tools.run_conformance
```

## Evidence boundary

The [positive corpus](../tests/contracts/positive-real/README.md) contains only registered, provenance-traceable real records. The [generated-negative corpus](../tests/contracts/negative-generated/README.md) exists only to prove rejection or safe failure. Passing fixtures provide Conformant evidence for their declared contract and provenance checks.

## Deliberately outside this implementation slice

The engine implements exact contract loading, dispatch, effect-policy enforcement, context measurement, and loss-declaring compact projection. Host compatibility and concrete integrations remain separate layers that must build on these contracts without introducing implementation-specific fields into the core.
