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

### A pattern must assert quota, not sit near it

Both lists are substring matches against the lowercased exception text, which makes
a short pattern dangerous in a way a long one is not. Two entries failed that test
and were removed:

- `resets`, on the Claude hop, matched `connection resets by peer`. A dead socket
  cascaded to a second vendor as though quota had run out — the route-bugs-around
  behaviour this gate exists to stop, on the hop whose narrowness was never in
  question. It was not load-bearing: the real message still matches on `session
  limit` and `you've hit your`.
- `hit your usage limit`, on the Codex hop, is a strict superstring of `usage
  limit`, so it could never be the sole matcher. Worse, the per-pattern test
  parametrizes over the tuple, so deleting the entry deleted its own test case and
  the suite stayed green. A subsumed pattern looks defended and is untestable by
  construction.

Two tests hold the line: one asserts a connection reset propagates, the other
rejects any pattern that is a superstring of another in the same list. The second
is the more useful of the pair — it makes a whole class of dead entry impossible
rather than pinning one instance.

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

Historically, one `deepseek-r1:8b` sample against a trivial prompt took ~17.5s,
versus sub-second for the hosted alternatives in that run. This is not a current
latency benchmark or quality qualification. The local tier is a last resort;
callers should treat `FailoverResult.degraded` as a signal to verify output
quality downstream, not just a log line.

This tier's backing model has changed before (`llama3.1:8b`, then
`muse-glimmer:30b-mlx`, then `deepseek-r1:8b`). There is no shipped local model
default now: callers must name a model, and the integrated dispatcher requires
a current qualification record. "Muse" is the historical tier label, not a
quality guarantee for a particular artifact.
