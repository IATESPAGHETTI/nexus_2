"""Bounded, read-only HTTP client to production/ used ONLY by the
single-agent baseline (evaluation/baselines.py) -- the baseline gets exactly
one flat evidence snapshot, not iterative tool access, which is precisely
what makes it a "single-agent, no tool loop" baseline rather than a second
diagnostic agent. Separate module from mcp/production_client.py and
guardrails/production_client.py on purpose (dependency isolation, same
principle as every other top-level folder).
"""

from __future__ import annotations

import os

import httpx

PRODUCTION_BASE_URL = os.environ.get("PRODUCTION_BASE_URL", "http://127.0.0.1:8001")  # 127.0.0.1 not "localhost": on Windows "localhost" costs ~2 s per request (IPv6 tried first)
HTTP_TIMEOUT_SECONDS = 5.0


def _get(path: str, attempts: int = 4) -> dict:
    """GET with retry on 5xx. The resource_exhaustion fault makes ANY non-admin request
    (observability endpoints included) fail ~8% of the time, so a single failed read is
    noise from the fault, not a reason to abandon the snapshot."""
    for attempt in range(attempts):
        response = httpx.get(f"{PRODUCTION_BASE_URL}{path}", timeout=HTTP_TIMEOUT_SECONDS)
        if response.status_code < 500 or attempt == attempts - 1:
            break
    response.raise_for_status()
    return response.json()


def snapshot() -> dict:
    """One flat pull of the same read-only signals the diagnostic agents
    gather over many MCP tool calls -- metrics, recent logs, recent changes,
    db diagnostics -- collapsed into a single dict for a single LLM call."""
    return {
        "metrics": _get("/metrics"),
        "recent_logs": _get("/logs?limit=20").get("entries", []),
        "recent_changes": _get("/changes?limit=5").get("changes", []),
        "db_diagnostics": _get("/db/diagnostics"),
    }
