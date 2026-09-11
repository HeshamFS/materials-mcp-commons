from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock
from typing import Literal

from .errors import HostError

OperationName = Literal["discover", "inspect", "activate", "execute"]
OperationOutcome = Literal["success", "failure"]
EventSink = Callable[["OperationEvent"], None]

_OPERATIONS = frozenset({"discover", "inspect", "activate", "execute"})
_OUTCOMES = frozenset({"success", "failure"})
_EFFECT_TIERS = frozenset({"R0", "R1", "R2", "R3", "R4"})


def _digest_reference(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class OperationEvent:
    """One metadata-only host operation event safe for an operator-selected sink."""

    sequence: int
    operation: OperationName
    outcome: OperationOutcome
    occurred_at: datetime
    duration_ns: int
    effect_tier: str | None = None
    error_code: str | None = None
    subject_sha256: str | None = None

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or self.sequence < 1:
            raise HostError("invalid-event", "Operation event sequence must be positive")
        if self.operation not in _OPERATIONS or self.outcome not in _OUTCOMES:
            raise HostError("invalid-event", "Operation event classification is invalid")
        if type(self.occurred_at) is not datetime or self.occurred_at.utcoffset() is None:
            raise HostError("invalid-event", "Operation event time must include a UTC offset")
        if type(self.duration_ns) is not int or self.duration_ns < 0:
            raise HostError("invalid-event", "Operation event duration must be non-negative")
        if self.effect_tier is not None and self.effect_tier not in _EFFECT_TIERS:
            raise HostError("invalid-event", "Operation event effect tier is invalid")
        if self.outcome == "success" and self.error_code is not None:
            raise HostError("invalid-event", "Successful events cannot carry an error code")
        if self.outcome == "failure" and not self.error_code:
            raise HostError("invalid-event", "Failed events require a stable error code")
        if self.subject_sha256 is not None and (
            len(self.subject_sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.subject_sha256)
        ):
            raise HostError("invalid-event", "Operation subject digest must be lowercase SHA-256")
        object.__setattr__(self, "occurred_at", self.occurred_at.astimezone(UTC))

    def to_document(self) -> dict[str, object]:
        document: dict[str, object] = {
            "sequence": self.sequence,
            "operation": self.operation,
            "outcome": self.outcome,
            "occurred_at": self.occurred_at.isoformat(timespec="microseconds").replace(
                "+00:00", "Z"
            ),
            "duration_ns": self.duration_ns,
        }
        if self.effect_tier is not None:
            document["effect_tier"] = self.effect_tier
        if self.error_code is not None:
            document["error_code"] = self.error_code
        if self.subject_sha256 is not None:
            document["subject_sha256"] = self.subject_sha256
        return document


@dataclass(frozen=True)
class OperationMetric:
    operation: OperationName
    outcome: OperationOutcome
    count: int
    total_duration_ns: int
    max_duration_ns: int


@dataclass(frozen=True)
class OperationMetricsSnapshot:
    events: tuple[OperationMetric, ...]
    dropped_sink_events: int

    def to_document(self) -> dict[str, object]:
        return {
            "events": [
                {
                    "operation": event.operation,
                    "outcome": event.outcome,
                    "count": event.count,
                    "total_duration_ns": event.total_duration_ns,
                    "max_duration_ns": event.max_duration_ns,
                }
                for event in self.events
            ],
            "dropped_sink_events": self.dropped_sink_events,
        }


class OperationObserver:
    """Thread-safe bounded metrics and isolated metadata-event delivery."""

    def __init__(
        self,
        sink: EventSink | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
        monotonic_ns: Callable[[], int] | None = None,
    ) -> None:
        self._sink = sink
        self._clock = clock or (lambda: datetime.now(UTC))
        self._monotonic_ns = monotonic_ns or time.monotonic_ns
        self._sequence = 0
        self._metrics: dict[tuple[OperationName, OperationOutcome], list[int]] = {}
        self._dropped_sink_events = 0
        self._lock = RLock()

    def begin(self) -> int:
        value = self._monotonic_ns()
        if type(value) is not int or value < 0:
            raise HostError("invalid-clock", "Monotonic clock returned an invalid value")
        return value

    def finish(
        self,
        started_ns: int,
        *,
        operation: OperationName,
        outcome: OperationOutcome,
        effect_tier: str | None = None,
        error_code: str | None = None,
        subject_ref: str | None = None,
    ) -> OperationEvent:
        ended_ns = self.begin()
        if type(started_ns) is not int or started_ns < 0 or ended_ns < started_ns:
            raise HostError("invalid-clock", "Monotonic clock moved backwards")
        occurred_at = self._clock()
        if type(occurred_at) is not datetime or occurred_at.utcoffset() is None:
            raise HostError("invalid-clock", "Wall clock must return an offset-aware time")
        subject_sha256 = None
        if subject_ref is not None:
            if type(subject_ref) is not str or not subject_ref:
                raise HostError("invalid-event", "Operation subject reference is invalid")
            subject_sha256 = _digest_reference(subject_ref)

        with self._lock:
            self._sequence += 1
            event = OperationEvent(
                sequence=self._sequence,
                operation=operation,
                outcome=outcome,
                occurred_at=occurred_at,
                duration_ns=ended_ns - started_ns,
                effect_tier=effect_tier,
                error_code=error_code,
                subject_sha256=subject_sha256,
            )
            values = self._metrics.setdefault((operation, outcome), [0, 0, 0])
            values[0] += 1
            values[1] += event.duration_ns
            values[2] = max(values[2], event.duration_ns)
            if self._sink is not None:
                try:
                    self._sink(event)
                except Exception:
                    self._dropped_sink_events += 1
            return event

    def snapshot(self) -> OperationMetricsSnapshot:
        with self._lock:
            events = tuple(
                OperationMetric(
                    operation=operation,
                    outcome=outcome,
                    count=values[0],
                    total_duration_ns=values[1],
                    max_duration_ns=values[2],
                )
                for (operation, outcome), values in sorted(self._metrics.items())
            )
            return OperationMetricsSnapshot(events, self._dropped_sink_events)
