from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator

from tools.freeze_public_api import build_public_api_contract

PUBLIC_ROOT = Path(__file__).parents[2]
CONTRACT_PATH = PUBLIC_ROOT / "conformance/public-api.json"
EXPECTED_TOOLS = [
    "materials_discover",
    "materials_inspect",
    "materials_activate",
    "materials_execute",
]
EXPECTED_ERROR_CODES = [
    "ACTIVATION_FAILED",
    "ASYNC_DISPATCH_REQUIRED",
    "AUTHORIZATION_DENIED",
    "AUTHORIZATION_RESOLVER_FAILED",
    "DISCOVERY_FAILED",
    "EFFECT_POLICY_REQUIRED",
    "EXECUTION_FAILED",
    "HANDLER_FAILED",
    "HANDLER_MODE_MISMATCH",
    "HANDLER_NOT_BOUND",
    "HANDLER_REJECTED",
    "INPUT_SCHEMA_REJECTED",
    "INSPECTION_FAILED",
    "PROFILE_INCOMPATIBLE",
    "RESULT_SCHEMA_REJECTED",
    "TARGET_UNAVAILABLE",
]


def _contract() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(CONTRACT_PATH.read_text(encoding="utf-8")))


def _schema_accepts(schema: dict[str, Any], instance: object) -> bool:
    validator = cast(Any, Draft202012Validator(schema))
    return cast(bool, validator.is_valid(instance))


def test_frozen_public_api_matches_actual_installed_package() -> None:
    assert build_public_api_contract() == _contract()


def test_frozen_protocol_surface_remains_bounded_and_host_trusted() -> None:
    contract = _contract()
    protocol = cast(dict[str, Any], contract["protocol"])
    tools = cast(list[dict[str, Any]], protocol["tools"])
    assert [tool["name"] for tool in tools] == EXPECTED_TOOLS
    assert protocol["error_codes"] == EXPECTED_ERROR_CODES
    assert all(tool["input_schema"]["additionalProperties"] is False for tool in tools)
    assert all(len(tool["output_schema"]["oneOf"]) == 2 for tool in tools)
    for tool in tools:
        definitions = cast(dict[str, Any], tool["output_schema"]["$defs"])
        assert definitions["_FailureOutput"]["additionalProperties"] is False
        success_name = next(name for name in definitions if name.endswith("Success"))
        assert definitions[success_name]["additionalProperties"] is False
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
    payload = cast(dict[str, object], cast(dict[str, Any], properties["payload"]))
    assert payload["additionalProperties"] is True


def test_frozen_protocol_outputs_reject_incomplete_mixed_and_invalid_errors() -> None:
    tools = cast(list[dict[str, Any]], _contract()["protocol"]["tools"])
    error = {
        "contract": (
            "https://schemas.autonomouslab.io/materials-mcp/0.2.0/structured-error.schema.json"
        ),
        "profile_version": "0.2.0",
        "error_ref": "urn:materials-mcp:error:test",
        "code": "DISCOVERY_FAILED",
        "stage": "discovery",
        "cause": "The operation was rejected.",
        "message": "The host operation failed closed.",
        "evidence": [{"kind": "other", "summary": "Contained failure evidence."}],
        "retryable": False,
        "next_action": "Correct the request.",
        "occurred_at": "2026-09-11T00:00:00Z",
    }
    success_by_tool: dict[str, dict[str, object]] = {
        "materials_discover": {"ok": True, "cards": []},
        "materials_inspect": {
            "ok": True,
            "registration_ref": "urn:materials-mcp:registration:test",
            "plugin_id": "org.example.test",
            "plugin_version": "0.1.0",
            "capability_id": "materials.test",
            "input_schema": "urn:materials-mcp:schema:input",
            "result_schema": "urn:materials-mcp:schema:result",
            "error_schema": "urn:materials-mcp:schema:error",
            "effect_tier": "R0",
            "supports_async": False,
        },
        "materials_activate": {
            "ok": True,
            "activation_ref": "urn:materials-mcp:activation:test",
            "capability_id": "materials.test",
            "registration_ref": "urn:materials-mcp:registration:test",
            "activated_at_turn": 1,
            "expires_at_turn": 2,
        },
        "materials_execute": {"ok": True, "result": {}},
    }
    for tool in tools:
        schema = cast(dict[str, Any], tool["output_schema"])
        success = success_by_tool[cast(str, tool["name"])]
        assert _schema_accepts(schema, success)
        assert _schema_accepts(schema, {"ok": False, "error": error})
        assert not _schema_accepts(schema, {"ok": True})
        assert not _schema_accepts(schema, {"ok": False})
        assert not _schema_accepts(schema, {**success, "error": error})
        assert not _schema_accepts(schema, {"ok": False, "error": {**error, "evidence": []}})
        assert not _schema_accepts(
            schema, {"ok": False, "error": {**error, "code": "NOT_A_PUBLIC_ERROR"}}
        )
    execute_schema = cast(
        dict[str, Any],
        next(tool for tool in tools if tool["name"] == "materials_execute")["output_schema"],
    )
    for result in cast(tuple[object, ...], ([], "scalar", None, 1, True)):
        assert _schema_accepts(execute_schema, {"ok": True, "result": result})


def test_frozen_python_surface_records_awaitability() -> None:
    exports = cast(list[dict[str, object]], _contract()["python"]["exports"])
    host = next(item for item in exports if item["name"] == "EngineMCPHost")
    members = cast(list[dict[str, Any]], host["members"])
    modes = {item["name"]: item["signature"]["callable_mode"] for item in members}
    assert modes["discover"] == "synchronous"
    assert modes["inspect"] == "synchronous"
    assert modes["activate"] == "coroutine"
    assert modes["execute"] == "coroutine"


def test_frozen_surface_identifies_release_profiles_and_console_command() -> None:
    contract = _contract()
    assert contract["distribution"] == "materials-mcp-commons"
    assert contract["distribution_version"] == "0.1.0a13"
    assert contract["stability"] == "production-alpha-plugin-proof"
    assert contract["profile_versions"] == ["0.1.0", "0.2.0"]
    assert contract["console_scripts"] == {
        "materials-mcp-conformance": (
            "materials_mcp_commons.plugin_conformance:plugin_conformance_main"
        ),
        "materials-mcp-scaffold": "materials_mcp_commons.authoring:scaffold_main",
    }
