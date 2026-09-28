# provider-router

Vendor-failover orchestration for Claude / Codex / local-model agent work. When one
vendor is exhausted, the work continues on the next — and when a vendor is *broken*
rather than exhausted, it doesn't.

See `docs/DESIGN.md` for architecture and rationale.

## The problem

Three tools cover a "Claude does the work" chain — Claude Code, `codex exec`, and a
local Ollama model — and nothing tied them together. When Claude hit its usage limit
mid-task, falling back to codex was a policy a human followed by noticing and
re-dispatching. This library is that policy, executable and testable.

## Install

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Usage

The caller supplies one `call_fn` per provider. `run_with_failover` owns ordering,
failure classification, and telemetry — nothing else.

```python
from provider_router import Provider, ProviderTask, run_with_failover

result = run_with_failover(
    ProviderTask(prompt="review this diff for security issues"),
    {
        Provider.CLAUDE: lambda task: claude_session(task.prompt),
        Provider.CODEX: lambda task: codex_exec(task.prompt),
        Provider.MUSE: lambda task: ollama_chat(task.prompt),
    },
)

result.response  # whatever the provider that succeeded returned
result.failovers  # 0 if the first provider answered
result.final_attempt  # which provider actually served it
result.attempts  # every attempt tried, in cascade order
result.degraded  # True when a lower tier served it -- flag output quality downstream
```

Providers are tried in `config.CASCADE_ORDER`. A provider you don't pass is skipped
rather than treated as failing. When every provider fails, `AllProvidersFailedError`
carries the whole attempt chain.

For telemetry across runs, pass `emit=JsonlSink("~/.provider_router/events.jsonl")`.
`InMemorySink` is for tests.

## It never invokes Claude

Codex and Ollama are ordinary subprocess and HTTP calls, so this library *could* own
them. Claude it cannot: a Claude Code session cannot spawn itself as a Python
callable, and the failure that matters — the **current** session running out of quota
— is not observable from inside a library that session calls into.

So invocation stays with the caller, following `model-router`'s pattern of returning a
decision rather than making the call. The consequence worth knowing: the Claude hop
only fails over if the caller's `call_fn` raises something recognisable, which means
the caller has to surface the limit error rather than swallow it.

## Both gates are narrow, deliberately

Failing over on *any* error routes bugs around instead of fixing them. So each hop
cascades only on a confirmed limit signature, matched case-insensitively against the
exception text (`config.NARROW_FAILOVER_TRIGGERS`):

| hop | cascades on | does not cascade on |
|---|---|---|
| Claude → Codex | session / usage-limit text | logic errors, tool errors |
| Codex → local | usage-limit text | auth failures, crashes, transient errors |

A provider absent from `NARROW_FAILOVER_TRIGGERS` cascades on anything — that is the
default for a provider whose limit signature nobody has caught yet, not a permanent
choice.

The Codex gate was broad until 2026-09-27, because no real codex limit signature had
been observed — a default that shipped with its own falsification condition written
into `docs/DESIGN.md`. One was caught mid-task and is now pinned.

Two consequences, both stated in `config.py` and the first asserted by a test:
**a codex auth failure now propagates instead of quietly degrading to a local
model**, because answering from a local model when codex credentials are broken
hides the breakage. And a **transient** codex failure — a 429 with retry-after, a
connect timeout — propagates too. That one is a real cost rather than a win: it is
neither quota nor bug, and it is not modelled. A caller that wants transients
retried should retry, since widening the pattern list to catch them would restore
the route-bugs-around behaviour the narrow gate exists to prevent.

## What this does not do

- **No retries.** A provider gets one attempt. Retrying a rate-limited vendor is the
  caller's business, and doing it here would hide the limit the cascade exists to
  react to.
- **No response-quality judgement.** A provider that returns something is treated as
  having succeeded. Whether the local model's answer is *good enough* is not a
  question this library can answer — `model-router`'s `validate_fn` is the seam for
  that, per-call and caller-supplied.
- **No cost accounting.** Which provider is cheaper is not modelled; the cascade order
  is configuration, not an optimisation.
- **No concurrency.** Providers are tried in sequence. Racing them would spend two
  vendors' quota to save latency, which inverts the point.

## Tests

```bash
python -m pytest tests/ -q
```

`tests/test_integration_real.py` is deselected by default — it invokes real providers
and needs credentials. Everything else is hermetic.
