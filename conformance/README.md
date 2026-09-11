# M1 conformance suite

`m1-suite.json` and `m1-report.json` are the immutable machine-readable M1 acceptance snapshot from public commit `6a8e9b59222195321bdc0b5578a73229837438a7`. They pin both exact profile indexes, enumerate the then-accepted corpus, and record the engine dependency and import surface at the M1 gate.

`engine-suite.json` and `engine-report.json` are the current evolving engine boundary. They retain the profile and corpus checks while adding each accepted runtime surface. Reports contain no timestamp, machine path, network result, or environment-specific value, so the same committed inputs produce identical bytes.

Run the suite from the repository root:

```console
uv sync --locked --all-groups
uv run python -m tools.run_conformance
```

Regenerate only the current engine report when an intentional, reviewed suite input changes:

```console
uv run python -m tools.run_conformance --output conformance/engine-report.json
uv run pytest tests/conformance
```

Do not rewrite the M1 snapshot. Reproduce it by checking out its recorded commit.

## What the coupling result means

The structural coupling audit requires an empty engine runtime-dependency set, an exact source-root allowlist, only declared standard-library import roots, exact-version-local schema references, and generic registered-extension boundaries. Schema-index digests pin the reviewed contract surface.

This result demonstrates that the current engine foundation has no imported external implementation and no external schema dependency. It is not a claim that automated text matching can understand every future architectural concept. Changes to the dependency, import, schema, or extension surface must update the suite deliberately and pass human architecture review.

The positive inputs remain real and provenance-traceable. Generated material is accepted only in the negative corpus to demonstrate rejection and fail-closed behavior.
