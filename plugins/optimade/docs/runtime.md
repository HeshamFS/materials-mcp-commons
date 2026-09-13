# OPTIMADE runtime and stdio host

The package can be embedded as a Python library or launched as a four-tool MCP
stdio server. Both paths register the same checksum-bound declarative package,
bind the same seven handlers, and use the same fixed provider and contract
boundaries.

## Source checkout setup

Until the engine and integration distributions are published, install from the
public source checkout with the exact lock:

```console
cd plugins/optimade
uv sync --all-groups --extra mcp-host --locked
```

The profile, export, and policy-state directories must already exist. Use
absolute paths and keep the policy directory private to the host process:

```console
materials-mcp-optimade-host \
  --profile-root /absolute/path/to/schemas/0.2.0 \
  --export-root /absolute/path/to/exports \
  --policy-root /absolute/path/to/policy-state \
  --export-quota 100
```

On Windows, pass the same arguments with absolute drive-qualified paths. The
host writes only protocol messages to standard output. It never downloads a
profile, follows provider redirects, reads proxy variables, or creates missing
directories.

The MCP surface remains the generic engine protocol:

1. `materials_discover` returns bounded local capability cards;
2. `materials_inspect` returns the exact registration and schemas;
3. `materials_activate` opens a bounded logical-turn lease; and
4. `materials_execute` validates and dispatches one exact active capability.

The generated [capability reference](../conformance/capabilities.md) lists all
seven capability IDs and their exact input, result, and error contracts.

Search execution preflights canonical query metadata at 500 tokenizer tokens
and 3,072 UTF-8 bytes before federation. The result binds the full query and
entry type through `query.sha256` instead of repeating filter text. It then
measures the complete JSON result with the declared `o200k_base` tokenizer and
UTF-8 encoding before it crosses the MCP boundary.
When a larger requested page cannot fit the 1,500-token or 8,192-byte inline
budget, it first compacts verbose provider warnings and page-by-page hash/time
arrays. Page evidence retains retrieval order in a documented, recomputable
per-provider SHA-256 commitment with the exact count. Only then does it remove
whole hits, declare the count, and roll provider cursors back to the first
omitted record. Repeating the same request with the returned continuation
retrieves the omitted data without starvation, duplication, or a silent offset
jump. If a single hit cannot fit the remaining envelope, the response advances
past that hit only after emitting a `deferred_hits` descriptor for exact
retrieval. The descriptor carries provider record identifiers only once. If its
JSON-escaped form still cannot fit the measured envelope, that provider becomes a
bounded `record-identity-context` partial failure without advancing its cursor;
other providers are preserved. The
tokenizer's exact merge-rank data is fetched from a fixed upstream HTTPS
endpoint through the bounded project transport and verified by SHA-256. One
successful load is retained in process memory; failed loads remain bounded and
can be retried by a later call. The runtime does not use `requests`, proxy
variables, or a machine tokenizer cache.

All seven handlers are also constrained by the engine dispatch envelope.
Registry listing, provider inspection, and exact retrieval compact only whole
repeatable records under a 60 KiB/3,800-node target. They update omission
metadata and preserve checksummed source evidence before the engine performs its
authoritative 65,536-byte/4,096-node validation.

## Python composition

Embedding applications can compose the same host explicitly:

```python
from pathlib import Path

from materials_mcp_commons import ContractRegistry, PolicyEngine, create_mcp_server
from materials_mcp_optimade.host import build_mcp_runtime

profile_root = Path("/absolute/path/to/schemas/0.2.0")
export_root = Path("/absolute/path/to/exports")
policy_root = Path("/absolute/path/to/policy-state")
contracts = ContractRegistry.from_directory(profile_root, "0.2.0")

with PolicyEngine(policy_root, contracts) as policy_engine:
    runtime = build_mcp_runtime(
        contracts,
        export_root,
        policy_engine,
        owner_ref="urn:example:owner:materials-research",
        export_quota=100,
    )
    create_mcp_server(runtime.host).run("stdio")
```

The returned `registration_ref` is also available on `runtime` for direct
engine embedding. A client using MCP normally obtains it from
`materials_inspect`.

## Export authorization and files

The first six capabilities are R0 reads. Export is R1: the engine first verifies
the exact activation is live, then the standalone host validates the exact
input, creates an immutable operation plan, checks its fixed export-root
permission, reserves one unit from the durable configured quota, consumes a
single-use receipt, and lets the dispatcher redeem that receipt immediately
before the handler runs. An inactive or expired request never reaches the
authorization resolver and consumes no quota. R1 export uses the configured
host policy and quota.

Authorization alone cannot establish redistribution rights. The handler also
requires a current affirmative provider-rights record before network access and
again immediately before writing. Materials Project therefore remains readable
but not exportable while its applicable rights are unresolved. The reviewed
NOMAD record permits native JSON and supported CIF export until its recorded
rights review expires; a new review is required after expiry.

Destinations are safe relative paths beneath the configured root. Parent
directories must already exist. Links, reparse points, traversal, absolute
destinations, existing files, and `overwrite: true` are rejected. POSIX uses a
no-follow, directory-descriptor-relative create; Windows opens and validates the
root and every parent by handle, creates the file exclusively, and validates its
final kernel path before writing provider bytes. Native JSON is byte-identical
to the fresh validated response. A CIF is a documented projection with explicit
conversion notes, not a claim of source symmetry.

Supplying `expected_response_sha256` turns the fresh provider response hash into
a write precondition. A mismatch leaves the destination absent. Successful
artifacts contain a logical workspace URN plus exact size, SHA-256, source,
rights, citation, and transformation provenance; local filesystem paths are not
placed on the MCP wire.

## Evidence boundary

The checked structural report proves only manifest, schema, and registration
integrity. Live tests separately contact the official registry and the two
fixed providers, exercise exact engine dispatch and a real stdio subprocess,
and parse a real exported CIF with an independent crystallographic parser.
Generated data appears only in rejection and security controls. The checked
[`support matrix`](../conformance/support-matrix.json) separates offline checks
from dated real-provider observations.
