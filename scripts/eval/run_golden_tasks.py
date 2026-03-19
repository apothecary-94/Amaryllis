#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import statistics
import sys
import time
from typing import Any

import httpx


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class EvaluationSummary:
    passed: int = 0
    failed: int = 0
    skipped: int = 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run golden tasks against Amaryllis chat API.")
    parser.add_argument(
        "--tasks-file",
        default="eval/golden_tasks/dev_v1.json",
        help="Path to golden task suite JSON.",
    )
    parser.add_argument(
        "--endpoint",
        default=os.getenv("AMARYLLIS_ENDPOINT", "http://localhost:8000"),
        help="Runtime API endpoint.",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("AMARYLLIS_TOKEN", ""),
        help="Bearer token for auth-enabled runtime.",
    )
    parser.add_argument(
        "--model",
        default="",
        help="Optional model override for chat request.",
    )
    parser.add_argument(
        "--timeout-sec",
        type=float,
        default=60.0,
        help="HTTP timeout for each task execution.",
    )
    parser.add_argument(
        "--max-tasks",
        type=int,
        default=0,
        help="Run only first N tasks (0 means all).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return non-zero exit code if any task fails.",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate suite schema only, skip execution.",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional output report path. Default: eval/reports/golden_tasks_<timestamp>.json",
    )
    return parser.parse_args()


def _load_suite(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_suite(suite: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(suite, dict):
        return ["suite root must be an object"]
    tasks = suite.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        errors.append("suite.tasks must be a non-empty list")
        return errors

    seen_ids: set[str] = set()
    for idx, task in enumerate(tasks):
        location = f"tasks[{idx}]"
        if not isinstance(task, dict):
            errors.append(f"{location} must be an object")
            continue

        task_id = str(task.get("id") or "").strip()
        if not task_id:
            errors.append(f"{location}.id is required")
        elif task_id in seen_ids:
            errors.append(f"duplicate task id: {task_id}")
        else:
            seen_ids.add(task_id)

        for field in ("title", "prompt", "category"):
            if not str(task.get(field) or "").strip():
                errors.append(f"{location}.{field} is required")

        expected = task.get("expected")
        if not isinstance(expected, dict):
            errors.append(f"{location}.expected must be an object")
            continue

        min_chars = expected.get("min_response_chars", 0)
        if not isinstance(min_chars, int) or min_chars < 0:
            errors.append(f"{location}.expected.min_response_chars must be >= 0 int")

        for field in ("required_keywords", "forbidden_keywords"):
            value = expected.get(field, [])
            if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                errors.append(f"{location}.expected.{field} must be list[str]")

        for bool_field in (
            "requires_numbered_list",
            "requires_bullets",
            "requires_code_block",
            "requires_table_like_output",
        ):
            value = expected.get(bool_field)
            if value is not None and not isinstance(value, bool):
                errors.append(f"{location}.expected.{bool_field} must be bool when provided")

    return errors


def _has_numbered_list(text: str) -> bool:
    return bool(re.search(r"(?m)^\s*\d+\.\s+", text))


def _has_bullets(text: str) -> bool:
    return bool(re.search(r"(?m)^\s*[-*]\s+", text))


def _has_code_block(text: str) -> bool:
    return text.count("```") >= 2


def _has_table_like_output(text: str) -> bool:
    lines_with_pipe = [line for line in text.splitlines() if "|" in line]
    return len(lines_with_pipe) >= 2


def _extract_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str):
                    return content
    # fallback: runtime-specific field
    output = payload.get("output")
    if isinstance(output, str):
        return output
    return ""


def _evaluate_response(task: dict[str, Any], response_text: str) -> dict[str, Any]:
    expected = task.get("expected") if isinstance(task.get("expected"), dict) else {}
    checks: list[dict[str, Any]] = []

    min_chars = int(expected.get("min_response_chars", 0))
    checks.append(
        {
            "name": "min_response_chars",
            "ok": len(response_text) >= min_chars,
            "expected": min_chars,
            "actual": len(response_text),
        }
    )

    required_keywords = [str(item).strip().lower() for item in expected.get("required_keywords", []) if str(item).strip()]
    lowered = response_text.lower()
    for keyword in required_keywords:
        checks.append(
            {
                "name": f"required_keyword:{keyword}",
                "ok": keyword in lowered,
                "expected": keyword,
                "actual": keyword in lowered,
            }
        )

    forbidden_keywords = [str(item).strip().lower() for item in expected.get("forbidden_keywords", []) if str(item).strip()]
    for keyword in forbidden_keywords:
        present = keyword in lowered
        checks.append(
            {
                "name": f"forbidden_keyword:{keyword}",
                "ok": not present,
                "expected": "absent",
                "actual": "present" if present else "absent",
            }
        )

    if expected.get("requires_numbered_list") is True:
        checks.append({"name": "requires_numbered_list", "ok": _has_numbered_list(response_text)})
    if expected.get("requires_bullets") is True:
        checks.append({"name": "requires_bullets", "ok": _has_bullets(response_text)})
    if expected.get("requires_code_block") is True:
        checks.append({"name": "requires_code_block", "ok": _has_code_block(response_text)})
    if expected.get("requires_table_like_output") is True:
        checks.append({"name": "requires_table_like_output", "ok": _has_table_like_output(response_text)})

    passed = all(bool(item.get("ok")) for item in checks)
    return {
        "passed": passed,
        "checks": checks,
    }


def _default_output_path() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path("eval/reports") / f"golden_tasks_{stamp}.json"


def main() -> int:
    args = _parse_args()
    tasks_file = Path(args.tasks_file)
    if not tasks_file.exists():
        print(f"tasks file not found: {tasks_file}", file=sys.stderr)
        return 2

    suite = _load_suite(tasks_file)
    validation_errors = _validate_suite(suite)
    if validation_errors:
        print("suite validation failed:", file=sys.stderr)
        for err in validation_errors:
            print(f"- {err}", file=sys.stderr)
        return 2

    if args.validate_only:
        print(f"suite validation OK: {tasks_file}")
        return 0

    tasks = list(suite.get("tasks", []))
    if args.max_tasks and args.max_tasks > 0:
        tasks = tasks[: args.max_tasks]

    endpoint = str(args.endpoint).rstrip("/")
    headers = {"Content-Type": "application/json"}
    if str(args.token).strip():
        headers["Authorization"] = f"Bearer {str(args.token).strip()}"

    summary = EvaluationSummary()
    results: list[dict[str, Any]] = []
    latencies: list[float] = []

    with httpx.Client(timeout=args.timeout_sec) as client:
        for task in tasks:
            task_id = str(task.get("id") or "")
            prompt = str(task.get("prompt") or "")
            mode = str(task.get("mode") or "balanced")

            payload: dict[str, Any] = {
                "messages": [{"role": "user", "content": prompt}],
                "routing": {
                    "mode": mode,
                    "require_stream": False,
                },
                "stream": False,
            }
            if str(args.model).strip():
                payload["model"] = str(args.model).strip()

            started = time.perf_counter()
            response_text = ""
            request_error = ""
            status_code: int | None = None
            try:
                response = client.post(f"{endpoint}/v1/chat/completions", headers=headers, json=payload)
                status_code = int(response.status_code)
                response.raise_for_status()
                response_json = response.json()
                response_text = _extract_content(response_json)
            except Exception as exc:
                request_error = str(exc)

            latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
            latencies.append(latency_ms)

            if request_error:
                summary.failed += 1
                results.append(
                    {
                        "id": task_id,
                        "title": task.get("title"),
                        "passed": False,
                        "status_code": status_code,
                        "latency_ms": latency_ms,
                        "error": request_error,
                        "checks": [],
                    }
                )
                continue

            evaluation = _evaluate_response(task, response_text)
            passed = bool(evaluation.get("passed"))
            if passed:
                summary.passed += 1
            else:
                summary.failed += 1

            results.append(
                {
                    "id": task_id,
                    "title": task.get("title"),
                    "passed": passed,
                    "status_code": status_code,
                    "latency_ms": latency_ms,
                    "response_chars": len(response_text),
                    "checks": evaluation.get("checks", []),
                }
            )

    avg_latency = round(statistics.mean(latencies), 2) if latencies else 0.0
    p95_latency = round(_percentile(latencies, 95), 2) if latencies else 0.0

    report = {
        "generated_at": _utc_now_iso(),
        "suite": suite.get("suite"),
        "suite_version": suite.get("version"),
        "tasks_file": str(tasks_file),
        "endpoint": endpoint,
        "strict": bool(args.strict),
        "summary": {
            "total": len(results),
            "passed": summary.passed,
            "failed": summary.failed,
            "skipped": summary.skipped,
            "pass_rate": round((summary.passed / len(results)) * 100.0, 2) if results else 0.0,
            "avg_latency_ms": avg_latency,
            "p95_latency_ms": p95_latency,
        },
        "results": results,
    }

    output_path = Path(args.output) if str(args.output).strip() else _default_output_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"report: {output_path}")
    print(json.dumps(report["summary"], ensure_ascii=False))

    if args.strict and summary.failed > 0:
        return 1
    return 0


def _percentile(values: list[float], p: int) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    rank = max(0, min(len(sorted_values) - 1, int(round((p / 100.0) * (len(sorted_values) - 1)))))
    return float(sorted_values[rank])


if __name__ == "__main__":
    raise SystemExit(main())
