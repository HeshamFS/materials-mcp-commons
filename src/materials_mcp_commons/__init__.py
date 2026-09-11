"""Materials MCP Commons engine package."""

from importlib.metadata import version

from .contracts import ContractRegistry
from .control import DISCOVER_CAPABILITY_ID, INSPECT_CAPABILITY_ID, EngineControlHandlers
from .dispatch import (
    Dispatcher,
    DispatchFailure,
    DispatchOutcome,
    DispatchRequest,
    DispatchSuccess,
    HandlerBinding,
    HandlerRequest,
)
from .errors import CommonsError, ContractError, DispatchError, LifecycleError, RunStoreError
from .lifecycle import (
    Activation,
    ActiveCapabilityTarget,
    CapabilityCard,
    CapabilityDetail,
    CapabilityTarget,
    LifecyclePolicy,
    LifecycleRegistry,
    Registration,
)
from .manifest import Capability, Effect, LoadedManifest, ManifestLoader, SchemaResource
from .runs import ArtifactAttachment, ArtifactSnapshot, RunOwner, RunSnapshot, RunStore

__version__: str = version("materials-mcp-commons")

__all__ = (
    "DISCOVER_CAPABILITY_ID",
    "INSPECT_CAPABILITY_ID",
    "Activation",
    "ActiveCapabilityTarget",
    "ArtifactAttachment",
    "ArtifactSnapshot",
    "Capability",
    "CapabilityCard",
    "CapabilityDetail",
    "CapabilityTarget",
    "CommonsError",
    "ContractError",
    "ContractRegistry",
    "DispatchError",
    "DispatchFailure",
    "DispatchOutcome",
    "DispatchRequest",
    "DispatchSuccess",
    "Dispatcher",
    "Effect",
    "EngineControlHandlers",
    "HandlerBinding",
    "HandlerRequest",
    "LifecycleError",
    "LifecyclePolicy",
    "LifecycleRegistry",
    "LoadedManifest",
    "ManifestLoader",
    "Registration",
    "RunOwner",
    "RunSnapshot",
    "RunStore",
    "RunStoreError",
    "SchemaResource",
    "__version__",
)
