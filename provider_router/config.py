from __future__ import annotations

from provider_router.models import Provider

CASCADE_ORDER: tuple[Provider, ...] = (Provider.CLAUDE, Provider.CODEX, Provider.MUSE)

# Claude only fails over on a confirmed session/usage-limit signal — a logic or tool
# error should be fixed, not routed around by switching vendor. Codex has no such
# gate: any failure cascades to the local model, since no confirmed codex-limit
# error string exists yet to match narrowly against.
CLAUDE_LIMIT_PATTERNS: tuple[str, ...] = (
    "session limit",
    "usage limit",
    "you've hit your",
    "resets",
)

# Providers not listed here fail over on any exception, unmatched.
NARROW_FAILOVER_TRIGGERS: dict[Provider, tuple[str, ...]] = {
    Provider.CLAUDE: CLAUDE_LIMIT_PATTERNS,
}
