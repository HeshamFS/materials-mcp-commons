# Materials MCP OPTIMADE capability reference

This generated reference reports exact declarative structure only. It does not load or execute plugin code and does not establish backend interoperability, security, or scientific validity.

- Plugin ID: `https://schemas.autonomouslab.io/materials-mcp/plugins/optimade`
- Plugin version: `0.1.0-alpha.1`
- Profile version: `0.2.0`
- Publisher: Hesham Salama
- License expression: `Apache-2.0`
- Manifest SHA-256: `1618b63a3f6d8ffb11b8eb26887bf15db123c1a9f72d2064372b7c466ffa9246`

## List OPTIMADE providers

Read the official registry and resolve only reviewed supported provider index entries without querying registry-only databases.

- Capability ID: `https://schemas.autonomouslab.io/materials-mcp/plugins/optimade/providers/list`
- Effect tier: `R0`
- Effect category: `read-only`
- Plan required: `no`
- Approval required: `no`
- Strong confirmation required: `no`
- Asynchronous: `no`
- Input schema: `https://schemas.autonomouslab.io/materials-mcp/plugins/optimade/0.1.0/provider-list-input.schema.json`
- Result schema: `https://schemas.autonomouslab.io/materials-mcp/plugins/optimade/0.1.0/provider-list-result.schema.json`
- Error schema: `https://schemas.autonomouslab.io/materials-mcp/0.2.0/structured-error.schema.json`

## Inspect an OPTIMADE provider

Inspect versions, base info, structures/references entry info, implementation metadata, limits, and current rights state for one supported provider.

- Capability ID: `https://schemas.autonomouslab.io/materials-mcp/plugins/optimade/providers/inspect`
- Effect tier: `R0`
- Effect category: `read-only`
- Plan required: `no`
- Approval required: `no`
- Strong confirmation required: `no`
- Asynchronous: `no`
- Input schema: `https://schemas.autonomouslab.io/materials-mcp/plugins/optimade/0.1.0/provider-inspect-input.schema.json`
- Result schema: `https://schemas.autonomouslab.io/materials-mcp/plugins/optimade/0.1.0/provider-inspect-result.schema.json`
- Error schema: `https://schemas.autonomouslab.io/materials-mcp/0.2.0/structured-error.schema.json`

## Search OPTIMADE structures

Run one validated OPTIMADE 1.2 filter across an explicit supported-provider subset with bounded fields, pages, results, honest partial failure, exact context measurement, and continuation or exact retrieval for omitted hits.

- Capability ID: `https://schemas.autonomouslab.io/materials-mcp/plugins/optimade/structures/search`
- Effect tier: `R0`
- Effect category: `read-only`
- Plan required: `no`
- Approval required: `no`
- Strong confirmation required: `no`
- Asynchronous: `no`
- Input schema: `https://schemas.autonomouslab.io/materials-mcp/plugins/optimade/0.1.0/search-input.schema.json`
- Result schema: `https://schemas.autonomouslab.io/materials-mcp/plugins/optimade/0.1.0/search-result.schema.json`
- Error schema: `https://schemas.autonomouslab.io/materials-mcp/0.2.0/structured-error.schema.json`

## Get one OPTIMADE structure

Retrieve exactly one structure by reviewed provider, database, and entry identity and map it to one provenance-complete core ResultBundle.

- Capability ID: `https://schemas.autonomouslab.io/materials-mcp/plugins/optimade/structures/get`
- Effect tier: `R0`
- Effect category: `read-only`
- Plan required: `no`
- Approval required: `no`
- Strong confirmation required: `no`
- Asynchronous: `no`
- Input schema: `https://schemas.autonomouslab.io/materials-mcp/plugins/optimade/0.1.0/get-input.schema.json`
- Result schema: `https://schemas.autonomouslab.io/materials-mcp/0.2.0/result-bundle.schema.json`
- Error schema: `https://schemas.autonomouslab.io/materials-mcp/0.2.0/structured-error.schema.json`

## Search OPTIMADE references

Run one validated OPTIMADE 1.2 filter over references across an explicit supported-provider subset with bounded projection, partial-failure reporting, and context-safe continuation or exact retrieval for omitted hits.

- Capability ID: `https://schemas.autonomouslab.io/materials-mcp/plugins/optimade/references/search`
- Effect tier: `R0`
- Effect category: `read-only`
- Plan required: `no`
- Approval required: `no`
- Strong confirmation required: `no`
- Asynchronous: `no`
- Input schema: `https://schemas.autonomouslab.io/materials-mcp/plugins/optimade/0.1.0/search-input.schema.json`
- Result schema: `https://schemas.autonomouslab.io/materials-mcp/plugins/optimade/0.1.0/search-result.schema.json`
- Error schema: `https://schemas.autonomouslab.io/materials-mcp/0.2.0/structured-error.schema.json`

## Get one OPTIMADE reference

Retrieve exactly one reference by reviewed provider, database, and entry identity and map it to one provenance-complete core ResultBundle.

- Capability ID: `https://schemas.autonomouslab.io/materials-mcp/plugins/optimade/references/get`
- Effect tier: `R0`
- Effect category: `read-only`
- Plan required: `no`
- Approval required: `no`
- Strong confirmation required: `no`
- Asynchronous: `no`
- Input schema: `https://schemas.autonomouslab.io/materials-mcp/plugins/optimade/0.1.0/get-input.schema.json`
- Result schema: `https://schemas.autonomouslab.io/materials-mcp/0.2.0/result-bundle.schema.json`
- Error schema: `https://schemas.autonomouslab.io/materials-mcp/0.2.0/structured-error.schema.json`

## Export one OPTIMADE record

Persist one freshly retrieved exact record as checksummed native JSON or a supported scientific export only when current provider rights allow it.

- Capability ID: `https://schemas.autonomouslab.io/materials-mcp/plugins/optimade/records/export`
- Effect tier: `R1`
- Effect category: `bounded-local`
- Plan required: `no`
- Approval required: `no`
- Strong confirmation required: `no`
- Asynchronous: `no`
- Input schema: `https://schemas.autonomouslab.io/materials-mcp/plugins/optimade/0.1.0/export-input.schema.json`
- Result schema: `https://schemas.autonomouslab.io/materials-mcp/0.2.0/artifact.schema.json`
- Error schema: `https://schemas.autonomouslab.io/materials-mcp/0.2.0/structured-error.schema.json`
