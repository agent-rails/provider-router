# provider-router: design

## Problem

Three tools cover a "Claude does the work" chain — Claude Code, `codex exec`, and a
local Ollama model — but nothing ties them together. When Claude hits its usage
limit mid-task, the fallback to codex has so far been a manually-followed policy
(see the `codex-limit-fallback` memory in the operator's own notes), not code.
This library is that policy, made executable and testable.

## Non-goal: this library does not invoke Claude

Codex and Ollama are ordinary subprocess/HTTP calls — this library could own
those directly. Claude cannot be invoked the same way: a Claude Code session
cannot spawn "itself" as a Python callable, and the failure mode that matters
(the *current* session running out of quota) can't be observed from inside a
library it calls into. So, following `model_router`'s own pattern — which
never calls the Anthropic API either, it only returns a decision — this
library never owns invocation. The caller supplies one `call_fn` per provider
it wants in the cascade; `run_with_failover` owns only ordering, failure
classification, and telemetry.

## Failover triggers are narrow on both hops

- **Claude -> Codex**: only cascades when the failure message matches a known
  session/usage-limit pattern (`config.CLAUDE_LIMIT_PATTERNS`). A real logic or
  tool error propagates immediately instead of being silently routed around —
  that class of bug needs fixing, not a different vendor.
- **Codex -> Muse**: same shape, matching `config.CODEX_LIMIT_PATTERNS`.

### This hop was asymmetric until 2026-09-27, and the history is the point

The Codex hop originally cascaded on *any* exception. The reason was recorded
rather than assumed: there was no confirmed codex-limit error string — only auth
failures had been observed — and the cost of waiting for one was judged higher
than the risk of over-triggering on an unrelated codex bug. The default shipped
with its own falsification condition attached: "config-driven, not hardcoded per
hop, so it can be tightened once a real codex-limit signature is caught."

A signature was caught mid-task while codex was verifying a release, and the gate
was narrowed. Worth being precise about what that was: not a considered default
being reversed on one observation, but a provisional one being discharged on the
evidence it was waiting for.

Only quota assertions are matched. An earlier draft also matched
`purchase more credits` and `codex/settings/usage`; both were dropped because they
are billing-surface strings — an upsell and a help link — which vendors attach to
auth and entitlement errors generally, so matching them let an auth failure
carrying a billing link degrade to the local model, the exact case the gate exists
to stop.

### What narrowing costs

A codex auth failure, crash, or **transient** failure — a 429 with retry-after, a
connect timeout — now propagates where it previously degraded to Muse. For auth
and crashes that is the intent: answering from `deepseek-r1:8b` while codex
credentials are broken converts a five-second fix into a silent quality
regression, and the Muse tier is explicitly a last resort rather than a casual
substitute.

Transients are the honest cost. They are neither quota nor bug, and they are the
one case where "keep the work moving" genuinely applies with nothing hidden. They
are not modelled: a caller that wants them retried should retry, and widening the
pattern list to catch them would restore the route-bugs-around behaviour the
narrow gate exists to prevent.

## Scope

Spawned subagent-equivalent work only. The main interactive session has no
task-notification text to detect a limit from in the first place — that
remains a manual switch to a separate `codex` terminal session.

## Quality note on the Muse tier

The Muse tier runs `deepseek-r1:8b` via local Ollama — a reasoning model
(chain-of-thought before answering), which trades latency for quality: one
measured sample against a trivial prompt took ~17.5s, versus sub-second for
Claude/codex. It's a last-resort tier, not a casual substitute — callers
should treat `FailoverResult.degraded` as a signal to flag output quality
downstream, not just a log line.

This tier's backing model has changed before (originally `llama3.1:8b`, then
`muse-glimmer:30b-mlx`, now `deepseek-r1:8b`) and may change again — "Muse" is
the architectural tier label (last-resort local fallback), independent of
which specific model backs it at any point.
