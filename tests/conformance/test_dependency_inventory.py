from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from tools.build_dependency_inventory import build_inventory

PUBLIC_ROOT = Path(__file__).parents[2]


def test_installed_production_dependency_and_license_inventory_is_current() -> None:
    if sys.version_info[:2] != (3, 12):
        pytest.skip("Release dependency inventories are pinned to Python 3.12")
    platform_name = "windows" if sys.platform == "win32" else "linux"
    expected_path = PUBLIC_ROOT / f"conformance/dependency-inventory-{platform_name}-py312.json"
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    assert build_inventory() == expected
    assert expected["scopes"]["base"]
    assert expected["scopes"]["mcp-host"]
    assert all(package["license"] for scope in expected["scopes"].values() for package in scope)
