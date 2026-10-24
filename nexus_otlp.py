"""OpenTelemetry (OTLP/HTTP JSON) export of a finished investigation's trace (course requirement 9).

Converts the stored span tree (`nexus_trace.build_trace`) into the standard OTLP JSON payload and POSTs it to a collector or
Jaeger when NEXUS_OTLP_ENDPOINT is set (for example http://jaeger:4318/v1/traces). Speaking the protocol directly (it is plain
JSON over HTTP) avoids adding the OpenTelemetry SDK, whose version pins conflict with the ADK stack's.

Each agent becomes its OWN service in the trace (service.name = the agent), the orchestrator is `nexus-orchestrator`, so a trace
viewer shows a genuine cross-service trace: orchestrator -> A2A call -> agent -> model / tool calls. The trace id is the one
that travelled over the wire as a W3C traceparent header.

Honest limits: span times are reconstructed (root from created_at/updated_at in whole seconds, agents from their own clock
readings, inner calls from recorded durations laid out in order), so they are accurate to roughly a second for the root and to
the millisecond only for durations. Export is best-effort and never changes an investigation's outcome.
"""

from __future__ import annotations

import os
from typing import Any

SPAN_KIND = {"incident": 1, "a2a_call": 3, "agent": 2}   # INTERNAL, CLIENT, SERVER (everything else INTERNAL)
SCOPE = {"name": "nexus", "version": "1.0"}


def _attr(key: str, value: Any) -> dict | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    if isinstance(value, float):
        return {"key": key, "value": {"doubleValue": value}}
    return {"key": key, "value": {"stringValue": str(value)[:300]}}


def _attrs(span: dict, incident_id: str) -> list[dict]:
    pairs = [
        ("nexus.incident_id", incident_id), ("nexus.kind", span.get("kind")), ("nexus.time_estimated", True),
        ("nexus.a2a_task_id", span.get("a2a_task_id")), ("nexus.a2a_context_id", span.get("a2a_context_id")),
        ("nexus.prompt_variant", span.get("prompt_variant")), ("nexus.prompt_tokens", span.get("prompt_tokens")),
        ("nexus.completion_tokens", span.get("completion_tokens")), ("nexus.tool_ok", span.get("ok")),
        ("nexus.error_type", span.get("error_type")), ("nexus.trace_id_seen_by_agent", span.get("trace_id_seen_by_agent")),
    ]
    return [a for a in (_attr(k, v) for k, v in pairs) if a]


def _service_of(span: dict, parents: dict[str, dict]) -> str:
    """Service a span belongs to: the nearest agent ancestor (or itself), else the orchestrator."""
    cur = span
    for _ in range(6):
        if cur.get("kind") == "agent":
            return cur["name"].replace("agent ", "", 1)
        parent = parents.get(cur.get("parent_span_id") or "")
        if parent is None:
            break
        cur = parent
    return "nexus-orchestrator"


def to_otlp(trace: dict, incident: dict) -> dict:
    """OTLP/HTTP JSON payload (`{"resourceSpans": [...]}`) for one incident's trace."""
    trace_id = trace.get("trace_id") or ""
    spans = trace.get("spans") or []
    if len(trace_id) != 32 or not spans:
        return {"resourceSpans": []}
    incident_id = str(incident.get("incident_id", ""))
    by_id = {s["span_id"]: s for s in spans}
    root = spans[0]
    root_start = root.get("start_unix_s")
    if root_start is None:
        return {"resourceSpans": []}

    def start_ms(s: dict) -> float:
        for key in ("abs_offset_ms", "offset_ms"):
            if s.get("kind") != "incident" and key == "offset_ms" and s.get("parent_span_id") and by_id.get(s["parent_span_id"], {}).get("kind") == "agent":
                continue    # an inner span's offset_ms is relative to its agent, not to the root
            if isinstance(s.get(key), (int, float)):
                return float(s[key])
        parent = by_id.get(s.get("parent_span_id") or "")
        return start_ms(parent) if parent else 0.0

    per_service: dict[str, list[dict]] = {}
    for s in spans:
        start = root_start * 1000 + start_ms(s)
        duration = s.get("duration_ms") if isinstance(s.get("duration_ms"), (int, float)) else 0
        failed = bool(s.get("errors")) or s.get("ok") is False or s.get("kind") in ("tool_error", "model_error")
        otlp_span = {
            "traceId": trace_id, "spanId": s["span_id"],
            "parentSpanId": s.get("parent_span_id") if s.get("parent_span_id") in by_id else "",
            "name": s.get("name", s.get("kind", "span")), "kind": SPAN_KIND.get(s.get("kind"), 1),
            "startTimeUnixNano": str(int(start * 1_000_000)), "endTimeUnixNano": str(int((start + duration) * 1_000_000)),
            "attributes": _attrs(s, incident_id), "status": {"code": 2 if failed else 1},
        }
        per_service.setdefault(_service_of(s, by_id), []).append(otlp_span)

    return {"resourceSpans": [
        {"resource": {"attributes": [_attr("service.name", service), _attr("nexus.incident_id", incident_id)]},
         "scopeSpans": [{"scope": SCOPE, "spans": batch}]}
        for service, batch in sorted(per_service.items())
    ]}


def endpoint() -> str:
    return os.environ.get("NEXUS_OTLP_ENDPOINT", "").strip()


def export(trace: dict, incident: dict, timeout: float = 5.0) -> dict:
    """POST the trace to NEXUS_OTLP_ENDPOINT. Returns {"exported": bool, ...}; never raises."""
    url = endpoint()
    if not url:
        return {"exported": False, "reason": "NEXUS_OTLP_ENDPOINT is not set"}
    payload = to_otlp(trace, incident)
    if not payload["resourceSpans"]:
        return {"exported": False, "reason": "no exportable spans"}
    try:
        import httpx

        response = httpx.post(url, json=payload, timeout=timeout)
        ok = response.status_code < 300
        return {"exported": ok, "status": response.status_code, "span_count": sum(len(s["spans"]) for r in payload["resourceSpans"] for s in r["scopeSpans"])}
    except Exception as exc:  # noqa: BLE001 -- tracing must never break an investigation
        return {"exported": False, "reason": f"{type(exc).__name__}"}
