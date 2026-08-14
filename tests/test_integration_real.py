from __future__ import annotations

import pytest
from real_adapters import muse_call_fn

from provider_router.cascade import run_with_failover
from provider_router.models import Provider
from provider_router.types import ProviderTask


def _simulated_claude_limit(_: ProviderTask) -> str:
    raise RuntimeError("You've hit your session limit · resets in 3h")


def _broken_codex(_: ProviderTask) -> str:
    raise RuntimeError("simulated codex failure, forcing cascade to muse")


@pytest.mark.integration
def test_real_cascade_reaches_muse() -> None:
    task = ProviderTask(prompt="Reply with exactly one line: integration test reached muse.")

    result = run_with_failover(
        task,
        {
            Provider.CLAUDE: _simulated_claude_limit,
            Provider.CODEX: _broken_codex,
            Provider.MUSE: muse_call_fn,
        },
    )

    assert result.attempts[0].provider == Provider.CLAUDE
    assert not result.attempts[0].succeeded
    assert result.attempts[1].provider == Provider.CODEX
    assert not result.attempts[1].succeeded
    assert result.attempts[2].provider == Provider.MUSE
    assert result.attempts[2].succeeded
    assert result.degraded
    assert len(result.response) > 0
