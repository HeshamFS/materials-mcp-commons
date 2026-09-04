# Contract-test corpora

Contract evidence is split by purpose so generated rejection inputs cannot be mistaken for scientific evidence:

- `positive-real/` accepts only registered, provenance-traceable real records with rights and integrity metadata.
- `negative-generated/` accepts deliberately invalid or adversarial inputs only when the asserted outcome is rejection, containment, or safe failure.

The current positive corpus contains one checksummed source record and a direct contract projection. The negative corpus contains eight generated rejection cases. Neither corpus is a substitute for later runtime, interoperability, or independent scientific-validation evidence.

## What the executable checks cover

- Draft 2020-12 meta-validation and exact path-derived root identifiers
- local-only reference resolution with network retrieval denied
- schema-index completeness and byte-level SHA-256 parity
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
