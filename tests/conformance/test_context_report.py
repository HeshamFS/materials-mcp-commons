from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from tools.run_context_benchmark import build_context_report, serialize_context_report

PUBLIC_ROOT = Path(__file__).parents[2]
REPORT_PATH = PUBLIC_ROOT / "conformance/context-engine-report.json"


def test_context_report_matches_actual_committed_engine_evidence() -> None:
    expected = cast(dict[str, object], json.loads(REPORT_PATH.read_text(encoding="utf-8")))
    actual = build_context_report(PUBLIC_ROOT)
    assert actual == expected
    assert serialize_context_report(actual) == serialize_context_report(
        build_context_report(PUBLIC_ROOT)
    )
