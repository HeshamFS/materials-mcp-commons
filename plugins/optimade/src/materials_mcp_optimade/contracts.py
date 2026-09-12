"""Exact package and contract identities for the OPTIMADE integration."""

from __future__ import annotations

import re
from pathlib import Path
from types import MappingProxyType
from typing import Final, TypeGuard

from materials_mcp_commons import ContractRegistry, LoadedManifest, ManifestLoader

PROFILE_VERSION: Final = "0.2.0"
PLUGIN_ID: Final = "https://schemas.autonomouslab.io/materials-mcp/plugins/optimade"
PLUGIN_VERSION: Final = "0.1.0-alpha.1"
SCHEMA_BASE: Final = f"{PLUGIN_ID}/0.1.0/"
OPTIMADE_CONTRACT_LINE: Final = "1.2"
OPTIMADE_BASELINE_VERSION: Final = "1.2.0"
_SUPPORTED_OPTIMADE_VERSION = re.compile(r"^1\.2\.(?:0|[1-9][0-9]*)$")

CAPABILITY_IDS = MappingProxyType(
    {
        "providers_list": f"{PLUGIN_ID}/providers/list",
        "providers_inspect": f"{PLUGIN_ID}/providers/inspect",
        "structures_search": f"{PLUGIN_ID}/structures/search",
        "structures_get": f"{PLUGIN_ID}/structures/get",
        "references_search": f"{PLUGIN_ID}/references/search",
        "references_get": f"{PLUGIN_ID}/references/get",
        "records_export": f"{PLUGIN_ID}/records/export",
    }
)


def is_supported_api_version(value: object) -> TypeGuard[str]:
    """Return whether ``value`` is a stable release in the verified 1.2 patch line."""

    return type(value) is str and _SUPPORTED_OPTIMADE_VERSION.fullmatch(value) is not None


def declarative_package_root() -> Path:
    """Return the installed checksum-bound declarative package directory."""

    return Path(__file__).resolve().parent / "declarative"


def load_declarative_manifest(profile_root: Path) -> LoadedManifest:
    """Load the package against an explicit exact profile directory."""

    contracts = ContractRegistry.from_directory(profile_root, PROFILE_VERSION)
    return ManifestLoader(contracts).load(declarative_package_root())
