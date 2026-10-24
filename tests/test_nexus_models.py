"""Pydantic contracts (nexus_models.py): validation, rejection of bad data, report building."""
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nexus_models import Critique, Hypothesis, RecoveryPlan, build_incident_report, validated  # noqa: E402

HYP = {"hypothesis_id": "H1", "statement": "DB slow", "supporting_evidence_ids": ["ev-1"],
       "confidence": 0.8, "created_at": "2026-01-01T00:00:00Z", "previous_confidence": 0.5}


def test_hypothesis_keeps_extra_fields_and_defaults():
    out = validated(Hypothesis, HYP)
    assert out["previous_confidence"] == 0.5 and out["status"] == "PROPOSED" and out["revision"] == 1


@pytest.mark.parametrize("bad", [{"confidence": 1.5}, {"statement": ""}, {"status": "MADE_UP"}])
def test_hypothesis_rejects_bad_values(bad):
    with pytest.raises(ValidationError):
        validated(Hypothesis, {**HYP, **bad})


def test_critique_rejects_unknown_verdict():
    with pytest.raises(ValidationError):
        validated(Critique, {"critique_id": "c", "verdict": "MAYBE", "rationale": "x", "timestamp": "t"})


def test_recovery_plan_rejects_bad_risk():
    with pytest.raises(ValidationError):
        validated(RecoveryPlan, {"plan_id": "p", "risk_level": "EXTREME", "blast_radius": "b",
                                 "rollback_plan": "r", "created_at": "t"})


def _incident(**over):
    inc = {
        "incident_id": "INC-1", "description": "slow checkout", "status": "DIAGNOSED",
        "decision": {"outcome": "DIAGNOSED", "reason": "H1 SUPPORTED", "loops_used": 2},
        "hypotheses": [{**HYP, "status": "SUPPORTED"}, {**HYP, "hypothesis_id": "H2", "statement": "bad deploy", "status": "REJECTED"}],
        "critic_results": [{"verdict": "SUPPORTED", "rationale": "consistent"}],
        "agent_findings": {"database_agent": {"evidence": [{"evidence_id": "ev-1", "tool": "get_database_stats"}]}},
        "recovery_plan": {"actions": [{"action": "scale_resources"}]},
        "approval_state": {"decision": "APPROVED"},
        "token_usage": {"total": {"llm_calls": 22, "total_tokens": 81486}},
    }
    inc.update(over)
    return inc


def test_report_from_diagnosed_incident():
    r = build_incident_report(_incident())
    assert r.root_cause == "DB slow" and r.supporting_evidence[0].tool == "get_database_stats"
    assert r.supporting_evidence[0].agent == "database_agent"
    assert r.rejected_hypotheses == ["bad deploy"] and r.recovery_actions == ["scale_resources"]
    assert r.total_tokens == 81486 and r.llm_calls == 22
    md = r.to_markdown()
    assert "# Incident report INC-1" in md and "| ev-1 | get_database_stats | database_agent |" in md


def test_report_for_abstained_incident_says_so():
    r = build_incident_report(_incident(status="ABSTAINED", hypotheses=[], critic_results=[], recovery_plan=None,
                                        approval_state=None, token_usage={}))
    assert r.root_cause is None
    md = r.to_markdown()
    assert "abstained" in md and "No recovery plan" in md and "not recorded" in md


def test_report_has_summary_hypotheses_and_agents_tables():
    inc = _incident(created_at="2026-10-18T10:00:00Z", updated_at="2026-10-18T10:00:20Z", trace_id="t" * 32,
                    token_usage={"total": {"llm_calls": 9, "total_tokens": 100},
                                 "by_agent": {"database_agent": {"llm_calls": 2, "total_tokens": 40}}},
                    run_config={"topology": "blackboard", "prompt_variant": "react", "critic_framework": "crewai"})
    r = build_incident_report(inc)
    md = r.to_markdown()
    assert "## Summary" in md and "| Field | Value |" in md and "| Duration | 20.0 s |" in md
    assert "| Topology / prompt / critic | blackboard / react / crewai |" in md
    assert "## Hypotheses" in md and "| H1 | SUPPORTED | 80% |" in md and "| H2 | REJECTED |" in md
    assert "## Agents" in md and "| database_agent | 2 | 1 | 40 |" in md
    assert r.trace_id == "t" * 32 and r.summary_rows[0] == ["Incident", "INC-1"]


def test_table_cells_cannot_break_the_markdown_table():
    from nexus_models import _md_cell
    assert "|" not in _md_cell("a | b\nc") and "\n" not in _md_cell("a | b\nc")
    assert len(_md_cell("x" * 500)) <= 160


def test_abstained_report_still_renders_a_summary_table():
    r = build_incident_report(_incident(status="ABSTAINED", hypotheses=[], critic_results=[], recovery_plan=None,
                                        approval_state=None, token_usage={}))
    md = r.to_markdown()
    assert "| Root cause | none supported (abstained) |" in md and "| Recovery | none proposed |" in md
