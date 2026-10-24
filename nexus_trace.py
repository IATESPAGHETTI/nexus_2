"""Distributed tracing and provenance for NEXUS (course requirement 9). Standard library only.

  * One `trace_id` per incident (W3C Trace Context format). The orchestrator puts a `traceparent` header on every
    A2A request; every agent service reads it (`TraceContextMiddleware`) and its AgentMonitor stamps the SAME trace_id
    on its model/tool records, so a single id links orchestrator -> A2A hop -> agent -> model call -> MCP tool call.
  * `build_trace` assembles the stored span tree from the incident's AGENT_MONITOR events.
  * `build_lineage` answers "why does the system believe this?": winning hypothesis -> evidence items (tool, arguments,
    agent, finding) -> critique -> recovery plan -> approval and execution, using only recorded facts.

Honest limits: span START times of an agent's inner calls are reconstructed from recorded durations in order (flagged
`start_estimated`); the export is NEXUS's own JSON, not an OTLP stream to an external collector.
"""

from __future__ import annotations

import contextvars
import re
import secrets
from dataclasses import dataclass
from typing import Any, Optional

_TRACEPARENT_RE = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")


@dataclass(frozen=True)
class TraceContext:
    trace_id: str
    span_id: str

    def traceparent(self) -> str:
        return f"00-{self.trace_id}-{self.span_id}-01"


_current: contextvars.ContextVar[Optional[TraceContext]] = contextvars.ContextVar("nexus_trace", default=None)


def new_trace_id() -> str:
    return secrets.token_hex(16)


def new_span_id() -> str:
    return secrets.token_hex(8)


def parse_traceparent(value: str | None) -> Optional[TraceContext]:
    match = _TRACEPARENT_RE.match((value or "").strip().lower())
    if not match or set(match.group(1)) == {"0"} or set(match.group(2)) == {"0"}:
        return None
    return TraceContext(match.group(1), match.group(2))


def current() -> Optional[TraceContext]:
    return _current.get()


def set_current(ctx: Optional[TraceContext]) -> contextvars.Token:
    return _current.set(ctx)


def start_trace() -> TraceContext:
    ctx = TraceContext(new_trace_id(), new_span_id())
    _current.set(ctx)
    return ctx


def child_context() -> Optional[TraceContext]:
    """A new span under the current trace (what one outgoing A2A call carries), or None when untraced."""
    ctx = _current.get()
    return TraceContext(ctx.trace_id, new_span_id()) if ctx else None


class TraceContextMiddleware:
    """Pure ASGI middleware for the agent services: read `traceparent`, expose it to the handler's task."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        token = None
        if scope.get("type") == "http":
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
            ctx = parse_traceparent(headers.get("traceparent"))
            if ctx:
                token = _current.set(ctx)
        try:
            await self.app(scope, receive, send)
        finally:
            if token is not None:
                _current.reset(token)


# ------------------------------------------------------------------ stored views


def _epoch(ts: Any) -> Optional[float]:
    """Seconds since the epoch for an ISO-8601 'Z' timestamp, or None."""
    try:
        from datetime import datetime, timezone

        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()
    except (TypeError, ValueError):
        return None


def build_trace(incident: dict, events: list[dict]) -> dict:
    """Span tree from recorded AGENT_MONITOR events. Pure; safe on partial data.

    Timing: the root span starts at the incident's created_at and ends at updated_at. An agent span ends at its
    AGENT_MONITOR event timestamp (whole seconds, as stored) and starts `total_ms` earlier. Inner spans are laid out in
    order from the agent's start using their recorded durations. All of this is reconstructed, so spans carry
    `time_estimated` / `start_estimated`; the numbers are good to about a second, not to the millisecond."""
    trace_id = incident.get("trace_id")
    root_id = incident.get("root_span_id") or "root"
    root_start = _epoch(incident.get("created_at"))
    root_end = _epoch(incident.get("updated_at"))
    spans: list[dict] = [{
        "span_id": root_id, "parent_span_id": None, "name": f"incident {incident.get('incident_id', '?')}",
        "kind": "incident", "status": incident.get("status"),
        "start_unix_s": root_start, "offset_ms": 0,
        "duration_ms": round((root_end - root_start) * 1000) if root_start is not None and root_end is not None else None,
        "time_estimated": True,
    }]
    hops = {}  # agent -> A2A task/context ids from A2A_MESSAGE_SENT
    for ev in events:
        if ev.get("event_type") == "A2A_MESSAGE_SENT":
            p = ev.get("payload") or {}
            hops[ev.get("target")] = {"task_id": p.get("task_id"), "context_id": p.get("context_id"), "span_id": p.get("span_id")}
    for ev in events:
        if ev.get("event_type") != "AGENT_MONITOR":
            continue
        mon = ev.get("payload") or {}
        agent = mon.get("agent") or ev.get("source")
        agent_span = mon.get("span_id") or f"{agent}-span"
        hop = hops.get(agent, {})
        records = mon.get("records") or []
        total = next((r.get("total_ms") for r in records if r.get("kind") == "agent_finished"), None)
        call_span = mon.get("parent_span_id")
        ended = _epoch(ev.get("timestamp"))
        agent_offset = None
        if root_start is not None and isinstance(mon.get("started_unix"), (int, float)):
            agent_offset = max(0, round((mon["started_unix"] - root_start) * 1000))     # the agent's own clock reading
        elif root_start is not None and ended is not None and total is not None:
            agent_offset = max(0, round((ended - root_start) * 1000) - total)           # fallback: event time minus duration
        if call_span:
            spans.append({"span_id": call_span, "parent_span_id": root_id, "name": f"a2a call -> {agent}",
                          "kind": "a2a_call", "a2a_task_id": hop.get("task_id"), "a2a_context_id": hop.get("context_id"),
                          "offset_ms": agent_offset, "duration_ms": total, "time_estimated": True})
        spans.append({
            "span_id": agent_span, "parent_span_id": call_span or root_id, "name": f"agent {agent}",
            "kind": "agent", "duration_ms": total, "trace_id_seen_by_agent": mon.get("trace_id"),
            "offset_ms": agent_offset, "time_estimated": True,
            "a2a_task_id": hop.get("task_id"), "a2a_context_id": hop.get("context_id"),
            "prompt_variant": mon.get("prompt_variant"), "errors": mon.get("errors", 0),
        })
        started: dict[str, dict] = {}
        cursor = 0
        for r in records:
            kind = r.get("kind", "")
            if kind in ("model_call_started", "tool_call_started"):
                started[kind.split("_")[0]] = r
            elif kind in ("model_call_finished", "tool_call_finished", "tool_error", "model_error", "crewai_step", "crewai_task_finished"):
                dur = r.get("duration_ms") or 0
                spans.append({
                    "span_id": r.get("span_id") or f"{agent_span}-{r.get('seq')}", "parent_span_id": agent_span,
                    "name": f"{'model' if kind.startswith('model') else 'tool'} {r.get('tool', '')}".strip(),
                    "kind": kind, "offset_ms": cursor, "duration_ms": dur, "start_estimated": True,
                    "abs_offset_ms": (agent_offset + cursor) if agent_offset is not None else None,
                    "ok": r.get("ok"), "prompt_tokens": r.get("prompt_tokens"), "completion_tokens": r.get("completion_tokens"),
                    "error_type": r.get("error_type"),
                })
                cursor += dur
    return {"trace_id": trace_id, "span_count": len(spans), "spans": spans,
            "note": "inner span start times are reconstructed from recorded durations (start_estimated)"}


def build_lineage(incident: dict, events: list[dict]) -> dict:
    """Provenance of the conclusion, from recorded facts only."""
    hyps = incident.get("hypotheses") or []
    winner = next((h for h in hyps if h.get("status") == "SUPPORTED"), None)
    findings = incident.get("agent_findings") or {}
    index: dict[str, dict] = {}
    for agent, finding in findings.items():
        for ev in (finding or {}).get("evidence", []) or []:
            index[ev.get("evidence_id")] = {
                "evidence_id": ev.get("evidence_id"), "tool": ev.get("tool"), "arguments": ev.get("arguments"),
                "agent": agent, "finding_id": (finding or {}).get("finding_id"), "collected_at": ev.get("timestamp"),
                "security_flags": (ev.get("result") or {}).get("security_flags") if isinstance(ev.get("result"), dict) else None,
            }
    critiques = incident.get("critic_results") or []
    plan = incident.get("recovery_plan") or {}
    ran = [e for e in events if e.get("event_type") in ("RECOVERY_EXECUTED", "RECOVERY_VERIFIED", "HUMAN_APPROVAL_GRANTED")]
    return {
        "trace_id": incident.get("trace_id"),
        "conclusion": winner.get("statement") if winner else None,
        "hypothesis_id": winner.get("hypothesis_id") if winner else None,
        "evidence": [index.get(i, {"evidence_id": i, "missing": True}) for i in (winner or {}).get("supporting_evidence_ids", [])],
        "contradicting_evidence": [index.get(i, {"evidence_id": i, "missing": True}) for i in (winner or {}).get("contradicting_evidence_ids", [])],
        "critique": {k: critiques[-1].get(k) for k in ("critique_id", "verdict", "framework")} if critiques else None,
        "recovery_plan_id": plan.get("plan_id"),
        "recovery_actions": [a.get("action") for a in plan.get("actions", [])],
        "later_steps": [{"event": e.get("event_type"), "at": e.get("timestamp")} for e in ran],
    }
