# Schemas

The immutable first authored schema line is `0.1.0/`. Its exact HTTPS identifiers
are rooted at:

`https://schemas.autonomouslab.io/materials-mcp/plugins/optimade/0.1.0/`

The identifiers are frozen exact-version identifiers. Hosted publication is
claimed only when the support matrix names an immutable deployment commit and
passing byte-parity evidence for this plugin line and its required core profile
`0.2.0`. Runtime validation always resolves the checked local package resources
and does not depend on network schema retrieval.

These are plugin-owned Draft 2020-12 input, search, provider, and composite
identity contracts. Exact gets reuse the core profile `ResultBundle`; exports
reuse the core `Artifact`; every capability reuses the core structured error.

The checked-in declarative package under
`src/materials_mcp_optimade/declarative/` is rebuilt byte-for-byte from these
sources by `tools/build_declarative_package.py`. Do not modify a published exact
schema line in place.
