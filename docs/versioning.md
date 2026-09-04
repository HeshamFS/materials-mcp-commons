# Versioning and compatibility

Materials MCP Commons versions the engine distribution and the Materials MCP Profile independently.

## Engine version

The initial Python distribution version is `0.1.0a0` under PEP 440. The alpha marker communicates that APIs and scope can evolve. It does not lower requirements for scientific validity, provenance, security, reproducibility, or real-system evidence.

## Contract version

Contract source versions use exact Semantic Versioning directories, beginning with `schemas/0.1.0/`. Published directories are immutable and there is no `latest` alias. A future compatibility matrix will declare which contract versions each engine release accepts and emits.

JSON Schema Draft 2020-12 is normative. The 0.1.0 line contains 16 root schemas whose absolute identifiers use:

`https://schemas.autonomouslab.io/materials-mcp/0.1.0/{resource-name}.schema.json`

Its `schema-index.json` pins the exact identifier, path, media type, and SHA-256 digest of every schema. Implementations resolve registered resources locally and fail closed rather than relying on implicit network retrieval. The canonical HTTPS host exists for durable distribution and human/tool discovery, not as a validation-time dependency.

After an exact-version resource or index is publicly distributed, its bytes and meaning are permanent. Corrections and additions use a new exact profile version. Branch names, mutable aliases, query strings, fragments, and local paths are not contract identifiers.

Normative contract sources are distributed separately from the Python engine package so their version and CC BY 4.0 licensing remain explicit.

See [the contract guide](contracts.md) for 0.1.0 semantics and [canonical schema hosting](schema-hosting.md) for distribution and integrity verification.
