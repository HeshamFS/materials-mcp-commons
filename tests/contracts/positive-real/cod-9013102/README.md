# Real contract record: COD 9013102, revision 291877

This directory contains a revision-pinned Crystallography Open Database (COD) record for silicon and a direct Materials MCP Profile 0.1.0 projection. It is positive contract evidence: it proves that a real, rights-recorded source can be represented and validated without fabricating numerical output.

It does not claim independent scientific validation of the source measurement or the projected values.

## Source and rights

| Item | Value |
|---|---|
| COD record | [9013102](https://www.crystallography.net/cod/9013102.html) |
| Immutable source | [`9013102.cif@291877`](https://www.crystallography.net/cod/9013102.cif@291877) |
| Revision | `291877` |
| Retrieved | `2026-09-04T22:45:08+02:00` |
| Media type | `chemical/x-cif` |
| Rights | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/); redistribution permitted |
| Requested acknowledgement | B. N. Dutta and the original structural-data sources |

The [COD licensing statement](https://www.crystallography.net/cod/licensing/) describes its database contents as dedicated to the public domain and asks users to acknowledge original authors. The source-data terms apply to [`source.cif`](source.cif), not to unrelated project material.

## Integrity

| Artifact | Size | SHA-256 |
|---|---:|---|
| Remote revision-pinned CIF | 5,190 bytes | `4ccd895a831a4d4539a687f23c03b8708a97fbb14fadbf9e43a22bb338b92176` |
| Repository mirror [`source.cif`](source.cif) | 5,191 bytes | `2645028926b3d4bed278417dc2812f8705bb23d792bcdcd2a7538f2a7c0e9cd8` |
| [`result-bundle.json`](result-bundle.json) | 12,136 bytes | `170cd7b9e00fe0ca55abcc129d09941668a6079be6f5fdb61bd91f9d58829c7c` |
| [`result-bundle-0.2.0.json`](result-bundle-0.2.0.json) | 12,136 bytes | `33e88c8890676a8d43f963f8598a8547df23f8bcafe7ba78e586ea4b2d59b35c` |
| [`compact-result-0.2.0.json`](compact-result-0.2.0.json) | 3,507 bytes | `8d23d98bbb9c0053a9ea5676f79f7e427c83c27db93de0a20440a7a8ed67b985` |

The repository mirror appends exactly one final LF for text-file normalization. Removing that LF reproduces the 5,190 source bytes and the remote digest.

[`registration.json`](registration.json) is the machine-readable source-rights, integrity, transformation, citation, and limitations record. [`registration-0.2.0.json`](registration-0.2.0.json) records the successor migration and compact-projection derivations.

## Direct projection

The result copies declared CIF fields without numerical conversion:

| Quantity | Projected value | Unit annotation |
|---|---:|---|
| Unit-cell lengths `a`, `b`, `c` | 5.4304 each | UCUM `Ao` (Å) |
| Unit-cell angles alpha, beta, gamma | 90 each | UCUM `deg` (°) |
| Unit-cell volume | 160.138 | UCUM `Ao3` (Å³) |
| Diffraction ambient temperature | 298.15 | UCUM `K` |

The unit identifiers annotate the units declared by the relevant IUCr CIF Core dictionary fields. The source also provides the chemical formula, sample origin, space-group number, Hermann-Mauguin symbol, and Hall symbol represented in the entity identifiers.

The associated scientific citation is B. N. Dutta, “Lattice constants and thermal expansion of silicon up to 900 C by X-ray method,” 1962, [DOI 10.1002/pssb.19620020803](https://doi.org/10.1002/pssb.19620020803).

## Successor migration and compact projection

The 0.2.0 ResultBundle changes only the exact profile version and contract identifier; the source-derived scientific content is byte-for-byte equivalent after those two fields are normalized. The compact result selects the first two properties and the source condition in source order, retains artifact/provenance/citation links, declares every omitted count, and measures its checked-in UTF-8 JSON representation against the context manifest's byte ceiling. It remains a projection of the rich result, never the authoritative record.

## Limitations and trust scope

- The selected scalar values contain no reported standard uncertainties.
- The source record contains no reflection observations.
- No computational backend or numerical scientific execution produced this fixture.
- The quality state is `not-assessed`.
- The fixture proves schema, provenance, rights, checksum, transformation, and internal-reference handling only. It is not a Validated scientific capability or a release claim.
