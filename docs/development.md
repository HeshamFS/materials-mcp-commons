# Development foundation

The engine uses a minimal Python package foundation. Its only current runtime dependencies are `jsonschema` and `referencing`, used for Draft 2020-12 validation and an explicit offline registry. Python 3.11 is the syntax and static-analysis floor; the supported initial line is Python 3.11 through 3.14.

## Python and contract checks

With [uv](https://docs.astral.sh/uv/) installed:

```console
uv lock --check
uv sync --locked --all-groups
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv build --no-sources
```

The complete test run includes both exact profile lines, the frozen-0.1.0 publication check, offline reference resolution, successor migration, compact/context budgets, real-positive corpus integrity, and generated-negative rejection cases. To run only that boundary:

```console
uv run pytest tests/contracts
```

The deterministic current-engine conformance runner evaluates the declared multi-version corpus and structural coupling boundary in one command:

```console
uv run python -m tools.run_conformance
```

Its current and frozen milestone suites and committed reproducible reports are documented in [`conformance/`](../conformance/README.md). The runner is public development tooling; it is intentionally outside the installed engine distribution.

The committed `uv.lock` controls development and verification dependencies. uv is not a runtime requirement of the installed engine package.

## Authoring checks

The installed `materials-mcp-scaffold` command creates a fresh empty scientist workspace from explicit metadata. The typed `PluginPackageBuilder` then constructs a checksum-bound declarative package from complete authored schemas and validates it with the runtime loader. See the [Scientist Kit guide](authoring.md).

The test suite reconstructs the actual engine-control package twice and compares every output byte. Generated malformed authoring inputs are isolated under `tests/runtime/negative_generated/`; they are boundary/security evidence, not scientific examples.

## Schema-host checks

The canonical-host deployment has an independent Node.js toolchain. From `deployment/cloudflare-schema-host/`:

```console
npm ci
npx wrangler types --include-runtime false
npm run typecheck
npm run check
```

These commands install the pinned deployment toolchain, regenerate binding types, type-check the Worker, and perform a Wrangler dry run. They do not deploy. See the [schema-hosting guide](schema-hosting.md) for local HTTP checks, authenticated deployment, and live acceptance.

## Build boundaries

Build configuration uses explicit public paths. Normative schemas, public documentation, conformance tooling, contract corpora, and deployment sources are not bundled into the engine wheel or source distribution. Public release artifacts must be created from clean, tracked repository content rather than a parent-directory build context.
