# Materials MCP Commons engine lifecycle capability reference

This generated reference reports exact declarative structure only. It does not load or execute plugin code and does not establish backend interoperability, security, or scientific validity.

- Plugin ID: `https://schemas.autonomouslab.io/materials-mcp/engine`
- Plugin version: `0.1.0-alpha.9`
- Profile version: `0.2.0`
- Publisher: Hesham Salama
- License expression: `Apache-2.0`
- Manifest SHA-256: `0880df4258baad35bdf3641b8b249644c71bf71511447ba0ec4dd3dd73530cba`

## Discover registered capabilities

Return a deterministic bounded set of compact cards from manifests already validated and registered in the local engine.

- Capability ID: `https://schemas.autonomouslab.io/materials-mcp/engine/discover`
- Effect tier: `R0`
- Effect category: `read-only`
- Plan required: `no`
- Approval required: `no`
- Strong confirmation required: `no`
- Asynchronous: `no`
- Input schema: `https://schemas.autonomouslab.io/materials-mcp/engine/0.1.0/discovery-input.schema.json`
- Result schema: `https://schemas.autonomouslab.io/materials-mcp/engine/0.1.0/discovery-result.schema.json`
- Error schema: `https://schemas.autonomouslab.io/materials-mcp/0.2.0/structured-error.schema.json`

## Inspect a registered capability

Return immutable identity, effect, and exact schema metadata for one capability already registered in the local engine.

- Capability ID: `https://schemas.autonomouslab.io/materials-mcp/engine/inspect`
- Effect tier: `R0`
- Effect category: `read-only`
- Plan required: `no`
- Approval required: `no`
- Strong confirmation required: `no`
- Asynchronous: `no`
- Input schema: `https://schemas.autonomouslab.io/materials-mcp/engine/0.1.0/inspection-input.schema.json`
- Result schema: `https://schemas.autonomouslab.io/materials-mcp/engine/0.1.0/inspection-result.schema.json`
- Error schema: `https://schemas.autonomouslab.io/materials-mcp/0.2.0/structured-error.schema.json`
