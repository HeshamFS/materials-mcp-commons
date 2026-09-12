# Materials MCP OPTIMADE

This separately packaged integration provides bounded read-only federation over
the OPTIMADE 1.2 API surface and a distinct rights-gated local export boundary.
Its first support matrix contains Materials Project (`mp`) and NOMAD (`nmd`);
registry entries outside that reviewed allowlist can be described but are never
queried as execution authority.

The package targets Materials MCP Commons engine `0.1.0a13`, profile `0.2.0`,
and the `Verified` trust level. It does not claim that provider data is
scientifically validated, does not merge records across providers, and does not
infer redistribution rights from public reachability or protocol conformance.

## Frozen capability contract

- list registry and supported provider records (`R0`);
- inspect one supported provider's versions, info, entry types, and current
  rights record (`R0`);
- search structures across one or both supported providers (`R0`);
- retrieve one exact structure by composite identity (`R0`);
- search references across one or both supported providers (`R0`);
- retrieve one exact reference by composite identity (`R0`); and
- export one freshly retrieved record only when engine `R1` policy and a current
  affirmative provider-rights record both allow it.

Searches use a plugin-owned result contract that permits honest zero matches and
explicit partial provider failure. Exact retrieval returns one core
`ResultBundle`; export returns one core `Artifact`.

## Development boundary

`optimade==1.5.0` supplies the consortium's 1.2 filter parser and response data
models. The upstream multi-provider client and its cache/request defaults are not
used. Network authority stays in project-owned HTTPS code with fixed provider
configuration, DNS/address verification, no ambient credentials or proxies, no
scheme downgrade, IPv4-only public-address pinning (which excludes NAT64
translation ambiguity), bounded responses, and bounded retry/pagination.

The engine alpha is not published yet. This checkout therefore resolves the
exact engine dependency from `../..` for local development; built package
metadata retains the exact version requirement. No package registry publication
or name reservation is part of this source milestone.

The optional `mcp-host` extra installs the official MCP SDK. The
`materials-mcp-optimade-host` command then composes the unchanged engine, all
seven plugin handlers, a durable bounded-export policy, and the fixed provider
client into one stdio server. It requires explicit existing profile, export,
and policy-state roots; it never downloads contracts or creates an implicit
write location.

See [`docs/runtime.md`](docs/runtime.md) for installation, host operation, and
R1 export behavior. [`docs/contracts.md`](docs/contracts.md) defines exact
identities, limits, mapping rules, support, and known limitations. The checked
[`support matrix`](conformance/support-matrix.json) records the local offline
and real-provider observations. Reproducible structural and dependency evidence
is under [`conformance/`](conformance/) and explained in
[`docs/dependencies.md`](docs/dependencies.md).
