"""Real HTTP client bridging NEXUS orchestration activity (Phase 6) into the
backend's incident state + event store (docs/EVENT_SCHEMA.md, root CLAUDE.md
section 15/16).

Every call here mirrors something that just actually happened -- a real A2A
round trip completing, a real MCP evidence item already present inside a
Finding, a hypothesis/critique a reasoning agent actually produced. Nothing is
fabricated here.

This is also how `mcp/audit.py`'s and the A2A layer's activity reaches the
shared event store: `mcp/audit.py` is a local, in-process audit log inside
each diagnostic agent's own OS process (reached over stdio, with no
network-queryable API by design -- see mcp/CLAUDE.md). `orchestrator/investigation.py`
emits `MCP_TOOL_CALL`/`MCP_TOOL_RESULT` events here for every evidence item
already present in a Finding it received over real A2A -- the exact same real
tool/arguments/result facts `mcp/audit.py` records privately, carried to the
backend through the Finding that already flows through the system, not a
second network hop into the MCP server's own process. This is documented
explicitly as a known scope limit in docs/PROJECT_STATE.md: the backend event
store does not query `mcp/audit.py`'s deque directly.
"""

from __future__ import annotations

import os
from typing import Any

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import nexus_trace  # noqa: E402

BACKEND_URL = os.environ.get("NEXUS_BACKEND_URL", "http://127.0.0.1:8000")
_TIMEOUT = 10.0


def create_incident(description: str) -> str:
    response = httpx.post(
        f"{BACKEND_URL}/incidents", json={"description": description}, timeout=_TIMEOUT
    )
    response.raise_for_status()
    return response.json()["incident_id"]


def emit_event(
    incident_id: str,
    event_type: str,
    source: str,
    target: str | None = None,
    status: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict:
    payload = dict(payload or {})
    ctx = nexus_trace.current()
    if ctx is not None:
        payload.setdefault("trace_id", ctx.trace_id)
    body = {
        "event_type": event_type,
        "source": source,
        "target": target,
        "status": status,
        "payload": payload,
    }
    response = httpx.post(
        f"{BACKEND_URL}/incidents/{incident_id}/events", json=body, timeout=_TIMEOUT
    )
    response.raise_for_status()
    return response.json()


def emit_monitor(incident_id: str, agent: str, monitoring: Any) -> None:
    """Stores an agent's callback trace (agents/common/callbacks.py) as an
    AGENT_MONITOR event. Fail-soft: monitoring must never break an investigation."""
    if not isinstance(monitoring, dict):
        return
    try:
        emit_event(
            incident_id,
            "AGENT_MONITOR",
            source=agent,
            status="errors" if monitoring.get("errors") else "ok",
            payload=monitoring,
        )
    except Exception:  # noqa: BLE001
        pass


def update_state(incident_id: str, **fields: Any) -> dict:
    response = httpx.post(
        f"{BACKEND_URL}/incidents/{incident_id}/state", json=fields, timeout=_TIMEOUT
    )
    response.raise_for_status()
    return response.json()


def get_incident(incident_id: str) -> dict:
    response = httpx.get(f"{BACKEND_URL}/incidents/{incident_id}", timeout=_TIMEOUT)
    response.raise_for_status()
    return response.json()


def get_events(incident_id: str) -> list[dict]:
    response = httpx.get(f"{BACKEND_URL}/incidents/{incident_id}/events", timeout=_TIMEOUT)
    response.raise_for_status()
    return response.json()["events"]
