# Engine operations runbook

This runbook governs the current local/in-process and stdio host boundary. It is not a deployment recipe for anonymous or authenticated Streamable HTTP.

## Start and preflight

1. Install the exact released wheel, adding `[mcp-host]` only for an MCP process.
2. Create explicit existing contract, package, state, and artifact roots with least-privilege filesystem access.
3. Load the exact offline profile and only operator-selected package roots. Review manifest digests and effects before registration.
4. Bind handlers to exact registration/capability pairs. Construct `PolicyEngine` before any R1-R4 dispatcher and supply a trusted `AuthorizationResolver` only after the real approval path is ready.
5. Construct `EngineMCPHost` with an authenticated local owner reference. Attach an `OperationObserver` sink only if it honors the metadata-only contract.
6. Check `host.health()` in process. Expected status is `ready`; verify the exact profile and expected registration/binding counts without exposing the document publicly.
7. Start the official SDK stdio server. Keep all application and handler diagnostics off stdout.

## Routine monitoring

- Alert on sustained `failure` counts by operation and stable error code, unexpected `dropped_sink_events`, or a change in expected registration/binding counts.
- Treat `TARGET_UNAVAILABLE` as a lifecycle/registration/lease problem, `INPUT_SCHEMA_REJECTED` as caller-contract drift, `EFFECT_POLICY_REQUIRED` or `AUTHORIZATION_DENIED` as a fail-closed policy event, and `HANDLER_FAILED` as a private handler investigation.
- Do not add payloads, results, owner references, receipts, paths, or raw exceptions to the public operational event.
- A `ready` health snapshot proves only that the local composition can answer; it does not prove external backend availability or scientific validity.

## Graceful stop

1. Stop accepting new host calls.
2. Allow the currently serialized activation/execution transition to finish or record the actual interruption.
3. Reconcile queued/running records with `recover_incomplete` and the real backend.
4. Close `RunStore` and `PolicyEngine` so database handles are released.
5. Preserve operator diagnostics under their own access and retention policy.

## Backup

1. Quiesce policy and run mutations for a coordinated recovery point.
2. Create a new, non-existing state snapshot with `StateRecovery.create_snapshot`.
3. Immediately call `inspect_snapshot` and retain the manifest with the two database files.
4. Snapshot the separate artifact root with storage-native tooling at the same recovery point.
5. Store both sets under restricted, versioned, non-public access. The current manifest detects drift but is not a signature.

## Restore and rollback

1. Keep the failed/live roots unchanged for forensic comparison; select new state and artifact target roots.
2. Inspect the state snapshot before restore and verify the matching artifact backup independently.
3. Restore into a fresh state root. Restore artifact bytes into a fresh artifact root without changing relative paths.
4. Open `PolicyEngine` to verify its audit chain, then `RunStore` to verify run records.
5. Retrieve representative referenced artifacts so their recorded SHA-256 checks run.
6. Reconcile every incomplete run with its real backend before resuming, cancelling, or reissuing work.
7. Point a new host process at the recovered roots and verify health plus bounded discover/inspect behavior before admitting execution.
8. Roll back by stopping that process and selecting the prior untouched roots; never merge SQLite files or overwrite a live root.

## Incident response

- Identity or approval concern: stop effectful admission, preserve policy/audit state, rotate external credentials outside the engine, and investigate the authenticated host layer.
- State integrity failure: stop mutations, preserve the rejected files, restore only from a fully inspected snapshot, and do not edit a database to force it open.
- Artifact hash failure: quarantine the mismatching bytes, preserve the manifest/provenance record, restore the exact source bytes if available, and record the real loss if not.
- Dependency advisory: pause release/deployment changes, refresh the exact lock and license inventory, apply the narrowest compatible update, and rerun clean-install, protocol, and package gates.
- Scientific discrepancy: stop scientific claims for the affected capability. Protocol health and schema conformance do not authorize a scientific result.
