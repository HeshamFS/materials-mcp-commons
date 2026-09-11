# M1 conformance suite

`m1-suite.json` is the machine-readable M1 acceptance boundary. It pins both exact profile indexes, enumerates every accepted positive instance and generated-negative rejection case, and declares the permitted engine dependency and import surface.

`m1-report.json` is the deterministic report produced from that suite. It contains no timestamp, machine path, network result, or environment-specific value, so the same committed inputs produce identical bytes.

Run the suite from the repository root:

```console
uv sync --locked --all-groups
uv run python -m tools.run_conformance
```

Regenerate the committed report only when an intentional, reviewed suite input changes:

```console
uv run python -m tools.run_conformance --output conformance/m1-report.json
uv run pytest tests/conformance
```

## What the coupling result means

The structural coupling audit requires an empty engine runtime-dependency set, an exact source-root allowlist, only declared standard-library import roots, exact-version-local schema references, and generic registered-extension boundaries. Schema-index digests pin the reviewed contract surface.

This result demonstrates that the current engine foundation has no imported external implementation and no external schema dependency. It is not a claim that automated text matching can understand every future architectural concept. Changes to the dependency, import, schema, or extension surface must update the suite deliberately and pass human architecture review.

The positive inputs remain real and provenance-traceable. Generated material is accepted only in the negative corpus to demonstrate rejection and fail-closed behavior.
