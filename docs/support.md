# Production-alpha support boundary

Materials MCP Commons is preparing a research-grade production alpha. The declared engine matrix is intentionally narrower than the set of environments where the package may happen to work.

## Required environment matrix

| Surface | Supported boundary |
|---|---|
| Operating systems | Current GitHub-hosted Windows and Ubuntu runner families, plus corresponding local Windows and Ubuntu-compatible Linux environments |
| Python | CPython 3.11, 3.12, 3.13, and 3.14 |
| Base engine | Installed without a protocol SDK; contracts, lifecycle, dispatch, policy, context, authoring, conformance, run state, and recovery remain available |
| MCP adapter | Optional `mcp-host` extra using the official MCP Python SDK 2.2.x |
| Transport | Local subprocess stdio and in-process SDK composition |
| Required hosts | Codex CLI and the independent MCP Inspector |
| Additional compatibility | Other MCP hosts are reported only after an actual bounded interoperability run |

The matrix requires complete tests on Windows and Ubuntu for every supported Python line. Packaging, strict static analysis, branch-aware coverage, production dependency vulnerability checks, and install/upgrade/removal evidence run as separate release gates. Platform-specific Python 3.12 dependency and lifecycle inventories are retained because their resolved graphs differ.

## Host acceptance

A host is not considered compatible merely because it can save an MCP configuration or display a server name. Acceptance requires the actual stdio server to:

1. initialize successfully and list exactly the four bounded engine tools;
2. discover a real registered engine-control capability;
3. inspect and activate that exact capability;
4. execute it successfully through the dispatcher; and
5. return a complete structured failure for an invalid target.

Current dated host evidence for the engine candidate is:

| Host | Version | Result | Scope |
|---|---:|---|---|
| MCP Inspector | 2.6.0 | Pass | Exact four-tool listing and real discovery call over stdio |
| Codex CLI | 0.153.3 | Pass | Exact four-tool availability, discovery, inspection, activation, R0 execution, and structured failure over stdio on 2026-09-11 |
| Claude Code | 2.1.268 | Compatible | The same bounded end-to-end sequence over stdio on 2026-09-11; additional evidence, not a required release host |

Codex's non-interactive default `approval policy is never` rejects an MCP call that requires approval. The passing run used Codex's bounded automatic-approval mode and verified completed tool events rather than trusting the model's summary. Host policies therefore remain part of installation and acceptance, even for an R0 engine operation.

The distribution provides a composition library, not a preconfigured server with an invented plugin or trusted identity. An embedding application must explicitly supply the contract registry, selected declarative packages, lifecycle, handlers, dispatcher, and trusted owner boundary described in the [MCP host guide](mcp-host.md).

## Explicit exclusions

Streamable HTTP and every other network deployment are unsupported in this alpha boundary. The SDK's ability to construct an HTTP application is not deployment evidence. Network support requires a separately accepted authenticated-principal design, transport-security allowlist, reverse-proxy and TLS controls, bounded request resources, and executed security and operations gates.

No concrete scientific or provider plugin is part of the engine support declaration. Scientific capabilities require their own real-system, provenance, numerical, licensing, security, and domain-review evidence before they can receive a trust label.

## Evidence status

The checked-in workflow and local reports are reproducibility inputs, not self-certifying claims. A release record must identify the immutable commit, successful hosted workflow run, exact host and SDK versions, artifact hashes, and qualified independent review. Until every required gate is recorded, the repository remains an unreleased alpha candidate.
