from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, cast

import pytest

from tests.contracts.support import PUBLIC_ROOT, load_json
from tools.run_conformance import ConformanceFailure, build_report, main, serialize_report

SUITE_PATH = PUBLIC_ROOT / "conformance" / "engine-suite.json"
REPORT_PATH = PUBLIC_ROOT / "conformance" / "engine-report.json"
M1_SUITE_PATH = PUBLIC_ROOT / "conformance" / "m1-suite.json"
M1_REPORT_PATH = PUBLIC_ROOT / "conformance" / "m1-report.json"


def test_committed_report_exactly_matches_a_fresh_run() -> None:
    assert build_report(SUITE_PATH) == load_json(REPORT_PATH)


def test_m1_evidence_snapshot_remains_byte_frozen() -> None:
    import hashlib

    assert hashlib.sha256(M1_SUITE_PATH.read_bytes()).hexdigest() == (
        "039b52bf114ad68a9ba9885f042b4dff5f664be26175c1937ca106ad03996911"
    )
    assert hashlib.sha256(M1_REPORT_PATH.read_bytes()).hexdigest() == (
        "7a6a8b4eb75ce603f8068628c4ada97d242e02607c6221ba965f53f7fcf938f8"
    )


def test_report_serialization_is_byte_deterministic() -> None:
    first = serialize_report(build_report(SUITE_PATH))
    second = serialize_report(build_report(SUITE_PATH))
    assert first == second
    assert first.encode("utf-8") == REPORT_PATH.read_bytes()


def test_changed_profile_surface_fails_closed(tmp_path: Path) -> None:
    suite = copy.deepcopy(load_json(SUITE_PATH))
    profiles = cast(list[dict[str, Any]], suite["profiles"])
    profiles[0]["schema_index_sha256"] = "0" * 64
    altered_path = tmp_path / "altered-suite.json"
    altered_path.write_text(json.dumps(suite), encoding="utf-8")

    with pytest.raises(ConformanceFailure, match="schema-index digest differs"):
        build_report(altered_path)


def test_cli_stdout_is_the_committed_report(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--suite", str(SUITE_PATH)]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.encode("utf-8") == REPORT_PATH.read_bytes()
