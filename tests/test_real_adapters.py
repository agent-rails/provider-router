from __future__ import annotations

import json
import subprocess

import pytest
from real_adapters import codex_call_fn, codex_run, local_run, muse_call_fn

from provider_router.types import ProviderTask


def test_codex_adapter_passes_model_effort_via_argv_and_prompt_via_stdin(monkeypatch: pytest.MonkeyPatch):
    seen = {}

    def fake_run(command, **kwargs):
        seen.update(command=command, kwargs=kwargs)
        events = [
            {"type": "item.completed", "item": {"type": "agent_message", "text": "done"}},
            {"type": "turn.completed", "usage": {"input_tokens": 100, "cached_input_tokens": 80, "output_tokens": 12}},
        ]
        return subprocess.CompletedProcess(command, 0, "\n".join(json.dumps(event) for event in events), "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = codex_run(ProviderTask(prompt="private prompt"), model="gpt-6-sol", effort="medium")

    assert seen["command"] == [
        "codex",
        "exec",
        "-s",
        "read-only",
        "--skip-git-repo-check",
        "--json",
        "--model",
        "gpt-6-sol",
        "--config",
        'model_reasoning_effort="medium"',
        "-",
    ]
    assert seen["kwargs"]["input"] == "private prompt"
    assert "private prompt" not in str(seen["command"])
    assert (result.text, result.model, result.effort) == ("done", "gpt-6-sol", "medium")
    assert result.usage is not None and result.usage.cached_input_tokens == 80


def test_usage_unknown_when_cli_omits_counts(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command,
            0,
            "\n".join(
                (
                    json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "answer"}}),
                    json.dumps({"type": "turn.completed"}),
                )
            ),
            "",
        ),
    )
    assert codex_run(ProviderTask(prompt="x")).usage is None
    assert codex_call_fn(ProviderTask(prompt="x")) == "answer"


def test_no_agent_message_fails_closed(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 0, json.dumps({"type": "turn.completed", "usage": {}}), ""
        ),
    )
    with pytest.raises(RuntimeError, match="without an agent response"):
        codex_run(ProviderTask(prompt="x"))


def test_failed_turn_fails_even_if_process_exits_zero(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0, json.dumps({"type": "turn.failed"}), ""),
    )
    with pytest.raises(RuntimeError, match="failed turn"):
        codex_run(ProviderTask(prompt="x"))


def test_bad_effort_rejected_before_spawning():
    with pytest.raises(ValueError, match="unsupported"):
        codex_run(ProviderTask(prompt="x"), effort="mega")


def test_local_adapter_requires_explicit_model(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("PROVIDER_ROUTER_LOCAL_MODEL", raising=False)
    with pytest.raises(ValueError, match="local model is not configured"):
        muse_call_fn(ProviderTask(prompt="x"))


def test_local_usage_preserves_unknown_cached_count(monkeypatch: pytest.MonkeyPatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self):
            return json.dumps({"response": "done", "done": True, "prompt_eval_count": 8, "eval_count": 3}).encode()

    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: Response())
    result = local_run(ProviderTask(prompt="x"), model="test:small")
    assert result.text == "done"
    assert result.usage is not None
    assert (result.usage.input_tokens, result.usage.cached_input_tokens, result.usage.output_tokens) == (8, None, 3)
