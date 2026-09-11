from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from .dispatch import HandlerRequest
from .lifecycle import LifecycleRegistry

DISCOVER_CAPABILITY_ID = "https://schemas.autonomouslab.io/materials-mcp/engine/discover"
INSPECT_CAPABILITY_ID = "https://schemas.autonomouslab.io/materials-mcp/engine/inspect"


@dataclass(frozen=True)
class EngineControlHandlers:
    """Actual handlers for the engine's own read-only lifecycle capabilities."""

    lifecycle: LifecycleRegistry

    def discover(self, request: HandlerRequest) -> object:
        query_value = request.payload.get("query", "")
        limit_value = request.payload.get("limit")
        query = cast(str, query_value)
        limit = cast(int | None, limit_value)
        cards = self.lifecycle.discover(query, limit=limit)
        return {
            "cards": [
                {
                    "capability_id": card.capability_id,
                    "title": card.title,
                    "description": card.description,
                    "effect_tier": card.effect_tier,
                    "supports_async": card.supports_async,
                }
                for card in cards
            ]
        }

    def inspect(self, request: HandlerRequest) -> object:
        capability_id = cast(str, request.payload["capability_id"])
        detail = self.lifecycle.inspect(capability_id)
        capability = detail.capability
        return {
            "registration_ref": detail.registration_ref,
            "plugin_id": detail.plugin_id,
            "plugin_version": detail.plugin_version,
            "capability_id": capability.capability_id,
            "input_schema": capability.input_schema,
            "result_schema": capability.result_schema,
            "error_schema": capability.error_schema,
        }
