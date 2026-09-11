from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

from materials_mcp_commons import (
    DISCOVER_CAPABILITY_ID,
    ArtifactAttachment,
    CapabilityDetail,
    ContractRegistry,
    LifecycleRegistry,
    LoadedManifest,
    RunOwner,
    RunSnapshot,
    RunStore,
)

PUBLIC_ROOT = Path(__file__).parents[2]
NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)
OWNER = RunOwner("urn:materials-mcp:owner:project-runtime-tests", "project")


def _source_record() -> tuple[Path, dict[str, object], str]:
    suite = PUBLIC_ROOT / "conformance" / "engine-suite.json"
    report = PUBLIC_ROOT / "conformance" / "engine-report.json"
    suite_digest = hashlib.sha256(suite.read_bytes()).hexdigest()
    report_digest = hashlib.sha256(report.read_bytes()).hexdigest()
    source_ref = f"urn:materials-mcp:source:engine-suite:{suite_digest}"
    provenance: dict[str, object] = {
        "provenance_ref": f"urn:materials-mcp:provenance:engine-report:{report_digest}",
        "activity_ref": "replaced-with-run-ref",
        "activity_type": "analysis",
        "started_at": "2026-09-11T12:00:00Z",
        "ended_at": "2026-09-11T12:02:00Z",
        "producer": {
            "producer_ref": "urn:materials-mcp:producer:commons-conformance",
            "name": "Materials MCP Commons conformance runner",
            "version": "0.1.0a3",
        },
        "inputs": [source_ref],
        "parameters": [],
        "environment": {
            "status": "reported",
            "software": [{"name": "materials-mcp-commons", "version": "0.1.0a3"}],
            "platform": "Declared local Python environment",
        },
        "sources": [
            {
                "source_ref": source_ref,
                "source_type": "other",
                "title": "Committed Materials MCP Commons engine conformance suite",
                "uri": source_ref,
                "version": suite_digest,
                "retrieved_at": "2026-09-11T12:00:00Z",
                "rights": {
                    "basis": "license",
                    "identifier": "CC-BY-4.0",
                    "uri": "https://creativecommons.org/licenses/by/4.0/",
                    "redistribution": "permitted",
                    "attribution": "Hesham Salama",
                },
                "size_bytes": suite.stat().st_size,
                "sha256": suite_digest,
                "transformations": [
                    {
                        "operation": "other",
                        "source_locator": "Complete committed suite",
                        "target_pointer": "",
                        "note": "Executed by the checked-in deterministic conformance runner.",
                    }
                ],
                "citation_refs": [
                    "https://schemas.autonomouslab.io/materials-mcp/0.1.0/schema-index.json"
                ],
            }
        ],
    }
    return report, provenance, report_digest


def _target(loaded_manifest: LoadedManifest) -> CapabilityDetail:
    lifecycle = LifecycleRegistry()
    lifecycle.register(loaded_manifest)
    return lifecycle.inspect(DISCOVER_CAPABILITY_ID)


def test_real_engine_record_persists_artifact_provenance_and_deltas(
    tmp_path: Path,
    loaded_manifest: LoadedManifest,
    contract_registry: ContractRegistry,
) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir()
    target = _target(loaded_manifest)
    request_ref = "urn:materials-mcp:request:real-engine-conformance-record"
    with RunStore(state_root, PUBLIC_ROOT, contract_registry) as store:
        created = store.create_run(
            request_ref=request_ref,
            target=target,
            owner=OWNER,
            created_at=NOW,
        )
        assert created == store.create_run(
            request_ref=request_ref,
            target=target,
            owner=OWNER,
            created_at=NOW,
        )
        running = store.transition(
            created.run_ref,
            OWNER.owner_ref,
            expected_sequence=0,
            state="running",
            updated_at=NOW + timedelta(minutes=1),
            progress=(0.5, "Validated the committed suite and generated the report."),
        )
        report, provenance, report_digest = _source_record()
        provenance["activity_ref"] = created.run_ref
        attached = store.attach_artifact(
            created.run_ref,
            OWNER.owner_ref,
            expected_sequence=running.sequence,
            updated_at=NOW + timedelta(minutes=2),
            relative_path=report.relative_to(PUBLIC_ROOT).as_posix(),
            uri=f"urn:materials-mcp:artifact-source:engine-report:{report_digest}",
            media_type="application/json",
            role="report",
            access_scope="workspace",
            provenance=provenance,
        )
        assert isinstance(attached, ArtifactAttachment)
        fetched = store.artifact(attached.artifact.artifact_ref, OWNER.owner_ref)
        assert fetched.to_document()["sha256"] == report_digest
        assert fetched.provenance_document()["activity_ref"] == created.run_ref
        succeeded = store.transition(
            created.run_ref,
            OWNER.owner_ref,
            expected_sequence=attached.run.sequence,
            state="succeeded",
            updated_at=NOW + timedelta(minutes=3),
            progress=(1.0, "Committed conformance report verified."),
            result_ref=attached.artifact.artifact_ref,
        )
        assert [
            delta.sequence
            for delta in store.deltas(created.run_ref, OWNER.owner_ref, after_sequence=0)
        ] == [1, 2, 3]
        assert succeeded.to_document()["artifact_refs"] == [attached.artifact.artifact_ref]

    with RunStore(state_root, PUBLIC_ROOT, contract_registry) as reopened:
        recovered = reopened.latest(created.run_ref, OWNER.owner_ref)
        assert recovered.state == "succeeded"
        assert recovered.sequence == 3
        contract_registry.validate(
            f"{contract_registry.canonical_base}run-record.schema.json",
            recovered.to_document(),
        )


def test_reconnect_recovers_and_cancels_owned_nonterminal_run(
    tmp_path: Path,
    loaded_manifest: LoadedManifest,
    contract_registry: ContractRegistry,
) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir()
    target = _target(loaded_manifest)
    with RunStore(state_root, PUBLIC_ROOT, contract_registry) as first:
        created = first.create_run(
            request_ref="urn:materials-mcp:request:real-engine-reconnect",
            target=target,
            owner=OWNER,
            created_at=NOW,
        )
        first.transition(
            created.run_ref,
            OWNER.owner_ref,
            expected_sequence=0,
            state="running",
            updated_at=NOW + timedelta(seconds=1),
        )

    with RunStore(state_root, PUBLIC_ROOT, contract_registry) as reopened:
        incomplete = reopened.recover_incomplete(OWNER.owner_ref)
        assert len(incomplete) == 1
        assert incomplete[0].state == "running"
        cancelled = reopened.cancel(
            created.run_ref,
            OWNER.owner_ref,
            expected_sequence=1,
            updated_at=NOW + timedelta(seconds=2),
        )
        assert isinstance(cancelled, RunSnapshot)
        assert cancelled.state == "cancelled"
        assert reopened.recover_incomplete(OWNER.owner_ref) == ()
