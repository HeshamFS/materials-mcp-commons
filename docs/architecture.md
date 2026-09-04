# Architecture

Materials MCP Commons is a plugin-agnostic engine for a federation of focused MCP capabilities. Concrete scientific and provider integrations attach later as separately packaged plugins through shared contracts, catalog metadata, runtime services, and evidence.

## Core layers

1. **Materials MCP Profile** — versioned, language-neutral contracts for quantities, entities, artifacts, runs, plans, results, errors, effects, context metadata, provenance, and extension namespaces.
2. **Engine runtime** — generic plugin registration, discovery, inspection, activation, dispatch, failure isolation, and lifecycle control.
3. **Context Gateway** — progressive discovery, compact capability inspection, bounded activation, result projection, and deterministic eviction.
4. **Shared services** — stable artifact, structure, run, catalog, policy, and evidence primitives.
5. **Plugin boundary and Scientist Kit** — generic authoring, validation, testing, packaging, and documentation paths that do not require scientists to become protocol specialists or modify engine code.
6. **Concrete plugins** — later, separately packaged capability surfaces around authoritative datasets, real solvers, scientific workflows, instruments, or compute systems.

## Design boundaries

- The complete capability catalog stays outside normal model context.
- Large arrays, meshes, trajectories, logs, and binary scientific files remain artifacts addressed by typed references and hashes.
- A durable Commons `run_ref` is the primary long-running-work identity; protocol task support is an optional compatibility layer.
- A generic executor cannot bypass schemas, authorization, effect classification, planning, or approval.
- Established scientific formats remain authoritative; compact JSON results are projections, not replacements.
- Numerical results originate from real scientific systems or authoritative real sources.
- Engine packages do not import provider SDKs, solver libraries, scheduler clients, provider-specific schemas, or backend-specific branches.

## Capability lifecycle

The intended control flow is:

`discover -> inspect -> validate -> plan -> execute/query -> observe -> retrieve -> provenance`

Each stage has explicit inputs, bounded outputs, structured failures, and permission semantics.
