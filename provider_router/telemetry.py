from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from provider_router.types import ProviderAttempt


@dataclass(frozen=True, slots=True)
class FailoverEvent:
    attempt: ProviderAttempt
    category: str | None
    tags: frozenset[str]
    prompt_chars: int
    timestamp: datetime


def build_event(
    attempt: ProviderAttempt,
    category: str | None,
    tags: frozenset[str],
    prompt_chars: int,
) -> FailoverEvent:
    return FailoverEvent(
        attempt=attempt,
        category=category,
        tags=tags,
        prompt_chars=prompt_chars,
        timestamp=datetime.now(UTC),
    )


EmitFn = Callable[[FailoverEvent], None]


@dataclass(slots=True)
class InMemorySink:
    events: list[FailoverEvent] = field(default_factory=list)

    def __call__(self, event: FailoverEvent) -> None:
        self.events.append(event)

    def failures(self) -> tuple[FailoverEvent, ...]:
        return tuple(e for e in self.events if not e.attempt.succeeded)

    def successes(self) -> tuple[FailoverEvent, ...]:
        return tuple(e for e in self.events if e.attempt.succeeded)
