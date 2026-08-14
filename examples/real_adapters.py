from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request

from provider_router.types import ProviderTask

CODEX_TIMEOUT_S = 120
MUSE_TIMEOUT_S = 180
MUSE_MODEL = "muse-glimmer:30b-mlx"
OLLAMA_URL = "http://localhost:11434/api/generate"


def codex_call_fn(task: ProviderTask) -> str:
    result = subprocess.run(
        ["codex", "exec", "-s", "read-only", "--skip-git-repo-check", task.prompt],
        capture_output=True,
        text=True,
        timeout=CODEX_TIMEOUT_S,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"codex exec failed (exit {result.returncode}): {result.stderr.strip()}")
    return result.stdout


def muse_call_fn(task: ProviderTask) -> str:
    payload = json.dumps({"model": MUSE_MODEL, "prompt": task.prompt, "stream": False}).encode()
    request = urllib.request.Request(OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=MUSE_TIMEOUT_S) as response:
            body = json.loads(response.read())
    except urllib.error.URLError as error:
        raise RuntimeError(f"ollama request failed: {error}") from error
    return body["response"]
