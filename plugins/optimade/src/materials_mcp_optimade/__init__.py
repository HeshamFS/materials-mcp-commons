"""Bounded OPTIMADE federation for Materials MCP Commons."""

from .client import OptimadeClient
from .config import PROVIDERS, ProviderConfig, RightsRecord, provider_config
from .contracts import (
    CAPABILITY_IDS,
    PLUGIN_ID,
    PLUGIN_VERSION,
    PROFILE_VERSION,
    SCHEMA_BASE,
    declarative_package_root,
    load_declarative_manifest,
)
from .errors import ExportError, OptimadeIntegrationError, ProviderProtocolError, TransportError
from .export import EXPORT_PROVENANCE_SCHEMA, OptimadeExporter
from .handlers import OptimadeHandlers, bind_handlers

__version__ = "0.1.0a1"

__all__ = [
    "CAPABILITY_IDS",
    "EXPORT_PROVENANCE_SCHEMA",
    "PLUGIN_ID",
    "PLUGIN_VERSION",
    "PROFILE_VERSION",
    "PROVIDERS",
    "SCHEMA_BASE",
    "ExportError",
    "OptimadeClient",
    "OptimadeExporter",
    "OptimadeHandlers",
    "OptimadeIntegrationError",
    "ProviderConfig",
    "ProviderProtocolError",
    "RightsRecord",
    "TransportError",
    "__version__",
    "bind_handlers",
    "declarative_package_root",
    "load_declarative_manifest",
    "provider_config",
]
