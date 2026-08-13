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

## Asymmetric failover trigger (deliberate, not a bug)

- **Claude -> Codex**: narrow trigger. Only cascades when the failure message
  matches a known session/usage-limit pattern (`config.CLAUDE_LIMIT_PATTERNS`).
  A real logic or tool error propagates immediately instead of being silently
  routed around — that class of bug needs fixing, not a different vendor.
- **Codex -> Muse**: broad trigger. Cascades on any exception. There is no
  confirmed codex-limit error string yet (only auth failures have been
  observed), and the cost of waiting for one was judged higher than the risk
  of over-triggering on an unrelated codex bug.

This asymmetry is config-driven (`NARROW_FAILOVER_TRIGGERS`), not hardcoded
per hop, so it can be tightened once a real codex-limit signature is caught.

## Scope

Spawned subagent-equivalent work only. The main interactive session has no
task-notification text to detect a limit from in the first place — that
remains a manual switch to a separate `codex` terminal session.

## Quality note on the Muse tier

`muse-glimmer:30b-mlx` has materially better instruction-following than the
originally-tried `llama3.1:8b`, but ~60-90s per call versus sub-second for
Claude/codex. It's a last-resort tier, not a casual substitute — callers
should treat `FailoverResult.degraded` as a signal to flag output quality
downstream, not just a log line.
