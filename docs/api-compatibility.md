# Production-alpha API compatibility

Engine `0.1.0a12` is the frozen production-alpha API candidate for the later concrete-plugin proof. It supersedes the incomplete `0.1.0a9`, `0.1.0a10`, and `0.1.0a11` snapshots. Independent adversarial review of a11 found that caller-rewritten receipt fields could bypass the durable grant binding and that one receipt could invoke an effectful handler repeatedly. The a12 contract preserves `verify_receipt` as a non-redeeming compatibility method, adds atomic single-use `redeem_receipt`, migrates policy state fail-closed, separates authorization-resolver failures from dispatch failures, and widens the nested MCP success `result` from object-only to any JSON root while rejecting non-wire-safe values. The freeze gives plugin authors and embedders one explicit engine target; it does not mean that a package, network service, or production-alpha release has been published.

## What is public

The machine-readable baseline is [`../conformance/public-api.json`](../conformance/public-api.json). It records:

- every name exported by `materials_mcp_commons.__all__`, its origin and kind, callable signature, declared dataclass fields, and declared public class members;
- the `materials-mcp-scaffold` and `materials-mcp-conformance` console-script mappings;
- the exact supported Profile `0.1.0` and `0.2.0` lines; and
- the ordered four-tool MCP inventory with descriptions, closed top-level input and output schemas, and the stable public MCP error-code registry;
- whether every exported callable is synchronous, a coroutine, a generator, or an asynchronous generator.

Names that are merely importable from an underscored name or package submodule are implementation details unless they also appear in the root export list. Profile resource bytes are governed separately by their exact-version schema indexes and publication rules.

## Compatibility rules

Within the frozen `0.1` production-alpha line, a backward-compatible addition still requires a new engine version, a regenerated API contract, migration notes, and review. Existing exports, parameters, dataclass fields, console mappings, protocol tools, and tool-schema properties cannot be silently removed, renamed, reordered, tightened, or assigned weaker semantics.

An incompatible change requires a new incompatible engine line and an explicit migration decision. Correctness or security defects may force that decision, but alpha status does not permit an unrecorded break.

Structured error `code` values in the contract's `protocol.error_codes` registry are stable machine identifiers within the frozen line. New codes may be added. Existing codes cannot be repurposed; human-readable messages can improve and are not compatibility keys. Internal Python exception codes are diagnostic implementation details unless separately promoted into that registry.

## Verify the baseline

From a locked development environment:

```console
uv run python -m tools.freeze_public_api --output public-api.candidate.json
```

The candidate must be byte-identical to `conformance/public-api.json` on every supported Python line. The conformance tests perform a fresh installed-package comparison and separately assert that trusted owner, authorization, policy, state-root, and event-sink inputs remain absent from the MCP execute schema.

When a reviewed compatible change is intentional, advance the engine version first, regenerate the checked-in contract, document the migration impact, and rerun the full engine gate. Do not edit the snapshot by hand.

This API freeze does not establish hosted CI, an actual production host, external authoring usability, or scientific validity. Those remain independent release evidence.
