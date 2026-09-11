from __future__ import annotations

from pathlib import Path

import pytest

from materials_mcp_commons import ContractRegistry, LoadedManifest, ManifestLoader

PUBLIC_ROOT = Path(__file__).parents[2]
PROFILE_ROOT = PUBLIC_ROOT / "schemas" / "0.2.0"
PACKAGE_ROOT = PUBLIC_ROOT / "tests" / "runtime" / "positive-project" / "engine-lifecycle"


@pytest.fixture(scope="session")
def contract_registry() -> ContractRegistry:
    return ContractRegistry.from_directory(PROFILE_ROOT, "0.2.0")


@pytest.fixture(scope="session")
def loaded_manifest(contract_registry: ContractRegistry) -> LoadedManifest:
    return ManifestLoader(contract_registry).load(PACKAGE_ROOT)
