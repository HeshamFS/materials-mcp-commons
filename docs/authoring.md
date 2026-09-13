# Authoring with the Scientist Kit

The Scientist Kit supports workspace scaffolding, declarative package construction, executable handler composition, and scientific reference checks. Each stage records its own results.

## Create an empty workspace

`materials-mcp-scaffold` creates a new installable Python project at an absolute destination. The destination parent must already exist and the destination itself must not. Every identity and license value is explicit:

```console
materials-mcp-scaffold ABSOLUTE_DESTINATION --distribution-name YOUR_DISTRIBUTION_NAME --import-name YOUR_IMPORT_NAME --display-name "YOUR DISPLAY NAME" --publisher-name "YOUR PUBLISHER NAME" --license-expression "YOUR SPDX EXPRESSION"
```

The single-line form works in PowerShell and POSIX shells. The scaffold contains a Python package, `schemas/` and `tests/` guidance, build metadata, and a pinned dependency on the exact engine alpha used to create it. It intentionally contains no manifest, capability, handler, backend, numerical value, result, or scientific claim. Before distributing the authored package, add the license text corresponding to the chosen SPDX expression and verify rights for every bundled resource.

The engine alpha is not published yet, so an ordinary registry-backed `uv sync` in a generated workspace is expected to fail. For current source-checkout evaluation, first build the engine wheel from this public tree and install both projects without asking the registry to resolve the unpublished pin:

```console
uv build --wheel --out-dir ABSOLUTE_ENGINE_DIST
uv venv ABSOLUTE_AUTHORING_VENV --python 3.12
uv pip install --python ABSOLUTE_AUTHORING_PYTHON ABSOLUTE_ENGINE_WHEEL
uv pip install --python ABSOLUTE_AUTHORING_PYTHON --no-deps -e ABSOLUTE_AUTHORED_WORKSPACE
uv pip check --python ABSOLUTE_AUTHORING_PYTHON
```

Use the Python executable inside `ABSOLUTE_AUTHORING_VENV` for `ABSOLUTE_AUTHORING_PYTHON`. After an engine distribution is published, the exact pin becomes normally resolvable and this source-checkout procedure is no longer needed.

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

The executable [`tools/build_engine_control_package.py`](../tools/build_engine_control_package.py) is the end-to-end reference for constructing every typed object and invoking `PluginPackageBuilder`. It rebuilds the repository's actual engine-control declarations from their authored manifest and schema bytes; it does not generate domain semantics. Run it only with a fresh destination:

```console
uv run python -m tools.build_engine_control_package ABSOLUTE_FRESH_DESTINATION
```

For a new package, replace that reference's manifest-derived construction with reviewed, explicitly authored `PluginPackageSpec`, `CapabilitySpec`, `EffectSpec`, `SchemaSpec`, and `ExtensionSpec` values. Never infer them from a backend response or model output.

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

An installed engine also exposes package conformance directly. Exact profile files are intentionally not bundled in the wheel; obtain them from this source tree or the canonical immutable schema host, pin the exact version, and retain their index digests with the review evidence:

```console
materials-mcp-conformance --profile-root ABSOLUTE_PROFILE_DIRECTORY --profile-version 0.2.0 --package ABSOLUTE_DECLARATIVE_PACKAGE --output ABSOLUTE_REPORT_PATH
```

The command exits `0` only for a conforming package and `2` with a typed code for a rejected profile, package, or output path. It never loads package code or contacts a backend.

## Assess an explicit migration candidate

`assess_plugin_migration` compares two separately valid caller-supplied packages against an explicit compatibility document and exact source/target registries. A passing assessment requires stable plugin and capability identities plus preserved manifest metadata, effects, extensions, schema-resource descriptors, and normalized validation semantics. Package versions may advance and are reported.

The assessment never edits, rewrites, or publishes either package. Authors construct the target package and use the report to check preserved declarations and schema semantics.
