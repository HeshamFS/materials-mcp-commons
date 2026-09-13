# Contract-test corpora

Contract evidence is split by purpose so generated rejection inputs cannot be mistaken for scientific evidence:

- `positive-real/` accepts only registered, provenance-traceable real records with rights and integrity metadata.
- `negative-generated/` accepts deliberately invalid or adversarial inputs only when the asserted outcome is rejection, containment, or safe failure.

The positive corpus contains one checksummed source record, its direct 0.1.0 ResultBundle, a lossless 0.2.0 migration, and a bounded compact projection. The negative corpus contains generated rejection cases only. These corpora exercise schema validation, provenance, and rejection behavior.

## What the executable checks cover

- Draft 2020-12 meta-validation and exact path-derived root identifiers for 0.1.0 and 0.2.0
- byte-level immutability of 0.1.0 against its publication commit and fallback digest manifest
- local-only reference resolution with network retrieval denied
- schema-index completeness and byte-level SHA-256 parity
- explicit successor compatibility, lossless identifier migration, and resource partitioning
- compact-result source linkage, subset integrity, omission accounting, and declared byte budget
- context budget ceilings and cross-field ordering
- strict JSON parsing, including duplicate-key and non-finite-number rejection
- core validation followed by exact-schema extension validation
- integrity, rights, transformation, and internal-link checks for the real record
- exact projection of selected source fields without invented numerical output
- deterministic rejection of every generated negative case

Run the contract suite from the repository root:

```console
uv sync --locked --all-groups
uv run pytest tests/contracts
```

See [`positive-real/README.md`](positive-real/README.md) and [`negative-generated/README.md`](negative-generated/README.md) for the inclusion rules. The public contract model is described in [`../../docs/contracts.md`](../../docs/contracts.md).
