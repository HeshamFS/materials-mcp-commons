# OPTIMADE integration contract

This package is a one-way dependency of Materials MCP Commons. The engine does
not import, name, package, or special-case this integration.

## Exact identity and compatibility

| Surface | Frozen value |
|---|---|
| Distribution | `materials-mcp-optimade` `0.1.0a1` |
| Import package | `materials_mcp_optimade` |
| Plugin | `https://schemas.autonomouslab.io/materials-mcp/plugins/optimade` |
| Plugin manifest version | `0.1.0-alpha.1` |
| Plugin schema line | `https://schemas.autonomouslab.io/materials-mcp/plugins/optimade/0.1.0/` |
| Engine | `materials-mcp-commons==0.1.0a13` |
| Profile | `0.2.0` |
| Protocol implementation | stable OPTIMADE 1.2.x patch line; 1.2.0 baseline |
| Intended local matrix | Windows and Ubuntu, CPython 3.11-3.14 |
| Trust target | `Verified`; not `Validated` |

The current official OPTIMADE specification is 1.3.0, but the accepted live
providers and the pinned official Python grammar/model dependency currently use
the 1.2 line. Stable 1.2 patch releases are accepted under OPTIMADE's semantic
versioning compatibility rule; development suffixes and other minor/major lines
fail closed. The client reports other stable 1.x versions during inspection but
does not execute or claim 1.3-only features until a versioned package change and
real-provider evidence support them.

## Capabilities and effects

| Capability suffix | Result contract | Effect |
|---|---|---|
| `providers/list` | plugin provider-list result | R0 bounded registry/index reads |
| `providers/inspect` | plugin provider-inspection result | R0 bounded provider metadata reads |
| `structures/search` | plugin zero-capable search result | R0 bounded federation |
| `structures/get` | one core `ResultBundle` | R0 exact record read |
| `references/search` | plugin zero-capable search result | R0 bounded federation |
| `references/get` | one core `ResultBundle` | R0 exact record read |
| `records/export` | one core `Artifact` | R1 bounded local write plus rights check |

All errors use the exact profile 0.2.0 structured-error contract. Search and
inspection outputs include selected/returned/omitted counts; a model-facing
projection cannot silently stand in for a complete provider response.

## Composite identity

No cross-provider deduplication occurs. One record is identified by:

1. registry provider ID;
2. resolved database ID;
3. normalized reviewed API base URL;
4. entry type (`structures` or `references`);
5. provider entry ID; and
6. immutable ID when the provider supplies it.

Exact retrieval encodes these values as frozen schemes in the core entity
identifier array and as the registered
`record-identity.extension.schema.json` payload. Formula, composition, or
geometry is never used as an identity substitute.

## Request and context limits

- providers per search: 2;
- fields per search: 32; fields per exact get: 64;
- page size: 50; pages per provider per call: 5;
- combined search hits: 100;
- sort keys: 8; included relationship types: 4;
- provider property definitions returned by inspection: 128, with an explicit
  omitted count;
- every response page and complete exact record carries its exact response-byte
  SHA-256; and
- namespaced provider properties remain separate from standard OPTIMADE fields.

Mapped `ResultBundle` property identifiers use the stable OPTIMADE `1.2`
contract line, while the exact provider patch version remains in source
provenance. A provider patch upgrade therefore does not change the identity of
an otherwise identical standard property.

For two-provider calls, `max_results` must be at least two and is divided
deterministically in requested-provider order; each selected provider receives
at least one result slot. Unused or exhausted capacity is not silently reassigned
across providers because that would make pagination and provider completeness
ambiguous. Each provider reports its own continuation state.

Runtime code imposes additional byte, decompression, JSON-depth, time, retry,
DNS/address, redirect, and concurrency limits. Provider-supplied pagination URLs
are never treated as authority and HTTP scheme downgrades are rejected.
DNS resolution is included in the total request deadline. The transport requests
and pins only public IPv4 addresses while retaining the reviewed hostname for
TLS. IPv6 literals are rejected because globally routed NAT64 prefixes can embed
private IPv4 targets and network-specific translation prefixes cannot be safely
classified from the literal alone. The transport requests identity encoding
only, rejects redirects and ambiguous framing, and accepts no ambient proxy or
credential configuration. Repeated page hashes, repeated record identities,
stalled pages, and inconsistent provider counts fail as bounded pagination
errors; earlier real hits remain explicitly partial.

If a provider fails before a response can establish its current API version,
the per-provider `api_version` is `null`; the integration does not substitute a
cached or configured version as though it were observed in that failed call.

The protocol's `/versions` response advertises versioned-base identifiers, which
may be only a major version such as `1`. Those identifiers are preserved as
reported. The exact semantic API version and the selected implementation line
come independently from the validated `/v1/info` response; the client never
expands a provider's major-only advertisement into a fabricated semantic
version.

Official registry records are preserved even when their optional `base_url` is
absent. Such records carry `index_base_url: null`, remain `registry-only`, and
never become request authority.

## Rights boundary

Public reachability, registry membership, and protocol conformance are not
licenses. Each provider has an expiring rights record. A successfully reviewed
terms document carries the hash of the exact retrieved bytes. If the applicable
terms cannot be retrieved and reviewed, `review_status` is `unavailable`, the
hash is `null`, and the record is constrained to `access-only`, `NOASSERTION`,
and redistribution `unknown`; a placeholder hash is never fabricated.

R0 reads may return bounded model-facing data with provenance. R1 export first
passes engine path/permission/quota policy, then independently requires a current
provider record that affirmatively permits the requested representation. An
expired or absent record fails closed. Materials Project content is not bundled
as a fixture while its applicable redistribution terms remain unresolved.

The engine verifies a live exact activation before the standalone host's
authorization resolver runs. The resolver then validates the export input,
creates a plan, binds the exact immutable input digest, consumes a single-use
receipt, and charges one durable export unit before dispatch. An inactive or
expired call consumes no authorization state. The exporter repeats the rights
check after fresh retrieval and immediately before its exclusive non-overwriting
write. A failed handler after valid authorization does not refund the consumed
receipt or quota.

Native JSON export preserves the exact validated provider response bytes. CIF
export currently accepts only three-dimensional periodic structures with a
finite nonsingular lattice, consistent site counts, and fully occupied
CIF-compatible species. It converts provider Cartesian positions to wrapped
fractional coordinates and emits a `P 1` representation without claiming that
the source supplied that symmetry. Every artifact records source URI, response
hash, projection, transformation, rights, citation, and timestamps through the
registered export-provenance extension.

## Dependency boundary

`optimade==1.5.0` is pinned for its official 1.2 `LarkParser` and Pydantic
response models. The integration does not use `OptimadeClient`, its HTTP extra,
its cache, or its provider-wide/default request behavior. The project-owned
transport uses only fixed reviewed configuration and the Python standard library
for egress. Transitive `requests` is therefore not an authorized network path.

Structural conformance, successful parsing, or a live response does not establish
scientific validity. Positive evidence uses real provider records; generated
inputs are isolated to negative, boundary, fuzz, and security rejection tests.
NOMAD currently exposes no reference records through the tested endpoint, while
the Materials Project rights record remains fail-closed for redistribution.
Consequently reference export is contract-complete but has no positive
rights-cleared live artifact in the initial matrix; this limitation is reported
instead of being filled with fixture data.
