"""Materials MCP Commons engine package."""

from importlib.metadata import version

from .contracts import ContractRegistry
from .errors import CommonsError, ContractError, LifecycleError
from .lifecycle import (
    Activation,
    CapabilityCard,
    CapabilityDetail,
    LifecyclePolicy,
    LifecycleRegistry,
    Registration,
)
from .manifest import Capability, Effect, LoadedManifest, ManifestLoader, SchemaResource

__version__: str = version("materials-mcp-commons")

__all__ = (
    "Activation",
    "Capability",
    "CapabilityCard",
    "CapabilityDetail",
    "CommonsError",
    "ContractError",
    "ContractRegistry",
    "Effect",
    "LifecycleError",
    "LifecyclePolicy",
    "LifecycleRegistry",
    "LoadedManifest",
    "ManifestLoader",
    "Registration",
    "SchemaResource",
    "__version__",
)
