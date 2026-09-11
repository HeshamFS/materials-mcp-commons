# Generated rejection corpus

This corpus is reserved for clearly labeled generated invalid, boundary, fuzz, property-based, migration, and security inputs. Every case must assert rejection, containment, or safe failure.

Content here is never a positive example, scientific reference output, benchmark result, demonstration result, or validation claim.

## Current cases

| Case | Required outcome |
|---|---|
| `NG-0001-number-without-unit.json` | Reject a numeric scientific value without a unit |
| `NG-0002-artifact-bad-digest.json` | Reject a malformed SHA-256 artifact digest |
| `NG-0003-r3-plan-without-approval.json` | Reject an external-write plan with an invalid approval posture |
| `NG-0004-unknown-core-field.json` | Reject silent core-schema drift; the case mutates a deep copy of the real positive record |
| `NG-0005-manifest-command-field.json` | Reject undeclared executable-command material at the declarative manifest boundary |
| `NG-0006-unregistered-extension.json` | Reject an extension absent from the exact offline schema registry |
| `NG-0007-duplicate-key.json.txt` | Reject duplicate JSON object members during strict parsing |
| `NG-0008-non-finite-number.json.txt` | Reject a non-finite JSON number during strict parsing |
| `NG-0009-context-too-many-active-schemas.json` | Reject an active-schema ceiling above the profile limit |
| `NG-0010-context-inline-token-ceiling.json` | Reject an inline-result token ceiling above the profile limit |
| `NG-0011-compact-observed-over-limit.json` | Reject a measured compact result larger than its declared budget |
| `NG-0012-context-target-over-maximum.json` | Reject an active-schema target above its declared maximum |
| `NG-0013-context-fraction-order.json` | Reject out-of-order context target, warning, and intervention fractions |

Each case declares `origin: generated`, `role: negative`, its purpose, and the expected rejection phase. The `.json.txt` suffix preserves intentionally non-interoperable JSON text without presenting it as an ordinary JSON document.
