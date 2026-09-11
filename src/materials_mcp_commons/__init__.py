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
from .errors import (
    CommonsError,
    ContractError,
    DispatchError,
    LifecycleError,
    PolicyError,
    RunStoreError,
)
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
from .policy import (
    ApprovalRecord,
    AuditEvent,
    AuthorizationGrant,
    AuthorizationReceipt,
    OperationPlan,
    Permission,
    PolicyEngine,
    PolicySnapshot,
    QuotaCharge,
    QuotaLimit,
)
from .runs import ArtifactAttachment, ArtifactSnapshot, RunOwner, RunSnapshot, RunStore

__version__: str = version("materials-mcp-commons")

__all__ = (
    "DISCOVER_CAPABILITY_ID",
    "INSPECT_CAPABILITY_ID",
    "Activation",
    "ActiveCapabilityTarget",
    "ApprovalRecord",
    "ArtifactAttachment",
    "ArtifactSnapshot",
    "AuditEvent",
    "AuthorizationGrant",
    "AuthorizationReceipt",
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
    "OperationPlan",
    "Permission",
    "PolicyEngine",
    "PolicyError",
    "PolicySnapshot",
    "QuotaCharge",
    "QuotaLimit",
    "Registration",
    "RunOwner",
    "RunSnapshot",
    "RunStore",
    "RunStoreError",
    "SchemaResource",
    "__version__",
)
