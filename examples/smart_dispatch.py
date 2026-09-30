"""Opt-in, read-only Codex/local dispatch using model-router's task policy.

Run with PYTHONPATH=../model-router after installing both sibling projects.
The default prints a plan; --execute incurs model usage.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from dataclasses import asdict
from datetime import date
from pathlib import Path

from model_router import LocalQualification, Runtime, TaskRequest, infer_task, plan_task
from real_adapters import codex_run, local_run

from provider_router import ProviderTask


def _installed_digest(model: str) -> str | None:
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3) as response:
            data = json.load(response)
    except (OSError, urllib.error.URLError, ValueError):
        return None
    for item in data.get("models", []):
        if item.get("name") == model:
            return item.get("digest")
    return None


def _qualification(path: Path) -> LocalQualification:
    data = json.loads(path.read_text())
    return LocalQualification(
        model=data["model"],
        digest=data["digest"],
        categories=frozenset(data["categories"]),
        evidence_ref=data["evidence_ref"],
        valid_until=date.fromisoformat(data["valid_until"]),
        max_prompt_chars=int(data["max_prompt_chars"]),
        p95_latency_ms=int(data["p95_latency_ms"]),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--category", help="optional trusted category; otherwise infer from the task")
    parser.add_argument("--tag", action="append", default=[])
    parser.add_argument("--workstreams", type=int, default=1)
    parser.add_argument("--local-qualification", type=Path)
    parser.add_argument("--max-latency-ms", type=int)
    parser.add_argument("--execute", action="store_true", help="run the selected model; default is a dry plan")
    args = parser.parse_args()
    prompt = sys.stdin.read()
    if not prompt.strip():
        parser.error("supply a task prompt on stdin")

    inferred = infer_task(prompt) if args.category is None else None
    task_request = (
        TaskRequest(
            prompt=prompt,
            category=args.category,
            tags=frozenset(args.tag),
            independent_workstreams=args.workstreams,
        )
        if inferred is None
        else TaskRequest(
            prompt=prompt,
            category=inferred.request.category,
            tags=inferred.request.tags | frozenset(args.tag),
            independent_workstreams=args.workstreams,
            metadata_trusted=False,
        )
    )
    qualification = _qualification(args.local_qualification) if args.local_qualification else None
    digest = _installed_digest(qualification.model) if qualification else None
    plan = plan_task(
        task_request,
        local=qualification,
        installed_digest=digest,
        max_latency_ms=args.max_latency_ms,
    )
    print(
        json.dumps(
            {
                "runtime": plan.runtime.value,
                "model": plan.model,
                "effort": plan.effort,
                "workflow": plan.codex.workflow.value,
                "workflow_steps": plan.codex.workflow_steps,
                "suggest_delegation": plan.codex.suggest_delegation,
                "context_files": plan.codex.context_files,
                "source": plan.codex.source.value,
                "category": task_request.category,
                "classification": inferred.rule if inferred else "caller supplied category",
                "reason": plan.reason,
                "qualification_ref": plan.qualification_ref,
                "rejections": plan.rejections,
            }
        ),
        file=sys.stderr,
    )
    if not args.execute:
        return

    task = ProviderTask(prompt=prompt, category=task_request.category, tags=task_request.tags)
    if plan.runtime == Runtime.CODEX:
        result = codex_run(task, model=plan.model, effort=plan.effort)
        print(result.text)
        print(json.dumps({"usage": asdict(result.usage) if result.usage else None}), file=sys.stderr)
    else:
        result = local_run(task, model=plan.model)
        print(result.text)
        print(
            json.dumps(
                {"usage": asdict(result.usage) if result.usage else None, "qualification_ref": plan.qualification_ref}
            ),
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
