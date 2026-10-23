"""Run a small black-box tool-routing evaluation against a local backend.

This suite intentionally avoids confirming destructive actions. It evaluates
tool selection and verifies that write tools are not called on the preparation
turn. Start the API and run: ``python evals/run_evals.py``.
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import time
from pathlib import Path

import requests


BASE_URL = os.getenv("EVAL_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
CASES_PATH = Path(__file__).with_name("cases.json")
HTTP = requests.Session()


def authenticate() -> None:
    username = os.getenv("EVAL_USERNAME", "agent_eval")
    password = os.getenv("EVAL_PASSWORD", "LocalEvalPassword123!")
    response = HTTP.post(
        f"{BASE_URL}/api/auth/login",
        json={"username": username, "password": password},
        timeout=10,
    )
    if response.status_code == 401:
        response = HTTP.post(
            f"{BASE_URL}/api/auth/register",
            json={"username": username, "password": password, "display_name": "Agent 评测"},
            timeout=10,
        )
    response.raise_for_status()


def main() -> int:
    authenticate()
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    results = []
    latencies = []

    for case in cases:
        started = time.perf_counter()
        response = HTTP.post(
            f"{BASE_URL}/api/chat",
            json={"message": case["message"]},
            timeout=70,
        )
        latency_ms = (time.perf_counter() - started) * 1000
        latencies.append(latency_ms)
        response.raise_for_status()
        payload = response.json()
        actual = set(payload.get("tools_used", []))
        required = set(case.get("required_tools", []))
        forbidden = set(case.get("forbidden_tools", []))
        passed = required.issubset(actual) and actual.isdisjoint(forbidden)
        results.append(passed)

        marker = "PASS" if passed else "FAIL"
        print(
            f"[{marker}] {case['id']}: tools={sorted(actual)} "
            f"latency={latency_ms:.0f}ms"
        )

        conversation_id = payload.get("conversation_id")
        conversation_token = payload.get("conversation_token")
        if conversation_id and conversation_token:
            HTTP.delete(
                f"{BASE_URL}/api/history/{conversation_id}",
                headers={"X-Conversation-Token": conversation_token},
                timeout=10,
            )

    pass_count = sum(results)
    p50 = statistics.median(latencies) if latencies else 0
    p95_index = max(0, round(0.95 * len(latencies) + 0.5) - 1)
    p95 = sorted(latencies)[p95_index] if latencies else 0
    print(
        f"\nTool-policy accuracy: {pass_count}/{len(results)} "
        f"({pass_count / len(results):.1%}); p50={p50:.0f}ms; p95={p95:.0f}ms"
    )
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
