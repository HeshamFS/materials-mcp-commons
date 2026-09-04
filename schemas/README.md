# Versioned contract sources

This directory is the source location for independently versioned Materials MCP Profile contracts. JSON Schema Draft 2020-12 is the normative schema dialect; language-specific models are adapters and cannot replace these contracts.

Each contract version has one exact-version directory such as [`0.1.0/`](0.1.0/README.md). Mutable aliases such as `latest` are not permitted. Every root schema declares the Draft 2020-12 dialect and a path-derived, absolute, fragment-free identifier under:

`https://schemas.autonomouslab.io/materials-mcp/{profile-version}/{resource-name}.schema.json`

The 0.1.0 line contains 16 normative root schemas and a [checksum-pinned resource index](0.1.0/schema-index.json). Validation is deliberately offline: implementations pre-register the exact resources they support and fail closed when a reference or extension schema is absent. Dereferenceable HTTPS copies are a distribution channel, not a validation-time trust source.

Once an exact-version resource is publicly distributed, its bytes and meaning are immutable. A change is published under a new exact profile version; it does not rewrite an existing resource or index.

Project-authored schema and specification content is licensed under CC BY 4.0. See [`../LICENSE-DOCS.md`](../LICENSE-DOCS.md).
