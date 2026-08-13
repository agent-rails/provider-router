from __future__ import annotations

import pytest

from provider_router.cascade import run_with_failover
from provider_router.models import Provider
from provider_router.telemetry import InMemorySink
from provider_router.types import AllProvidersFailedError, ProviderTask

TASK = ProviderTask(prompt="review this diff for security issues")


def test_claude_success_short_circuits() -> None:
    result = run_with_failover(TASK, {Provider.CLAUDE: lambda t: "claude response"})

    assert result.response == "claude response"
    assert result.failovers == 0
    assert not result.degraded
    assert result.attempts[0].provider == Provider.CLAUDE
    assert result.attempts[0].succeeded


def test_claude_limit_cascades_to_codex() -> None:
    def claude_fails(_: ProviderTask) -> str:
        raise RuntimeError("You've hit your session limit · resets in 3h")

    result = run_with_failover(
        TASK,
        {Provider.CLAUDE: claude_fails, Provider.CODEX: lambda t: "codex response"},
    )

    assert result.response == "codex response"
    assert result.failovers == 1
    assert result.degraded
    assert result.attempts[0].provider == Provider.CLAUDE
    assert not result.attempts[0].succeeded
    assert result.attempts[1].provider == Provider.CODEX
    assert result.attempts[1].succeeded


def test_claude_non_limit_error_does_not_cascade() -> None:
    def claude_fails(_: ProviderTask) -> str:
        raise TypeError("unexpected keyword argument 'foo'")

    with pytest.raises(TypeError, match="unexpected keyword"):
        run_with_failover(
            TASK,
            {Provider.CLAUDE: claude_fails, Provider.CODEX: lambda t: "should not run"},
        )


def test_codex_any_failure_cascades_to_muse() -> None:
    def claude_fails(_: ProviderTask) -> str:
        raise RuntimeError("you've hit your session limit")

    def codex_fails(_: ProviderTask) -> str:
        raise RuntimeError("network unreachable, nothing to do with limits")

    result = run_with_failover(
        TASK,
        {
            Provider.CLAUDE: claude_fails,
            Provider.CODEX: codex_fails,
            Provider.MUSE: lambda t: "muse response",
        },
    )

    assert result.response == "muse response"
    assert result.failovers == 2
    assert result.attempts[1].provider == Provider.CODEX
    assert not result.attempts[1].succeeded
    assert result.attempts[2].provider == Provider.MUSE
    assert result.attempts[2].succeeded


def test_all_providers_fail_raises() -> None:
    def claude_fails(_: ProviderTask) -> str:
        raise RuntimeError("session limit hit")

    def codex_fails(_: ProviderTask) -> str:
        raise RuntimeError("boom")

    def muse_fails(_: ProviderTask) -> str:
        raise RuntimeError("ollama down")

    with pytest.raises(AllProvidersFailedError) as excinfo:
        run_with_failover(
            TASK,
            {Provider.CLAUDE: claude_fails, Provider.CODEX: codex_fails, Provider.MUSE: muse_fails},
        )

    assert len(excinfo.value.attempts) == 3
    assert all(not a.succeeded for a in excinfo.value.attempts)


def test_missing_provider_call_fn_is_skipped() -> None:
    def claude_fails(_: ProviderTask) -> str:
        raise RuntimeError("session limit hit")

    result = run_with_failover(
        TASK,
        {Provider.CLAUDE: claude_fails, Provider.MUSE: lambda t: "muse direct"},
    )

    assert result.response == "muse direct"
    assert result.attempts[-1].provider == Provider.MUSE


def test_telemetry_emitted_for_every_attempt() -> None:
    sink = InMemorySink()

    def claude_fails(_: ProviderTask) -> str:
        raise RuntimeError("session limit hit")

    run_with_failover(
        TASK,
        {Provider.CLAUDE: claude_fails, Provider.CODEX: lambda t: "codex response"},
        emit=sink,
    )

    assert len(sink.events) == 2
    assert len(sink.failures()) == 1
    assert len(sink.successes()) == 1
