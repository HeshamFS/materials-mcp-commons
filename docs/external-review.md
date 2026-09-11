# External production-alpha review protocol

M5 requires evidence from a qualified reviewer who did not build the candidate. Automated checks and separate AI-agent reviews are useful internal evidence, but they do not satisfy this external-human gate.

## Reviewer and candidate identity

Record the reviewer's relevant scientific-software or MCP experience, independence from the implementation, operating system, Python version, `uv` version, Codex host version, exact Git commit, wheel and source-distribution SHA-256 values, and exact profile index digests. Keep personal contact details outside the public repository.

## Clean-room procedure

The reviewer must work from a clean archive or public clone, not the builder's working environment, and record every correction or undocumented step required.

1. Verify the candidate commit and artifact hashes before installation.
2. Install the base wheel in a fresh environment; import the package and confirm the optional MCP SDK is absent.
3. Install the `mcp-host` extra in another fresh environment and run `pip check`.
4. Create an empty workspace with `materials-mcp-scaffold`. Confirm that it contains no manifest, capability, handler, backend, result, or scientific claim and that an existing destination is not overwritten.
5. Follow [the authoring guide](authoring.md) to rebuild the real engine-control declarative package and run `materials-mcp-conformance` against the exact local Profile `0.2.0` directory.
6. Register the documented stdio host in an actual supported Codex host, list exactly four tools, and exercise discovery, inspection, activation, a successful engine-control execution, and a structured failure.
7. Run the documented verification commands, install/upgrade/removal lifecycle check, and dependency/license inventory check.
8. Confirm that the docs never imply scientific validation, backend interoperability, or concrete-plugin readiness from structural conformance alone.

## Acceptance record

For each step, record pass/fail, elapsed time, commands used, observed output, required assistance, ambiguity, and any security or scientific-trust concern. A pass requires no undisclosed local dependency or builder intervention. Every failure must retain its exact error, retryability, corrective next action, and whether the reviewer could recover using public documentation alone.

The filled record must identify unresolved findings and the reviewer's explicit recommendation: accept M5, accept with named conditions, or reject. Acceptance does not authorize selecting or implementing a concrete plugin; that remains a separate user decision after all M5 gates pass.
