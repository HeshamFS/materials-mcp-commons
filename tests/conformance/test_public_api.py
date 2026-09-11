from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from tools.freeze_public_api import build_public_api_contract

PUBLIC_ROOT = Path(__file__).parents[2]
CONTRACT_PATH = PUBLIC_ROOT / "conformance/public-api.json"
EXPECTED_TOOLS = [
    "materials_discover",
    "materials_inspect",
    "materials_activate",
    "materials_execute",
]


def _contract() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(CONTRACT_PATH.read_text(encoding="utf-8")))


def test_frozen_public_api_matches_actual_installed_package() -> None:
    assert build_public_api_contract() == _contract()


def test_frozen_protocol_surface_remains_bounded_and_host_trusted() -> None:
    contract = _contract()
    protocol = cast(dict[str, Any], contract["protocol"])
    tools = cast(list[dict[str, Any]], protocol["tools"])
    assert [tool["name"] for tool in tools] == EXPECTED_TOOLS
    execute = next(tool for tool in tools if tool["name"] == "materials_execute")
    properties = cast(dict[str, object], execute["input_schema"]["properties"])
    assert set(properties) == {"registration_ref", "capability_id", "payload"}
    assert {
        "owner_ref",
        "authorization",
        "policy",
        "state_root",
        "event_sink",
    }.isdisjoint(properties)


def test_frozen_surface_identifies_release_profiles_and_console_command() -> None:
    contract = _contract()
    assert contract["distribution"] == "materials-mcp-commons"
    assert contract["distribution_version"] == "0.1.0a9"
    assert contract["stability"] == "production-alpha-plugin-proof"
    assert contract["profile_versions"] == ["0.1.0", "0.2.0"]
    assert contract["console_scripts"] == {
        "materials-mcp-scaffold": "materials_mcp_commons.authoring:scaffold_main"
    }
