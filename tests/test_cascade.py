from __future__ import annotations

import pytest

from provider_router.cascade import run_with_failover
from provider_router.config import CODEX_LIMIT_PATTERNS, NARROW_FAILOVER_TRIGGERS
from provider_router.models import Provider
from provider_router.telemetry import InMemorySink
from provider_router.types import AllProvidersFailedError, FailureReason, ProviderTask

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


def test_codex_limit_cascades_to_muse() -> None:
    def claude_fails(_: ProviderTask) -> str:
        raise RuntimeError("you've hit your session limit")

    def codex_fails(_: ProviderTask) -> str:
        # The real signature, from a codex CLI session that ran out mid-task.
        raise RuntimeError(
            "You've hit your usage limit. Upgrade to Pro, visit "
            "https://chatgpt.com/codex/settings/usage to purchase more credits"
        )

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
        raise RuntimeError("usage limit reached")

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


def test_codex_first_success_is_not_degraded() -> None:
    """Regression: a cascade that intentionally starts at codex (Claude can't invoke
    itself, see docs/DESIGN.md) must not be flagged degraded just because the first
    attempt wasn't Claude. Degraded means "didn't succeed on the first provider tried"."""
    result = run_with_failover(TASK, {Provider.CODEX: lambda t: "codex response"})

    assert result.response == "codex response"
    assert result.failovers == 0
    assert not result.degraded


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


def test_provider_exception_text_is_not_retained_in_attempt_or_telemetry() -> None:
    sink = InMemorySink()
    marker = "private-prompt-marker"

    def claude_fails(_: ProviderTask) -> str:
        raise RuntimeError(f"session limit: {marker}")

    result = run_with_failover(
        TASK,
        {Provider.CLAUDE: claude_fails, Provider.CODEX: lambda _: "done"},
        emit=sink,
    )

    assert result.attempts[0].error == "RuntimeError"
    assert marker not in repr(result.attempts)
    assert marker not in repr(sink.events)


def test_a_codex_error_that_is_not_a_limit_propagates_instead_of_degrading() -> None:
    # The consequence of narrowing the codex gate, asserted rather than assumed.
    # Answering from a local model when codex credentials are broken hides the
    # breakage; docs/DESIGN.md records auth failures as the codex errors actually
    # observed before a limit signature was caught.
    def claude_fails(_: ProviderTask) -> str:
        raise RuntimeError("you've hit your session limit")

    def codex_auth_fails(_: ProviderTask) -> str:
        raise RuntimeError("401 unauthorized: stored credentials rejected")

    with pytest.raises(RuntimeError, match="401 unauthorized"):
        run_with_failover(
            TASK,
            {
                Provider.CLAUDE: claude_fails,
                Provider.CODEX: codex_auth_fails,
                Provider.MUSE: lambda t: "muse should never be reached",
            },
        )


@pytest.mark.parametrize(
    ("provider", "patterns"),
    sorted(NARROW_FAILOVER_TRIGGERS.items(), key=lambda item: item[0].value),
    ids=lambda value: value.value if isinstance(value, Provider) else "",
)
def test_no_pattern_subsumes_another(provider: Provider, patterns: tuple[str, ...]) -> None:
    # Parametrizing a test over a pattern tuple cannot catch a redundant entry:
    # deleting the entry deletes its own test case, so the suite stays green. This
    # asserts the property that makes the per-pattern test meaningful -- every
    # pattern must be independently reachable, or it is dead weight that looks
    # defended.
    subsumed = {pattern: [other for other in patterns if other != pattern and other in pattern] for pattern in patterns}
    offenders = {pattern: hits for pattern, hits in subsumed.items() if hits}
    assert not offenders, f"{provider.value} patterns contain a superstring of another pattern: {offenders}"


def test_a_connection_reset_is_not_a_claude_limit() -> None:
    # "resets" used to be a Claude limit pattern and matched this message, cascading
    # a network error to another vendor as though quota had run out. A transport
    # failure has to propagate: switching vendor hides it and the next run hits the
    # same broken socket.
    def claude_network_fails(_: ProviderTask) -> str:
        raise RuntimeError("connection resets by peer")

    with pytest.raises(RuntimeError, match="connection resets by peer"):
        run_with_failover(
            TASK,
            {
                Provider.CLAUDE: claude_network_fails,
                Provider.CODEX: lambda t: "codex should never be reached",
                Provider.MUSE: lambda t: "muse should never be reached",
            },
        )


@pytest.mark.parametrize("pattern", CODEX_LIMIT_PATTERNS)
def test_every_codex_limit_pattern_cascades(pattern: str) -> None:
    # One message containing every pattern lets any of them be deleted with nothing
    # failing -- a surviving mutation. Each pattern has to carry its own test.
    def claude_fails(_: ProviderTask) -> str:
        raise RuntimeError("you've hit your session limit")

    def codex_fails(_: ProviderTask) -> str:
        raise RuntimeError(f"codex says: {pattern}")

    result = run_with_failover(
        TASK,
        {
            Provider.CLAUDE: claude_fails,
            Provider.CODEX: codex_fails,
            Provider.MUSE: lambda t: "muse response",
        },
    )

    assert result.response == "muse response"
    assert result.final_attempt.provider == Provider.MUSE
    # A cascading failure must be classified; None would leave an operator reading
    # the JSONL unable to tell "failed, unclassified" from anything else.
    assert result.attempts[1].failure_reason == FailureReason.LIMIT


# --- manual overflow (PROVIDER_ROUTER_PREFER) ---------------------------------

import pytest

from provider_router.config import CASCADE_ORDER, resolve_cascade_order


def test_no_preference_keeps_default_order():
    assert resolve_cascade_order(env={}) == CASCADE_ORDER


def test_blank_preference_keeps_default_order():
    assert resolve_cascade_order(env={"PROVIDER_ROUTER_PREFER": "   "}) == CASCADE_ORDER


def test_single_preference_front_loads_and_keeps_the_rest():
    assert resolve_cascade_order(env={"PROVIDER_ROUTER_PREFER": "codex"}) == (
        Provider.CODEX,
        Provider.CLAUDE,
        Provider.MUSE,
    )


def test_multiple_preferences_keep_their_given_order():
    assert resolve_cascade_order(env={"PROVIDER_ROUTER_PREFER": "muse,codex"}) == (
        Provider.MUSE,
        Provider.CODEX,
        Provider.CLAUDE,
    )


def test_preference_is_case_and_space_insensitive():
    assert resolve_cascade_order(env={"PROVIDER_ROUTER_PREFER": " CODEX , claude "}) == (
        Provider.CODEX,
        Provider.CLAUDE,
        Provider.MUSE,
    )


def test_duplicate_preference_is_not_repeated():
    assert resolve_cascade_order(env={"PROVIDER_ROUTER_PREFER": "codex,codex"}) == (
        Provider.CODEX,
        Provider.CLAUDE,
        Provider.MUSE,
    )


def test_unknown_provider_raises_rather_than_being_ignored():
    """A silently-dropped preference is a control that reads as active and does nothing."""
    with pytest.raises(ValueError) as excinfo:
        resolve_cascade_order(env={"PROVIDER_ROUTER_PREFER": "gpt"})
    assert "gpt" in str(excinfo.value)
    assert "claude" in str(excinfo.value)


def test_explicit_order_argument_overrides_the_env():
    """An explicit order wins: callers that already decided are not second-guessed."""
    calls: list[Provider] = []

    def record(provider: Provider):
        def _call(task):
            calls.append(provider)
            return f"ok-{provider.value}"

        return _call

    task = ProviderTask(prompt="p", category="chat", tags=())
    result = run_with_failover(
        task,
        {p: record(p) for p in CASCADE_ORDER},
        order=(Provider.MUSE, Provider.CLAUDE),
    )
    assert calls == [Provider.MUSE]
    assert result.response == "ok-muse"
