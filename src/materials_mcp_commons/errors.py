from __future__ import annotations


class CommonsError(Exception):
    """Base class for typed engine failures."""

    code: str

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ContractError(CommonsError):
    """A profile, schema, JSON, or manifest contract failed closed."""


class LifecycleError(CommonsError):
    """A catalog registration or activation transition was rejected."""


class DispatchError(CommonsError):
    """A dispatch request or handler binding was invalid before execution."""


class RunStoreError(CommonsError):
    """Durable run, provenance, or artifact state failed closed."""


class PolicyError(CommonsError):
    """Planning, approval, permission, quota, or audit policy failed closed."""


class ContextError(CommonsError):
    """Context measurement, projection, or certification failed closed."""


class AuthoringError(CommonsError):
    """Workspace scaffolding or declarative package authoring failed closed."""


class PluginConformanceError(CommonsError):
    """Plugin conformance, compatibility, or reference generation failed closed."""


class HostError(CommonsError):
    """Protocol-host composition or operational telemetry failed closed."""


class StateRecoveryError(CommonsError):
    """Durable engine state inspection, snapshot, or restoration failed closed."""
