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
