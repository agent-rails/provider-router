from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass

from provider_router.types import ProviderTask

CODEX_TIMEOUT_S = 120
MUSE_TIMEOUT_S = 180
OLLAMA_URL = "http://localhost:11434/api/generate"


@dataclass(frozen=True, slots=True)
class CodexUsage:
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int


@dataclass(frozen=True, slots=True)
class CodexResult:
    text: str
    model: str | None
    effort: str | None
    usage: CodexUsage | None


@dataclass(frozen=True, slots=True)
class LocalUsage:
    input_tokens: int
    cached_input_tokens: int | None
    output_tokens: int
    duration_ms: float | None


@dataclass(frozen=True, slots=True)
class LocalResult:
    text: str
    model: str
    usage: LocalUsage | None


def codex_run(task: ProviderTask, *, model: str | None = None, effort: str | None = None) -> CodexResult:
    """Run one read-only Codex task with explicit, caller-selected settings.

    Usage is None when the installed CLI does not return a recognized usage event.
    The adapter does not silently substitute another model or effort.
    """
    command = ["codex", "exec", "-s", "read-only", "--skip-git-repo-check", "--json"]
    if model is not None:
        command.extend(["--model", model])
    if effort is not None:
        if effort not in {"low", "medium", "high", "xhigh", "max"}:
            raise ValueError(f"unsupported Codex reasoning effort: {effort!r}")
        command.extend(["--config", f'model_reasoning_effort="{effort}"'])
    command.append("-")
    result = subprocess.run(
        command,
        input=task.prompt,
        capture_output=True,
        text=True,
        timeout=CODEX_TIMEOUT_S,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"codex exec failed (exit {result.returncode}): {result.stderr.strip()}")
    answer: str | None = None
    usage: CodexUsage | None = None
    completed = False
    for line in result.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError as error:
            raise RuntimeError("codex exec returned malformed JSONL") from error
        if event.get("type") in {"turn.failed", "error"}:
            raise RuntimeError("codex exec reported a failed turn")
        if event.get("type") == "item.completed":
            item = event.get("item", {})
            if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                answer = item["text"]
        elif event.get("type") == "turn.completed":
            completed = True
            counts = event.get("usage")
            if isinstance(counts, dict) and all(
                isinstance(counts.get(key), int) for key in ("input_tokens", "cached_input_tokens", "output_tokens")
            ):
                usage = CodexUsage(counts["input_tokens"], counts["cached_input_tokens"], counts["output_tokens"])
    if not completed or answer is None:
        raise RuntimeError("codex exec completed without an agent response")
    return CodexResult(text=answer, model=model, effort=effort, usage=usage)


def codex_call_fn(task: ProviderTask, *, model: str | None = None, effort: str | None = None) -> str:
    """Compatibility adapter for callers expecting only the final answer."""
    return codex_run(task, model=model, effort=effort).text


def local_run(task: ProviderTask, *, model: str | None = None) -> LocalResult:
    selected = model or os.environ.get("PROVIDER_ROUTER_LOCAL_MODEL", "").strip()
    if not selected:
        raise ValueError("local model is not configured; set PROVIDER_ROUTER_LOCAL_MODEL or pass model=")
    payload = json.dumps({"model": selected, "prompt": task.prompt, "stream": False}).encode()
    request = urllib.request.Request(OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=MUSE_TIMEOUT_S) as response:
            body = json.loads(response.read())
    except urllib.error.URLError as error:
        raise RuntimeError(f"ollama request failed: {error}") from error
    if not isinstance(body.get("response"), str) or body.get("done") is not True:
        raise RuntimeError("ollama returned no completed response")
    input_count = body.get("prompt_eval_count")
    output_count = body.get("eval_count")
    cached_count = body.get("prompt_eval_cached_count")
    duration = body.get("total_duration")
    usage = None
    if isinstance(input_count, int) and isinstance(output_count, int):
        usage = LocalUsage(
            input_tokens=input_count,
            cached_input_tokens=cached_count if isinstance(cached_count, int) else None,
            output_tokens=output_count,
            duration_ms=duration / 1_000_000 if isinstance(duration, int) else None,
        )
    return LocalResult(text=body["response"], model=selected, usage=usage)


def muse_call_fn(task: ProviderTask, *, model: str | None = None) -> str:
    """Compatibility adapter for callers expecting only local response text."""
    return local_run(task, model=model).text
