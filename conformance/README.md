# Conformance evidence

`m1-suite.json` and `m1-report.json` are the immutable machine-readable M1 acceptance snapshot from public commit `6a8e9b59222195321bdc0b5578a73229837438a7`. They pin both exact profile indexes, enumerate the then-accepted corpus, and record the engine dependency and import surface at the M1 gate.

`engine-suite.json` and `engine-report.json` are the current evolving engine boundary. They retain the profile and corpus checks while adding each accepted runtime surface. Reports contain no timestamp, machine path, network result, or environment-specific value, so the same committed inputs produce identical bytes.

`context-engine-report.json` records W-0303 measurements over the actual engine control capabilities and registered real COD result. It identifies the exact verification tokenizer and model-window assumption, records canonical bytes/tokens, retrieval Recall@5, compact-result omissions, and the 100-turn activation workload. It explicitly does not claim scientific-domain retrieval breadth.

`engine-plugin-report.json` is the deterministic exact-profile declarative report for the actual engine-control package. `authoring-matrix-report.json` records the explicit 0.1.0/0.2.0 profile matrix and compatibility checks. `engine-capabilities.md` is rendered only from the validated immutable manifest. These three authoring artifacts do not execute plugin code and do not establish backend, security, interoperability, or scientific validity.

Run the suite from the repository root:

```console
uv sync --locked --all-groups
uv run python -m tools.run_conformance
uv run python -m tools.run_context_benchmark
uv run python -m tools.run_plugin_conformance package
uv run python -m tools.run_plugin_conformance matrix
uv run python -m tools.run_plugin_conformance reference
```

Regenerate only the current engine report when an intentional, reviewed suite input changes:

```console
uv run python -m tools.run_conformance --output conformance/engine-report.json
uv run python -m tools.run_plugin_conformance package --output conformance/engine-plugin-report.json
uv run python -m tools.run_plugin_conformance matrix --output conformance/authoring-matrix-report.json
uv run python -m tools.run_plugin_conformance reference --output conformance/engine-capabilities.md
uv run pytest tests/conformance
```

Do not rewrite the M1 snapshot. Reproduce it by checking out its recorded commit.

## What the coupling result means

The structural coupling audit requires the exact declared generic runtime-dependency set, an exact source-root allowlist, only declared standard-library and dependency import roots, exact-version-local schema references, and generic registered-extension boundaries. Schema-index digests pin the reviewed contract surface.

This result demonstrates that the current engine foundation has no imported external implementation and no external schema dependency. It is not a claim that automated text matching can understand every future architectural concept. Changes to the dependency, import, schema, or extension surface must update the suite deliberately and pass human architecture review.

The positive inputs remain real and provenance-traceable. Generated material is accepted only in the negative corpus to demonstrate rejection and fail-closed behavior.
