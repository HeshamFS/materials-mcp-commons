# Durable state recovery

`StateRecovery` protects the two SQLite databases owned by the engine: durable run/provenance metadata and policy/authorization/audit metadata. It does not silently choose locations. Source, snapshot, and restore roots must be explicit direct paths; symbolic links and indirect paths are rejected.

## Snapshot contract

`create_snapshot(state_root, destination)` requires both current database files and a destination that does not exist. It:

1. checks the source schema versions and SQLite integrity;
2. uses SQLite's online backup API to create a consistent copy of each database;
3. repeats integrity and foreign-key checks on each copy;
4. records exact schema versions, sizes, and SHA-256 digests in `snapshot.json`; and
5. renames a private staging directory into the requested destination only after the full set passes.

The two databases are individually consistent but are not one cross-database transaction. Quiesce run and policy mutations when a recovery point must represent one coordinated operational instant.

`RecoveryLimits` bounds the manifest and database sizes accepted during inspection and restore. Raise the database limit explicitly for a larger real deployment after checking available disk, snapshot duration, and recovery objectives.

## Inspection and restore

`inspect_snapshot(snapshot_root)` requires the exact two databases plus the manifest. It rejects extra members, missing members, symbolic links, malformed JSON, unsupported schema versions, failed SQLite integrity/foreign-key checks, and metadata or checksum drift. Policy database schema 1 remains an accepted snapshot, inspection, and recovery input for the a12 transition, so an operator can capture a rollback point before opening the store with a12. The restored database migrates transactionally to schema 2 when `PolicyEngine` first opens it. Consumed schema-1 receipts become `legacy-closed`, because the older store cannot prove whether they already invoked a handler. Their approvals and reserved quota are intentionally not refunded.

`restore(snapshot_root, target_state_root)` first performs the complete inspection, then copies and revalidates both databases into a private staging directory. The target must not exist. Successful restore creates a fresh state root; it never replaces or merges live state.

After restore, reopen `PolicyEngine` first so its audit chain is verified, then reopen `RunStore`. Use `recover_incomplete(owner_ref)` to enumerate queued/running work and reconcile each item with its actual backend before resuming or cancelling it.

## Artifact boundary

The state snapshot contains artifact manifests, provenance records, and relative artifact paths, but not the artifact bytes stored beneath the separately configured artifact root. Back up that root with storage-native versioning or snapshots at the same quiesced recovery point. Preserve paths and bytes exactly: `RunStore.artifact` verifies the recorded SHA-256 when an artifact is retrieved.

A database restore without its matching artifact snapshot may recover run history but cannot make missing artifact content available. Do not mark such a recovery complete until referenced artifacts have passed their hash checks or have been explicitly recorded as unavailable.

See the [operations runbook](operations-runbook.md) for the recovery sequence and rollback rules.
