# Development foundation

The engine currently uses a minimal Python package foundation with no runtime dependencies. Python 3.11 is the syntax and static-analysis floor; the supported initial line is Python 3.11 through 3.14.

## Local checks

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

The committed lockfile controls development and verification dependencies. uv is not a runtime requirement of the installed engine package.

Build configuration uses explicit public paths. Normative schemas, public documentation, contract corpora, and internal development controls are not bundled into the engine wheel or source distribution.
