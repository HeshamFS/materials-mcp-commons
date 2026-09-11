# Authoring with the Scientist Kit

The Scientist Kit separates workspace scaffolding, declarative package construction, executable handler composition, and scientific validation. These are different gates: completing one does not imply the next has passed.

## Create an empty workspace

`materials-mcp-scaffold` creates a new installable Python project at an absolute destination. The destination parent must already exist and the destination itself must not. Every identity and license value is explicit:

```console
materials-mcp-scaffold ABSOLUTE_DESTINATION \
  --distribution-name YOUR_DISTRIBUTION_NAME \
  --import-name YOUR_IMPORT_NAME \
  --display-name "YOUR DISPLAY NAME" \
  --publisher-name "YOUR PUBLISHER NAME" \
  --license-expression "YOUR SPDX EXPRESSION"
```

The scaffold contains a Python package, `schemas/` and `tests/` guidance, build metadata, and a pinned dependency on the exact engine alpha used to create it. It intentionally contains no manifest, capability, handler, backend, numerical value, result, or scientific claim.

## Author real capability contracts

Before constructing a package, define the capability's real purpose and support boundary, then author its Draft 2020-12 input, result, and error schemas. Record the effect tier and approval behavior explicitly. Positive scientific evidence must use authentic provenance-traceable sources or real systems; generated malformed and adversarial values belong only in labeled negative/security tests.

The SDK types are:

- `WorkspaceSpec` and `scaffold_workspace` for the empty project;
- `EffectSpec` and `CapabilitySpec` for explicit behavior declarations;
- `SchemaSpec` for a source schema, its package path, exact identity, and role;
- `ExtensionSpec` for an explicit registered extension boundary;
- `PluginPackageSpec` for complete publisher, rights, version, capability, schema, and extension metadata; and
- `PluginPackageBuilder` for deterministic package construction.

The builder requires a caller-supplied exact `ContractRegistry`, complete typed specification, schema source root, and fresh absolute destination. It copies schema bytes without modification, computes every resource SHA-256, emits deterministic manifest JSON, and runs the existing `ManifestLoader` against the staged package before one atomic publication step.

## What the builder will not do

The authoring layer never invents schemas, effects, units, uncertainty, provenance, capability semantics, or scientific results. It performs no network access, package installation, subprocess execution, dynamic import, handler discovery, credential access, or plugin-code execution.

A `PackageReceipt` establishes the destination, file hashes, manifest hash, declared identity, and validated immutable manifest. This is structural package evidence only. Backend interoperability, security, numerical correctness, reproducibility, and scientific trust still require their applicable real-system gates.

## Bind implementation explicitly

Keep executable handlers in the authored project and bind them through the engine's exact registration and dispatcher APIs. No manifest field names or imports executable code. Effectful execution remains subject to deterministic planning, permission, approval, quota, receipt, and audit enforcement.

The broader cross-version conformance runner, migration checks, and generated capability-reference documentation are a later authoring milestone and are not claimed by this initial SDK.
