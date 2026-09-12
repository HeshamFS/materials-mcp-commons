"""Engine bindings for the seven frozen OPTIMADE capabilities."""

from __future__ import annotations

from dataclasses import dataclass

from materials_mcp_commons import Dispatcher, HandlerBinding, HandlerRequest

from .client import OptimadeClient
from .contracts import CAPABILITY_IDS
from .errors import OptimadeIntegrationError
from .export import OptimadeExporter


@dataclass(frozen=True)
class OptimadeHandlers:
    """Concrete handlers with no lifecycle or policy authority of their own."""

    client: OptimadeClient
    exporter: OptimadeExporter

    @staticmethod
    def _require_capability(request: HandlerRequest, name: str) -> None:
        if request.capability_id != CAPABILITY_IDS[name]:
            raise OptimadeIntegrationError(
                "handler-capability-mismatch",
                "Handler invocation does not match its bound capability",
            )

    def providers_list(self, request: HandlerRequest) -> object:
        self._require_capability(request, "providers_list")
        return self.client.list_providers(request.payload)

    def providers_inspect(self, request: HandlerRequest) -> object:
        self._require_capability(request, "providers_inspect")
        return self.client.inspect_provider(request.payload)

    def structures_search(self, request: HandlerRequest) -> object:
        self._require_capability(request, "structures_search")
        return self.client.search_structures(request.payload)

    def structures_get(self, request: HandlerRequest) -> object:
        self._require_capability(request, "structures_get")
        return self.client.get_structure(request.payload)

    def references_search(self, request: HandlerRequest) -> object:
        self._require_capability(request, "references_search")
        return self.client.search_references(request.payload)

    def references_get(self, request: HandlerRequest) -> object:
        self._require_capability(request, "references_get")
        return self.client.get_reference(request.payload)

    def records_export(self, request: HandlerRequest) -> object:
        self._require_capability(request, "records_export")
        return self.exporter.export(request.payload, request_ref=request.request_ref)


def bind_handlers(
    dispatcher: Dispatcher,
    registration_ref: str,
    handlers: OptimadeHandlers,
) -> tuple[HandlerBinding, ...]:
    """Bind every frozen capability to one exact lifecycle registration."""

    methods = {
        "providers_list": handlers.providers_list,
        "providers_inspect": handlers.providers_inspect,
        "structures_search": handlers.structures_search,
        "structures_get": handlers.structures_get,
        "references_search": handlers.references_search,
        "references_get": handlers.references_get,
        "records_export": handlers.records_export,
    }
    return tuple(
        dispatcher.bind(registration_ref, CAPABILITY_IDS[name], methods[name])
        for name in CAPABILITY_IDS
    )


__all__ = ["OptimadeHandlers", "bind_handlers"]
