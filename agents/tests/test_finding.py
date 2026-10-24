"""Unit tests for agents/common/finding.py — pure logic, no LLM/network calls."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))

from finding import build_finding, make_evidence_item  # noqa: E402


def test_evidence_item_has_unique_id_and_timestamp():
    item = make_evidence_item("get_metrics", {}, {"ok": True, "request_count": 5})
    assert item["evidence_id"].startswith("ev-")
    assert item["tool"] == "get_metrics"
    assert item["result"]["request_count"] == 5
    assert "timestamp" in item


def test_build_finding_parses_confidence_line():
    evidence = [make_evidence_item("get_metrics", {}, {"ok": True})]
    finding = build_finding(
        "metrics_agent", evidence, "Everything looks fine.\nCONFIDENCE: 0.87"
    )
    assert finding["confidence"] == 0.87
    assert "CONFIDENCE" not in finding["interpretation"]
    assert finding["interpretation"] == "Everything looks fine."
    assert finding["limitations"] == "none noted"


def test_build_finding_parses_markdown_bold_confidence_line():
    # Real model output observed during Phase 5 testing: "**CONFIDENCE:** 0.68"
    # instead of the plain "CONFIDENCE: 0.68" form.
    evidence = [make_evidence_item("get_git_diff", {}, {"ok": True})]
    finding = build_finding(
        "change_analysis_agent",
        evidence,
        "The most recent change looks unrelated to this failure.\n\n**CONFIDENCE:** 0.68",
    )
    assert finding["confidence"] == 0.68
    assert "CONFIDENCE" not in finding["interpretation"]
    assert finding["interpretation"] == "The most recent change looks unrelated to this failure."


def test_build_finding_defaults_confidence_when_missing():
    evidence = [make_evidence_item("get_metrics", {}, {"ok": True})]
    finding = build_finding("metrics_agent", evidence, "Everything looks fine, no number given.")
    assert finding["confidence"] == 0.3
    assert "did not report a parseable CONFIDENCE" in finding["limitations"]


def test_build_finding_clamps_out_of_range_confidence():
    evidence = [make_evidence_item("get_metrics", {}, {"ok": True})]
    finding = build_finding("metrics_agent", evidence, "text\nCONFIDENCE: 1.0")
    assert finding["confidence"] == 1.0


def test_build_finding_notes_empty_evidence():
    finding = build_finding("metrics_agent", [], "No tools were called.\nCONFIDENCE: 0.1")
    assert "no MCP tool evidence" in finding["limitations"]
    assert finding["observation"] == "No MCP tool call succeeded; no evidence was gathered."


def test_build_finding_notes_failed_tool_call():
    evidence = [make_evidence_item("get_trace", {"trace_id": "x"}, {"ok": False, "error": "not found"})]
    finding = build_finding("logs_traces_agent", evidence, "The trace was not found.\nCONFIDENCE: 0.9")
    assert "ok=False" in finding["limitations"]


def test_build_finding_schema_shape():
    evidence = [make_evidence_item("get_database_stats", {}, {"ok": True, "table_row_counts": {}})]
    finding = build_finding("database_agent", evidence, "DB looks fine.\nCONFIDENCE: 0.5")
    required_keys = {
        "finding_id",
        "agent",
        "observation",
        "source",
        "window",
        "evidence",
        "interpretation",
        "confidence",
        "limitations",
    }
    assert required_keys.issubset(finding.keys())
    assert finding["source"] == "database_agent"
    assert set(finding["window"].keys()) == {"start", "end"}


def test_mcp_server_receives_the_settings_it_needs(monkeypatch):
    """The MCP SDK gives the tool server a minimal environment, so required settings are passed explicitly."""
    import mcp_connection
    monkeypatch.setenv("PRODUCTION_BASE_URL", "http://production:8001")
    monkeypatch.delenv("NEXUS_ENABLE_GIT_DIFF", raising=False)
    assert mcp_connection.mcp_server_env() == {"PRODUCTION_BASE_URL": "http://production:8001"}
    params = mcp_connection.mcp_server_connection_params().server_params
    assert params.env == {"PRODUCTION_BASE_URL": "http://production:8001"}


def test_analysis_tools_are_off_by_default_and_assigned_when_enabled(monkeypatch):
    import mcp_connection as mc
    monkeypatch.delenv("NEXUS_ENABLE_ANALYSIS_TOOLS", raising=False)
    assert mc.analysis_tools_for("metrics_agent") == []
    monkeypatch.setenv("NEXUS_ENABLE_ANALYSIS_TOOLS", "1")
    assert mc.analysis_tools_for("metrics_agent") == ["detect_latency_step", "evaluate_expression"]
    assert mc.analysis_tools_for("logs_traces_agent") == ["search_runbook"]
    assert mc.analysis_tools_for("database_agent") == []
    p = mc.analysis_server_connection_params().server_params
    assert p.args[0].endswith("analysis_server.py")


def test_diagnostic_agent_gets_a_second_toolset_only_when_enabled(monkeypatch):
    import diagnostic_agent as da
    agent = da.DiagnosticAgent("metrics_agent", "x", ["get_metrics"])
    monkeypatch.delenv("NEXUS_ENABLE_ANALYSIS_TOOLS", raising=False)
    assert len(agent.build_adk_agent().tools) == 1 and "EXTRA TOOLS" not in agent.build_adk_agent().instruction
    monkeypatch.setenv("NEXUS_ENABLE_ANALYSIS_TOOLS", "1")
    built = agent.build_adk_agent()
    assert len(built.tools) == 2 and "detect_latency_step" in built.instruction
    assert agent._tool_names() == ["get_metrics", "detect_latency_step", "evaluate_expression"]
    assert da.DiagnosticAgent("database_agent", "x", ["get_database_stats"]).build_adk_agent().tools.__len__() == 1
