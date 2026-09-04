# Versioning and compatibility

Materials MCP Commons versions the engine distribution and the Materials MCP Profile independently.

## Engine version

The initial Python distribution version is `0.1.0a0` under PEP 440. The alpha marker communicates that APIs and scope can evolve. It does not lower requirements for scientific validity, provenance, security, reproducibility, or real-system evidence.

## Contract version

Contract source versions use exact Semantic Versioning directories, beginning with `schemas/0.1.0/`. Published directories are immutable and there is no `latest` alias. A future compatibility matrix will declare which contract versions each engine release accepts and emits.

JSON Schema Draft 2020-12 is normative. The first actual schemas will be added only after a permanent project-controlled HTTPS namespace is selected for their absolute identifiers. Implementations must resolve registered schema resources locally rather than relying on implicit network retrieval.

Normative contract sources are distributed separately from the Python engine package so their version and CC BY 4.0 licensing remain explicit.
