from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from provider_router.models import Provider


class FailureReason(StrEnum):
    LIMIT = "limit"
    ERROR = "error"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ProviderTask:
    prompt: str
    category: str | None = None
    tags: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class ProviderAttempt:
    provider: Provider
    succeeded: bool
    failure_reason: FailureReason | None
    error: str | None
    duration_ms: float


class AllProvidersFailedError(Exception):
    def __init__(self, attempts: tuple[ProviderAttempt, ...]) -> None:
        self.attempts = attempts
        tried = ", ".join(f"{a.provider.value} ({a.failure_reason})" for a in attempts)
        super().__init__(f"all providers failed: {tried}")


@dataclass(frozen=True, slots=True)
class FailoverResult[ResponseT]:
    response: ResponseT
    attempts: tuple[ProviderAttempt, ...]

    @property
    def final_attempt(self) -> ProviderAttempt:
        return self.attempts[-1]

    @property
    def failovers(self) -> int:
        return len(self.attempts) - 1

    @property
    def degraded(self) -> bool:
        return self.final_attempt.provider != Provider.CLAUDE
