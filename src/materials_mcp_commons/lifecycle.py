from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from threading import RLock
from typing import cast

from .errors import LifecycleError
from .manifest import Capability, LoadedManifest

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def _required_mapping(document: Mapping[str, object], key: str) -> dict[str, object]:
    value = document.get(key)
    if not isinstance(value, dict):
        raise LifecycleError("invalid-context-policy", f"Context field {key} must be an object")
    return cast(dict[str, object], value)


def _required_int(document: Mapping[str, object], key: str) -> int:
    value = document.get(key)
    if type(value) is not int:
        raise LifecycleError("invalid-context-policy", f"Context field {key} must be an integer")
    return value


@dataclass(frozen=True)
class LifecyclePolicy:
    max_discovery_cards: int = 5
    max_active_capabilities: int = 8
    default_lease_turns: int = 20
    max_lease_turns: int = 100
    max_card_description_chars: int = 512

    def __post_init__(self) -> None:
        if not 1 <= self.max_discovery_cards <= 5:
            raise LifecycleError("invalid-policy", "Discovery-card limit must be between 1 and 5")
        if not 1 <= self.max_active_capabilities <= 8:
            raise LifecycleError(
                "invalid-policy", "Active-capability limit must be between 1 and 8"
            )
        if not 1 <= self.default_lease_turns <= self.max_lease_turns <= 100:
            raise LifecycleError("invalid-policy", "Lease limits are inconsistent")
        if not 1 <= self.max_card_description_chars <= 4096:
            raise LifecycleError("invalid-policy", "Card-description limit is invalid")

    @classmethod
    def from_context_manifest(cls, manifest: Mapping[str, object]) -> LifecyclePolicy:
        budgets = _required_mapping(manifest, "budgets")
        lease_policy = _required_mapping(manifest, "lease_policy")
        discovery = _required_mapping(budgets, "discovery")
        activation = _required_mapping(budgets, "activation")
        return cls(
            max_discovery_cards=_required_int(discovery, "max_cards"),
            max_active_capabilities=_required_int(activation, "max_schemas"),
            default_lease_turns=_required_int(lease_policy, "default_turns"),
            max_lease_turns=_required_int(lease_policy, "max_turns"),
        )


@dataclass(frozen=True)
class Registration:
    registration_ref: str
    plugin_id: str
    plugin_version: str
    manifest_sha256: str


@dataclass(frozen=True)
class CapabilityCard:
    capability_id: str
    title: str
    description: str
    effect_tier: str
    supports_async: bool


@dataclass(frozen=True)
class CapabilityDetail:
    registration_ref: str
    plugin_id: str
    plugin_version: str
    capability: Capability


@dataclass(frozen=True)
class CapabilityTarget:
    detail: CapabilityDetail
    manifest: LoadedManifest


@dataclass(frozen=True)
class Activation:
    activation_ref: str
    capability_id: str
    registration_ref: str
    activated_at_turn: int
    expires_at_turn: int


@dataclass(frozen=True)
class ActiveCapabilityTarget:
    detail: CapabilityDetail
    manifest: LoadedManifest
    activation: Activation


class LifecycleRegistry:
    """Deterministic in-memory registration and activation state."""

    def __init__(self, policy: LifecyclePolicy | None = None) -> None:
        self._policy = policy or LifecyclePolicy()
        self._registrations: dict[str, tuple[Registration, LoadedManifest]] = {}
        self._capabilities: dict[str, tuple[Registration, LoadedManifest, Capability]] = {}
        self._active: dict[str, Activation] = {}
        self._last_turn = 0
        self._lock = RLock()

    @staticmethod
    def _reference(kind: str, *parts: str) -> str:
        payload = "\0".join(parts).encode("utf-8")
        return f"urn:materials-mcp:{kind}:{hashlib.sha256(payload).hexdigest()}"

    def register(self, manifest: LoadedManifest) -> Registration:
        with self._lock:
            existing = self._registrations.get(manifest.plugin_id)
            if existing is not None:
                registration, loaded = existing
                if (
                    loaded.plugin_version == manifest.plugin_version
                    and loaded.manifest_sha256 == manifest.manifest_sha256
                ):
                    return registration
                raise LifecycleError(
                    "plugin-already-registered",
                    "Plugin identity already has a different registered snapshot",
                )
            collisions = sorted(
                capability.capability_id
                for capability in manifest.capabilities
                if capability.capability_id in self._capabilities
            )
            if collisions:
                raise LifecycleError(
                    "capability-id-conflict", "Capability identifier is already registered"
                )
            registration = Registration(
                registration_ref=self._reference(
                    "registration",
                    manifest.plugin_id,
                    manifest.plugin_version,
                    manifest.manifest_sha256,
                ),
                plugin_id=manifest.plugin_id,
                plugin_version=manifest.plugin_version,
                manifest_sha256=manifest.manifest_sha256,
            )
            self._registrations[manifest.plugin_id] = (registration, manifest)
            for capability in manifest.capabilities:
                self._capabilities[capability.capability_id] = (
                    registration,
                    manifest,
                    capability,
                )
            return registration

    def unregister(self, plugin_id: str) -> Registration:
        with self._lock:
            existing = self._registrations.get(plugin_id)
            if existing is None:
                raise LifecycleError("plugin-not-registered", "Plugin identity is not registered")
            registration, manifest = existing
            if any(
                capability.capability_id in self._active for capability in manifest.capabilities
            ):
                raise LifecycleError(
                    "plugin-active", "An active capability prevents unregistration"
                )
            del self._registrations[plugin_id]
            for capability in manifest.capabilities:
                del self._capabilities[capability.capability_id]
            return registration

    def registrations(self) -> tuple[Registration, ...]:
        with self._lock:
            return tuple(
                registration
                for registration, _ in sorted(
                    self._registrations.values(), key=lambda item: item[0].plugin_id
                )
            )

    def discover(self, query: str = "", *, limit: int | None = None) -> tuple[CapabilityCard, ...]:
        if type(query) is not str:
            raise LifecycleError("invalid-query", "Discovery query must be a string")
        selected_limit = self._policy.max_discovery_cards if limit is None else limit
        if (
            type(selected_limit) is not int
            or not 1 <= selected_limit <= self._policy.max_discovery_cards
        ):
            raise LifecycleError("invalid-discovery-limit", "Discovery limit exceeds policy")
        query_tokens = set(TOKEN_PATTERN.findall(query.casefold()))
        ranked: list[tuple[int, str, str, Capability]] = []
        with self._lock:
            for capability_id, (_, manifest, capability) in self._capabilities.items():
                searchable = " ".join(
                    (
                        capability_id,
                        capability.title,
                        capability.description,
                        manifest.name,
                        manifest.description,
                    )
                ).casefold()
                score = sum(token in searchable for token in query_tokens)
                if query_tokens and score == 0:
                    continue
                ranked.append((-score, capability.title.casefold(), capability_id, capability))
        ranked.sort(key=lambda item: item[:3])
        return tuple(
            CapabilityCard(
                capability_id=capability.capability_id,
                title=capability.title,
                description=capability.description[: self._policy.max_card_description_chars],
                effect_tier=capability.effect.tier,
                supports_async=capability.supports_async,
            )
            for _, _, _, capability in ranked[:selected_limit]
        )

    def inspect(self, capability_id: str) -> CapabilityDetail:
        with self._lock:
            found = self._capabilities.get(capability_id)
            if found is None:
                raise LifecycleError("capability-not-found", "Capability is not registered")
            registration, manifest, capability = found
            return CapabilityDetail(
                registration_ref=registration.registration_ref,
                plugin_id=manifest.plugin_id,
                plugin_version=manifest.plugin_version,
                capability=capability,
            )

    def resolve(self, capability_id: str, registration_ref: str) -> CapabilityTarget:
        """Resolve one capability only when exact registration ownership matches."""
        with self._lock:
            found = self._capabilities.get(capability_id)
            if found is None:
                raise LifecycleError("capability-not-found", "Capability is not registered")
            registration, manifest, capability = found
            if registration.registration_ref != registration_ref:
                raise LifecycleError(
                    "registration-mismatch", "Capability is owned by a different registration"
                )
            return CapabilityTarget(
                detail=CapabilityDetail(
                    registration_ref=registration.registration_ref,
                    plugin_id=manifest.plugin_id,
                    plugin_version=manifest.plugin_version,
                    capability=capability,
                ),
                manifest=manifest,
            )

    def resolve_active(
        self,
        capability_id: str,
        registration_ref: str,
        *,
        current_turn: int,
    ) -> ActiveCapabilityTarget:
        """Resolve exact ownership and a live activation in one locked transition."""
        if type(current_turn) is not int or current_turn < 0:
            raise LifecycleError("invalid-turn", "Logical turn must be non-negative")
        with self._lock:
            self._advance(current_turn)
            target = self.resolve(capability_id, registration_ref)
            activation = self._active.get(capability_id)
            if activation is None or activation.registration_ref != registration_ref:
                raise LifecycleError("capability-not-active", "Capability is not active")
            return ActiveCapabilityTarget(
                detail=target.detail,
                manifest=target.manifest,
                activation=activation,
            )

    def _advance(self, current_turn: int) -> None:
        if current_turn < self._last_turn:
            raise LifecycleError("turn-regression", "Logical turn cannot move backwards")
        self._last_turn = current_turn
        expired = [
            capability_id
            for capability_id, activation in self._active.items()
            if activation.expires_at_turn <= current_turn
        ]
        for capability_id in expired:
            del self._active[capability_id]

    def activate(
        self,
        capability_id: str,
        *,
        current_turn: int,
        lease_turns: int | None = None,
    ) -> Activation:
        if type(current_turn) is not int or current_turn < 0:
            raise LifecycleError("invalid-turn", "Logical turn must be non-negative")
        lease = self._policy.default_lease_turns if lease_turns is None else lease_turns
        if type(lease) is not int or not 1 <= lease <= self._policy.max_lease_turns:
            raise LifecycleError("invalid-lease", "Activation lease exceeds policy")
        with self._lock:
            self._advance(current_turn)
            found = self._capabilities.get(capability_id)
            if found is None:
                raise LifecycleError("capability-not-found", "Capability is not registered")
            registration, _, _ = found
            if (
                capability_id not in self._active
                and len(self._active) >= self._policy.max_active_capabilities
            ):
                victim = min(
                    self._active.values(),
                    key=lambda active: (active.expires_at_turn, active.capability_id),
                )
                del self._active[victim.capability_id]
            expires_at = current_turn + lease
            activation = Activation(
                activation_ref=self._reference(
                    "activation",
                    registration.registration_ref,
                    capability_id,
                    str(current_turn),
                    str(expires_at),
                ),
                capability_id=capability_id,
                registration_ref=registration.registration_ref,
                activated_at_turn=current_turn,
                expires_at_turn=expires_at,
            )
            self._active[capability_id] = activation
            return activation

    def deactivate(self, capability_id: str, *, current_turn: int) -> Activation:
        if type(current_turn) is not int or current_turn < 0:
            raise LifecycleError("invalid-turn", "Logical turn must be non-negative")
        with self._lock:
            self._advance(current_turn)
            activation = self._active.pop(capability_id, None)
            if activation is None:
                raise LifecycleError("capability-not-active", "Capability is not active")
            return activation

    def active(self, *, current_turn: int) -> tuple[Activation, ...]:
        if type(current_turn) is not int or current_turn < 0:
            raise LifecycleError("invalid-turn", "Logical turn must be non-negative")
        with self._lock:
            self._advance(current_turn)
            return tuple(sorted(self._active.values(), key=lambda item: item.capability_id))
