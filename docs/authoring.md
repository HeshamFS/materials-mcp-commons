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

## Check a package and generate its reference

`PluginConformanceRunner` loads a declarative package through the same exact-profile `ManifestLoader`, verifies its schema bytes and roles, and proves deterministic registration identity. Its report is structural: it does not import or execute implementation code, contact a backend, or assign a `Verified` or `Validated` trust level.

`build_versioned_matrix` accepts explicit local `ProfileCase` and `PackageCase` values. Each package is checked only against the exact profile version declared in its manifest; there is no profile download, negotiation, or fallback. Supplied compatibility declarations are validated against their target profile and checked for exact source/target identity, complete resource partitioning, and preserved carried-contract validation semantics.

`render_capability_reference` renders Markdown solely from one validated immutable manifest. The generated reference records capability identity, effect and approval posture, asynchronous behavior, and exact input/result/error schemas without inferring usage instructions or scientific claims.

The repository's actual engine-control declarations provide reproducible structural evidence:

```console
uv run python -m tools.run_plugin_conformance package
uv run python -m tools.run_plugin_conformance matrix
uv run python -m tools.run_plugin_conformance reference
```

Pass `--output PATH` to write the deterministic bytes. The checked-in outputs are documented in [`conformance/`](../conformance/README.md).

## Assess an explicit migration candidate

`assess_plugin_migration` compares two separately valid caller-supplied packages against an explicit compatibility document and exact source/target registries. A passing assessment requires stable plugin and capability identities plus preserved manifest metadata, effects, extensions, schema-resource descriptors, and normalized validation semantics. Package versions may advance and are reported.

The assessment never edits, rewrites, or publishes either package. Authors must construct and review the target package themselves; the result does not establish backend interoperability or scientific validity.
