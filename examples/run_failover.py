#!/usr/bin/env python3
"""Run the codex -> configured local fallback cascade for a single prompt.

Usage: python3 run_failover.py "<prompt>"

Assumes tier 1 (Claude) has already failed. Local fallback requires an explicit
PROVIDER_ROUTER_LOCAL_MODEL; Codex failover occurs only on a recognized quota
error. Claude cannot invoke itself programmatically.
"""

from __future__ import annotations

import sys

from real_adapters import codex_call_fn, muse_call_fn

from provider_router import Provider, ProviderTask, run_with_failover


def main() -> None:
    if len(sys.argv) != 2:
        print('usage: run_failover.py "<prompt>"', file=sys.stderr)
        raise SystemExit(2)

    task = ProviderTask(prompt=sys.argv[1])
    result = run_with_failover(task, {Provider.CODEX: codex_call_fn, Provider.MUSE: muse_call_fn})

    for attempt in result.attempts:
        status = "ok" if attempt.succeeded else f"failed ({attempt.error})"
        print(f"[{attempt.provider.value}] {status} in {attempt.duration_ms:.0f}ms", file=sys.stderr)

    if result.degraded:
        print("--- DEGRADED: response from local fallback, not codex ---", file=sys.stderr)

    print(result.response)


if __name__ == "__main__":
    main()
