"""Typed, bounded failures for the OPTIMADE integration."""

from __future__ import annotations

from materials_mcp_commons import CommonsError


class OptimadeIntegrationError(CommonsError):
    """A reviewed integration boundary failed closed."""


class TransportError(OptimadeIntegrationError):
    """A fixed HTTPS request failed without exposing provider response content."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        http_status: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(code, message)
        self.http_status = http_status
        self.retryable = retryable


class ProviderProtocolError(OptimadeIntegrationError):
    """A provider response violated the selected OPTIMADE contract or local bounds."""


class ExportError(OptimadeIntegrationError):
    """A rights, conversion, or bounded local-persistence check failed closed."""
