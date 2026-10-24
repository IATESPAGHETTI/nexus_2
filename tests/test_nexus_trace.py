"""nexus_trace: traceparent handling, ASGI propagation, span tree and provenance (pure, no network)."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import nexus_trace as nt  # noqa: E402


def test_traceparent_roundtrip_and_rejects_garbage():
    ctx = nt.TraceContext(nt.new_trace_id(), nt.new_span_id())
    assert nt.parse_traceparent(ctx.traceparent()) == ctx
    for bad in (None, "", "garbage", "00-" + "0" * 32 + "-" + "1" * 16 + "-01", "01-abc"):
        assert nt.parse_traceparent(bad) is None


def test_child_context_keeps_trace_id_changes_span():
    root = nt.start_trace()
    child = nt.child_context()
    assert child.trace_id == root.trace_id and child.span_id != root.span_id
    nt.set_current(None)
    assert nt.child_context() is None


def test_middleware_exposes_incoming_traceparent_to_the_handler_and_cleans_up():
    seen = {}

    async def app(scope, receive, send):
        seen["ctx"] = nt.current()

    ctx = nt.TraceContext(nt.new_trace_id(), nt.new_span_id())
    scope = {"type": "http", "headers": [(b"traceparent", ctx.traceparent().encode())]}
    nt.set_current(None)
    asyncio.run(nt.TraceContextMiddleware(app)(scope, None, None))
    assert seen["ctx"] == ctx
    assert nt.current() is None


def test_middleware_ignores_missing_or_bad_header():
    seen = {}

    async def app(scope, receive, send):
        seen["ctx"] = nt.current()

    nt.set_current(None)
    asyncio.run(nt.TraceContextMiddleware(app)({"type": "http", "headers": [(b"traceparent", b"nope")]}, None, None))
    assert seen["ctx"] is None


INCIDENT = {
    "incident_id": "INC-1", "trace_id": "a" * 32, "root_span_id": "r" * 16, "status": "DIAGNOSED",
    "hypotheses": [{"hypothesis_id": "H1", "statement": "s", "status": "SUPPORTED", "supporting_evidence_ids": ["ev-1", "ev-zzz"]}],
    "agent_findings": {"database_agent": {"finding_id": "find-1", "evidence": [
        {"evidence_id": "ev-1", "tool": "get_database_stats", "arguments": {}, "timestamp": "t", "result": {"ok": True}}]}},
    "critic_results": [{"critique_id": "crit-1", "verdict": "SUPPORTED", "framework": "crewai"}],
    "recovery_plan": {"plan_id": "RP-1", "actions": [{"action": "scale_resources"}]},
}
EVENTS = [
    {"event_type": "A2A_MESSAGE_SENT", "target": "database_agent", "payload": {"task_id": "t1", "context_id": "c1"}},
    {"event_type": "AGENT_MONITOR", "source": "database_agent", "payload": {
        "agent": "database_agent", "trace_id": "a" * 32, "span_id": "s1", "parent_span_id": "p1", "prompt_variant": "default",
        "errors": 0, "records": [
            {"seq": 1, "kind": "model_call_started"},
            {"seq": 2, "kind": "model_call_finished", "duration_ms": 100, "prompt_tokens": 50},
            {"seq": 3, "kind": "tool_call_finished", "tool": "get_database_stats", "duration_ms": 30, "ok": True},
            {"seq": 4, "kind": "agent_finished", "total_ms": 150}]}},
    {"event_type": "RECOVERY_EXECUTED", "timestamp": "t9"},
]


def test_build_trace_makes_a_connected_span_tree_with_the_wire_trace_id():
    tr = nt.build_trace(INCIDENT, EVENTS)
    by_id = {s["span_id"]: s for s in tr["spans"]}
    agent = by_id["s1"]
    assert agent["trace_id_seen_by_agent"] == INCIDENT["trace_id"]  # same id arrived over the wire
    assert agent["parent_span_id"] == "p1" and by_id["p1"]["parent_span_id"] == "r" * 16
    assert by_id["p1"]["a2a_task_id"] == "t1"
    kids = [s for s in tr["spans"] if s["parent_span_id"] == "s1"]
    assert [k["offset_ms"] for k in kids] == [0, 100] and all(k["start_estimated"] for k in kids)
    ids = {s["span_id"] for s in tr["spans"]}
    assert all(s["parent_span_id"] in ids for s in tr["spans"] if s["parent_span_id"])


def test_build_lineage_links_conclusion_to_evidence_and_flags_missing_ids():
    lin = nt.build_lineage(INCIDENT, EVENTS)
    assert lin["conclusion"] == "s" and lin["critique"]["framework"] == "crewai"
    assert lin["evidence"][0]["tool"] == "get_database_stats" and lin["evidence"][0]["agent"] == "database_agent"
    assert lin["evidence"][1] == {"evidence_id": "ev-zzz", "missing": True}  # never invented
    assert lin["recovery_actions"] == ["scale_resources"] and lin["later_steps"][0]["event"] == "RECOVERY_EXECUTED"


def test_builders_survive_empty_input():
    assert nt.build_trace({}, [])["span_count"] == 1
    assert nt.build_lineage({}, [])["conclusion"] is None
