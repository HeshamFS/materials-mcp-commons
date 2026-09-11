# Development foundation

The engine uses a minimal Python package foundation. Its base runtime dependencies are `jsonschema` and `referencing`, used for Draft 2020-12 validation and an explicit offline registry. The separately selected `mcp-host` extra provides the official protocol adapter. Python 3.11 is the syntax and static-analysis floor; the supported initial line is Python 3.11 through 3.14.

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

The production-alpha API lock is regenerated from the actual installed package and official-SDK host composition:

```console
uv run python -m tools.freeze_public_api --output public-api.candidate.json
```

The candidate must be byte-identical to `conformance/public-api.json`; `tests/conformance/test_public_api.py` enforces the same comparison in the supported Python matrix.

Its current and frozen milestone suites and committed reproducible reports are documented in [`conformance/`](../conformance/README.md). The runner is public development tooling; it is intentionally outside the installed engine distribution.

The committed `uv.lock` controls development and verification dependencies. uv is not a runtime requirement of the installed engine package.

The host and recovery boundary has focused checks in addition to the complete suite:

```console
uv run pytest tests/runtime/test_mcp_host.py tests/runtime/test_state_recovery.py
uv run pytest tests/runtime/negative_generated/test_mcp_host_rejections.py tests/runtime/negative_generated/test_state_recovery_rejections.py
```

The positive host tests compose the actual engine-control package and use the official SDK client in process and over a real stdio subprocess. The same stdio fixture has also passed the official independent MCP Inspector CLI 2.6.0: strict tool listing returned the exact four schemas and a real discovery call returned the actual engine-control cards. Recovery creates actual run and policy/audit records, snapshots them through SQLite, restores them into a fresh root, and reopens both stores. Generated failure inputs remain isolated in the negative directory.

The checked-in GitHub Actions workflow declares Windows and Ubuntu jobs across Python 3.11 through 3.14, plus a separate Windows packaging/static/coverage job. Action revisions and uv are pinned. A workflow file is not evidence that hosted CI ran: record the actual run URL and conclusion only after a public remote exists and the workflow has executed. Local Windows 3.11-3.14 and Ubuntu WSL2 Python 3.12 results are maintained separately as dated milestone evidence.

## Authoring checks

The installed `materials-mcp-scaffold` command creates a fresh empty scientist workspace from explicit metadata. The typed `PluginPackageBuilder` then constructs a checksum-bound declarative package from complete authored schemas and validates it with the runtime loader. See the [Scientist Kit guide](authoring.md).

The test suite reconstructs the actual engine-control package twice and compares every output byte. It also verifies the package report, exact-profile matrix, generated capability reference, and explicit migration assessment:

```console
uv run python -m tools.run_plugin_conformance package
uv run python -m tools.run_plugin_conformance matrix
uv run python -m tools.run_plugin_conformance reference
uv run pytest tests/conformance/test_plugin_authoring_reports.py tests/runtime/test_plugin_migration.py tests/runtime/negative_generated/test_plugin_conformance_rejections.py
```

The passing migration case uses two checked-in declarations of actual engine-control behavior under `tests/runtime/positive-project/`. Generated mutations remain isolated under `tests/runtime/negative_generated/` and pass only when drift is rejected or reported; they are not scientific examples.

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
