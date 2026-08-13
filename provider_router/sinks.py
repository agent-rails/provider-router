from __future__ import annotations

import json
from pathlib import Path

from provider_router.telemetry import FailoverEvent


def event_to_json(event: FailoverEvent) -> dict:
    return {
        "timestamp": event.timestamp.isoformat(),
        "category": event.category,
        "tags": sorted(event.tags),
        "prompt_chars": event.prompt_chars,
        "attempt": {
            "provider": event.attempt.provider.value,
            "succeeded": event.attempt.succeeded,
            "failure_reason": event.attempt.failure_reason.value if event.attempt.failure_reason else None,
            "error": event.attempt.error,
            "duration_ms": event.attempt.duration_ms,
        },
    }


class JsonlSink:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path).expanduser()
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, event: FailoverEvent) -> None:
        line = json.dumps(event_to_json(event))
        with self._path.open("a") as f:
            f.write(line + "\n")

    def read_all(self) -> list[dict]:
        if not self._path.exists():
            return []
        with self._path.open() as f:
            return [json.loads(line) for line in f if line.strip()]
