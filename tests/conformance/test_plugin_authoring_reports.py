from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.run_plugin_conformance import (
    build_capability_reference,
    build_matrix_report,
    build_plugin_report,
    main,
)

PUBLIC_ROOT = Path(__file__).parents[2]


def test_actual_engine_plugin_report_matches_committed_bytes() -> None:
    expected = (PUBLIC_ROOT / "conformance/engine-plugin-report.json").read_bytes()
    first = build_plugin_report(PUBLIC_ROOT)
    second = build_plugin_report(PUBLIC_ROOT)
    assert first == second
    assert first.encode() == expected
    assert '"result": "pass"' in first
    assert '"scope": "exact-profile-declarative-only"' in first


def test_versioned_authoring_matrix_matches_committed_bytes() -> None:
    expected = (PUBLIC_ROOT / "conformance/authoring-matrix-report.json").read_bytes()
    first = build_matrix_report(PUBLIC_ROOT)
    second = build_matrix_report(PUBLIC_ROOT)
    assert first == second
    assert first.encode() == expected
    assert json.loads(first)["result"] == "pass"
    assert '"from_profile": "0.1.0"' in first
    assert '"to_profile": "0.2.0"' in first


def test_capability_reference_matches_committed_bytes_and_cli(
    capsys: pytest.CaptureFixture[str],
) -> None:
    expected = (PUBLIC_ROOT / "conformance/engine-capabilities.md").read_bytes()
    rendered = build_capability_reference(PUBLIC_ROOT)
    assert rendered.encode() == expected
    assert main(["reference"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == rendered
