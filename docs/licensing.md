# Licensing and third-party material

Materials MCP Commons applies separate licenses to project-authored software and prose:

- Source code: Apache License 2.0
- Documentation, schema specifications, and specification/test-vector content: CC BY 4.0

These licenses apply only to material for which Hesham Salama owns or controls the relevant rights. They do not relicense third-party dependencies, datasets, models, solvers, databases, pseudopotentials, examples, or generated artifacts.

## Current dependency inventory

The engine package has no runtime dependencies. Its wheel therefore does not redistribute any third-party Python runtime package.

The current directly declared Python build and verification tools are:

| Package | Current resolution or constraint | Role | Reported license |
|---|---|---|---|
| Hatchling | `>=1.27,<2` | Isolated build backend | MIT |
| jsonschema | `4.26.0` | Draft 2020-12 instance and meta-schema validation | MIT |
| referencing | `0.37.0` | Explicit offline schema registry | MIT |
| Pyright | `1.1.411` | Static type analysis | MIT |
| pytest | `9.1.1` | Test runner | MIT |
| pytest-cov | `7.1.0` | Coverage integration | MIT |
| Ruff | `0.16.6` | Linting and formatting | MIT |
| uv | `>=0.9.18` | Resolver, environment runner, and build frontend | Apache-2.0 OR MIT |

The exact Python verification graph, including transitive versions, is recorded in [`uv.lock`](../uv.lock). These tools are development/build inputs, not installed engine requirements.

The Cloudflare schema-host deployment has no application runtime dependency. Its directly pinned development/deployment tools are:

| Package | Pinned version | Role | Reported license |
|---|---:|---|---|
| Wrangler | `4.129.0` | Worker development and deployment CLI | MIT OR Apache-2.0 |
| `@cloudflare/workers-types` | `5.20260904.1` | Worker runtime type declarations | MIT OR Apache-2.0 |
| TypeScript | `7.0.2` | Static compilation check | Apache-2.0 |

The exact Node.js dependency graph is recorded in [`deployment/cloudflare-schema-host/package-lock.json`](../deployment/cloudflare-schema-host/package-lock.json). Wrangler, TypeScript, and type declarations are not imported by the deployed Worker.

License expressions above were reviewed from package metadata on 2026-09-04. Lockfiles preserve the reviewed version graph; a release still requires a refreshed transitive-license, vulnerability, and artifact inventory.

## Included data and test-vector rights

| Path | Material | Rights |
|---|---|---|
| [`tests/contracts/positive-real/cod-9013102/source.cif`](../tests/contracts/positive-real/cod-9013102/source.cif) | Crystallography Open Database record 9013102, revision 291877 | CC0-1.0; redistribution permitted; acknowledge B. N. Dutta and the original structural-data sources as requested by COD |
| [`tests/contracts/positive-real/cod-9013102/registration.json`](../tests/contracts/positive-real/cod-9013102/registration.json) and [`result-bundle.json`](../tests/contracts/positive-real/cod-9013102/result-bundle.json) | Project-authored registration and direct contract projection | CC BY 4.0; embedded source facts retain their source provenance |
| [`tests/contracts/negative-generated/`](../tests/contracts/negative-generated/README.md) | Project-authored invalid contract inputs used only for rejection testing | CC BY 4.0; no scientific-validity claim |
| [`schemas/`](../schemas/README.md) and [`docs/`](README.md) | Project-authored schema specifications and documentation | CC BY 4.0 |
| `src/`, executable tests, and `deployment/` code | Project-authored software | Apache-2.0 |

The [source-specific fixture record](../tests/contracts/positive-real/cod-9013102/README.md) documents source URLs, exact byte counts and digests, repository normalization, projected fields, citation, and scientific limitations.

## Third-party intake rule

Before third-party material is used in a test, example, distribution, or evidence package, the project records:

- canonical source and version;
- copyright and license identifier;
- access and redistribution terms;
- required attribution or notices;
- checksum and retrieval date;
- transformations and derived-artifact rules;
- whether redistribution is permitted or access must remain bring-your-own-license.

Restricted material, credentials, and proprietary executables are never committed to the public repository.
