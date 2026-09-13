# Scientific evidence policy

Scientific trust is attached to a versioned capability and its evidence, not to a repository or successful API call.

## Trust levels

- **Conformant** — protocol, schema, lifecycle, context, and deterministic inventory requirements pass.
- **Verified** — Conformant plus security, packaging, permissions, maintenance, supply-chain, and interoperability evidence.
- **Validated** — Verified plus real scientific reference cases, declared tolerances, clean replay, and applicability and quality criteria.

Control-plane services without a meaningful numerical scientific claim may be Conformant or Verified; they are not labeled Validated.

## Real-data requirement

Positive examples, demonstrations, benchmarks, integrations, golden cases, numerical comparisons, and release claims use real, provenance-traceable scientific data and real systems. Each case records source, license or access rights, checksum, transformations, version, environment, conditions, units, quality criteria, and limitations as applicable.

Toy datasets, mocked scientific backends, mocked schedulers, emulators presented as systems, and fabricated numerical outputs are not scientific or release evidence.

## Negative and adversarial tests

Deliberately generated invalid, boundary, fuzz, property-based, migration, and security inputs are permitted only when the expected outcome is rejection, containment, or safe failure. They are isolated from positive scientific corpora and never serve as scientific reference outputs.
