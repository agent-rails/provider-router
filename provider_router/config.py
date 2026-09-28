from __future__ import annotations

from provider_router.models import Provider

CASCADE_ORDER: tuple[Provider, ...] = (Provider.CLAUDE, Provider.CODEX, Provider.MUSE)

# Neither hop fails over on an arbitrary error: a logic, tool or auth failure
# should be fixed, not routed around by switching vendor. Both gates are narrow.
CLAUDE_LIMIT_PATTERNS: tuple[str, ...] = (
    "session limit",
    "usage limit",
    "you've hit your",
    "resets",
)

# Tightened from the original broad "cascade on any codex exception", which
# docs/DESIGN.md flagged as provisional: "so it can be tightened once a real
# codex-limit signature is caught." One was caught on 2026-09-27, mid-task, while
# codex was verifying a release:
#
#   You've hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro),
#   visit https://chatgpt.com/codex/settings/usage to purchase more credits or try
#   again at 3:55 PM.
#
# Provenance, since it matters for a pattern list: that text is the operator's own
# codex CLI output, recorded from a session transcript rather than captured by an
# automated probe. If codex changes the wording, this list silently stops matching
# and the hop stops failing over -- which fails closed (the error surfaces) rather
# than open, but is worth an integration test against a real limit if one is ever
# cheap to provoke.
#
# The consequence of narrowing that is worth stating: a codex *auth* failure no
# longer degrades to the local model. docs/DESIGN.md noted auth failures were the
# only codex errors observed at the time, and silently answering from a local model
# when codex credentials are broken hides the breakage instead of surfacing it.
CODEX_LIMIT_PATTERNS: tuple[str, ...] = (
    "usage limit",
    "purchase more credits",
    "codex/settings/usage",
)

# Providers not listed here fail over on any exception, unmatched.
NARROW_FAILOVER_TRIGGERS: dict[Provider, tuple[str, ...]] = {
    Provider.CLAUDE: CLAUDE_LIMIT_PATTERNS,
    Provider.CODEX: CODEX_LIMIT_PATTERNS,
}
