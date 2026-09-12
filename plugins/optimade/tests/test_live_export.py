from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import cast

import pytest

from materials_mcp_optimade import (
    EXPORT_PROVENANCE_SCHEMA,
    PROFILE_VERSION,
    ExportError,
    OptimadeExporter,
)
from materials_mcp_optimade.contracts import load_declarative_manifest

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("MATERIALS_MCP_LIVE") != "1",
        reason="Set MATERIALS_MCP_LIVE=1 to run fixed-provider live evidence",
    ),
]

PLUGIN_ROOT = Path(__file__).parents[1]
PUBLIC_ROOT = PLUGIN_ROOT.parents[1]
PROFILE_ROOT = PUBLIC_ROOT / "schemas" / PROFILE_VERSION
ARTIFACT_SCHEMA = "https://schemas.autonomouslab.io/materials-mcp/0.2.0/artifact.schema.json"
NOMAD_RECORD = "C1YUj8LENValWcMQ3Y0aUH5acDmX"


def _validate(artifact: dict[str, object]) -> dict[str, object]:
    manifest = load_declarative_manifest(PROFILE_ROOT)
    manifest.validate(ARTIFACT_SCHEMA, artifact)
    extensions = cast(dict[str, dict[str, object]], artifact["extensions"])
    extension = extensions[EXPORT_PROVENANCE_SCHEMA]
    manifest.validate(EXPORT_PROVENANCE_SCHEMA, extension)
    return extension


def _payload(destination: str, export_format: str) -> dict[str, object]:
    return {
        "provider_id": "nmd",
        "database_id": "nmd",
        "entry_type": "structures",
        "entry_id": NOMAD_RECORD,
        "format": export_format,
        "destination": destination,
        "overwrite": False,
    }


def test_live_native_export_is_exact_validated_provider_bytes(tmp_path: Path) -> None:
    artifact = OptimadeExporter(tmp_path).export(
        _payload("nomad-record.optimade.json", "optimade-json"),
        request_ref="urn:materials-mcp:request:live-native-export",
    )
    extension = _validate(artifact)
    destination = tmp_path / "nomad-record.optimade.json"
    content = destination.read_bytes()
    source = cast(dict[str, object], extension["source"])

    assert json.loads(content)["data"]["id"] == NOMAD_RECORD
    assert artifact["sha256"] == hashlib.sha256(content).hexdigest()
    assert artifact["sha256"] == source["sha256"]
    assert artifact["size_bytes"] == source["size_bytes"]
    assert source["projection"] == "complete"
    assert cast(dict[str, object], extension["rights"])["identifier"] == "CC-BY-4.0"


def test_live_cif_export_has_real_lattice_sites_attribution_and_provenance(
    tmp_path: Path,
) -> None:
    artifact = OptimadeExporter(tmp_path).export(
        _payload("nomad-record.cif", "cif"),
        request_ref="urn:materials-mcp:request:live-cif-export",
    )
    extension = _validate(artifact)
    content = (tmp_path / "nomad-record.cif").read_text(encoding="utf-8")
    transformation = cast(dict[str, object], extension["transformation"])

    assert artifact["media_type"] == "chemical/x-cif"
    assert "_cell_length_a" in content
    assert "_atom_site_fract_x" in content
    assert "# Rights: CC-BY-4.0" in content
    assert "# Citation: https://doi.org/10.21105/joss.05388" in content
    assert transformation["operation"] == "optimade-cartesian-to-cif"


def test_live_source_hash_precondition_fails_before_persistence(tmp_path: Path) -> None:
    payload = _payload("must-not-exist.json", "optimade-json")
    payload["expected_response_sha256"] = "0" * 64

    with pytest.raises(ExportError) as captured:
        OptimadeExporter(tmp_path).export(
            payload,
            request_ref="urn:materials-mcp:request:live-hash-precondition",
        )
    assert captured.value.code == "source-precondition-failed"
    assert not (tmp_path / "must-not-exist.json").exists()
