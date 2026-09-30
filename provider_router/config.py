from __future__ import annotations

import os
from collections.abc import Mapping

from provider_router.models import Provider

CASCADE_ORDER: tuple[Provider, ...] = (Provider.CLAUDE, Provider.CODEX, Provider.MUSE)

# Manual overflow. The cascade fires on failure only -- it waits for Claude to
# return a limit error, then moves. When the operator already knows Claude's quota
# is nearly spent, waiting for that error wastes the remaining headroom on a
# request that will fail. PROVIDER_ROUTER_PREFER front-loads named providers for
# the process, leaving the rest of the order intact.
#
#     PROVIDER_ROUTER_PREFER=codex   ->  (CODEX, CLAUDE, MUSE)
#
# Deliberately manual. There is no quota-remaining API, so any automatic version
# would infer pressure from 429 history -- a stateful heuristic that is wrong
# exactly when it matters. An operator flag is honest about what it knows.
#
# An unrecognised name RAISES rather than being ignored. A silently-dropped
# preference means the operator believes they are conserving Claude quota while
# every request still goes to Claude first -- a control that reads as active and
# does nothing.
PREFER_ENV_VAR = "PROVIDER_ROUTER_PREFER"


def resolve_cascade_order(
    env: Mapping[str, str] | None = None,
    base: tuple[Provider, ...] = CASCADE_ORDER,
) -> tuple[Provider, ...]:
    """Cascade order for this call, honouring the manual overflow preference."""
    source = os.environ if env is None else env
    raw = (source.get(PREFER_ENV_VAR) or "").strip()
    if not raw:
        return base

    valid = {p.value: p for p in base}
    preferred: list[Provider] = []
    for name in (part.strip().lower() for part in raw.split(",")):
        if not name:
            continue
        if name not in valid:
            raise ValueError(
                f"{PREFER_ENV_VAR}={raw!r} names unknown provider {name!r}; valid options are {sorted(valid)}"
            )
        provider = valid[name]
        if provider not in preferred:
            preferred.append(provider)

    return tuple(preferred) + tuple(p for p in base if p not in preferred)


# Neither hop fails over on an arbitrary error: a logic, tool or auth failure
# should be fixed, not routed around by switching vendor. Both gates are narrow.
# "resets" was here and was dropped: it matched "connection resets by peer",
# cascading a network error as though it were a quota limit -- the route-bugs-around
# behaviour this gate exists to stop, and the same billing-surface mistake the codex
# list below records. It was never load-bearing; the real message
# ("You've hit your session limit - resets in 3h") still matches on "session limit"
# and "you've hit your". Every pattern here must be a quota assertion, not a word
# that happens to appear near one.
CLAUDE_LIMIT_PATTERNS: tuple[str, ...] = (
    "session limit",
    "usage limit",
    "you've hit your",
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
# Only quota assertions are matched. "purchase more credits" and
# "codex/settings/usage" were in an earlier draft and were dropped: they are
# billing-surface strings -- an upsell and a help link -- which vendors attach to
# auth and entitlement errors generally, so matching them let an auth failure
# carrying a billing link degrade to the local model, the exact case this gate
# exists to stop.
#
# Also no longer cascading: transient codex failures -- a 429 with retry-after, a
# connect timeout. Those are neither quota nor bug, and this is the honest cost of
# narrowing. A caller that wants them retried should retry; widening this list to
# catch them would restore the route-bugs-around behaviour it exists to prevent.
#
# The consequence of narrowing that is worth stating: a codex *auth* failure no
# longer degrades to the local model. docs/DESIGN.md noted auth failures were the
# only codex errors observed at the time, and silently answering from a local model
# when codex credentials are broken hides the breakage instead of surfacing it.
# One entry, not two. "hit your usage limit" was also here and is a strict superstring
# of "usage limit", so it could never be the sole matcher -- and because the
# per-pattern test parametrizes over this tuple, deleting it deleted its own test
# case and the suite stayed green. A subsumed pattern is untestable by construction;
# test_no_pattern_subsumes_another now rejects one.
CODEX_LIMIT_PATTERNS: tuple[str, ...] = ("usage limit",)

# Providers not listed here fail over on any exception, unmatched.
NARROW_FAILOVER_TRIGGERS: dict[Provider, tuple[str, ...]] = {
    Provider.CLAUDE: CLAUDE_LIMIT_PATTERNS,
    Provider.CODEX: CODEX_LIMIT_PATTERNS,
}
