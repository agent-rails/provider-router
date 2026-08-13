from __future__ import annotations

import time
from collections.abc import Callable

from provider_router.config import CASCADE_ORDER, NARROW_FAILOVER_TRIGGERS
from provider_router.models import Provider
from provider_router.telemetry import EmitFn, build_event
from provider_router.types import (
    AllProvidersFailedError,
    FailoverResult,
    FailureReason,
    ProviderAttempt,
    ProviderTask,
)


def _should_cascade(provider: Provider, error: Exception) -> bool:
    patterns = NARROW_FAILOVER_TRIGGERS.get(provider)
    if patterns is None:
        return True
    message = str(error).lower()
    return any(pattern in message for pattern in patterns)


def _classify_failure(provider: Provider, error: Exception) -> FailureReason:
    if provider in NARROW_FAILOVER_TRIGGERS:
        return FailureReason.LIMIT
    return FailureReason.ERROR


def run_with_failover[ResponseT](
    task: ProviderTask,
    call_fns: dict[Provider, Callable[[ProviderTask], ResponseT]],
    emit: EmitFn | None = None,
) -> FailoverResult[ResponseT]:
    attempts: list[ProviderAttempt] = []

    for provider in CASCADE_ORDER:
        call_fn = call_fns.get(provider)
        if call_fn is None:
            continue

        start = time.monotonic()
        try:
            response = call_fn(task)
        except Exception as error:
            duration_ms = (time.monotonic() - start) * 1000
            cascade = _should_cascade(provider, error)
            attempt = ProviderAttempt(
                provider=provider,
                succeeded=False,
                failure_reason=_classify_failure(provider, error) if cascade else None,
                error=str(error),
                duration_ms=duration_ms,
            )
            attempts.append(attempt)
            if emit is not None:
                emit(build_event(attempt, task.category, task.tags, len(task.prompt)))

            if not cascade:
                raise

            continue

        duration_ms = (time.monotonic() - start) * 1000
        attempt = ProviderAttempt(
            provider=provider,
            succeeded=True,
            failure_reason=None,
            error=None,
            duration_ms=duration_ms,
        )
        attempts.append(attempt)
        if emit is not None:
            emit(build_event(attempt, task.category, task.tags, len(task.prompt)))

        return FailoverResult(response=response, attempts=tuple(attempts))

    raise AllProvidersFailedError(tuple(attempts))
