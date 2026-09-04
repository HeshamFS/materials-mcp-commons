# Versioned contract sources

This directory is the source location for independently versioned Materials MCP Profile contracts. JSON Schema Draft 2020-12 is the normative schema dialect; language-specific models are adapters and cannot replace these contracts.

Each published contract version has one immutable exact-version directory such as `0.1.0/`. Mutable aliases such as `latest` are not permitted. Every future root schema must declare the Draft 2020-12 dialect and an absolute, fragment-free identifier in the accepted project-controlled namespace.

No normative schema has been published yet. The first version directory documents the layout only and is not a conformance target.

Project-authored schema and specification content is licensed under CC BY 4.0. See [`../LICENSE-DOCS.md`](../LICENSE-DOCS.md).
