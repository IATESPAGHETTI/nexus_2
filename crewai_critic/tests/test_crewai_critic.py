"""Run with .venv-crewai. Stub mode: no model call, no tokens."""
import json
import pytest
import os
import sys
from pathlib import Path

os.environ["CRITIC_STUB"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import a2a_service  # noqa: E402


def test_critique_follows_the_shared_contract():
    out = a2a_service.critique_for(json.dumps({"hypothesis": {"hypothesis_id": "H1"}, "evidence_pool": [{"evidence_id": "e"}]}))
    assert out["framework"] == "crewai"
    assert out["hypothesis_id"] == "H1" and out["verdict"] == "INSUFFICIENT_EVIDENCE"
    assert out["evidence_pool_size"] == 1 and out["critique_id"].startswith("crit-")
    assert out["usage"]["llm_calls"] == 0
    assert out["monitoring"]["agent"] == "root_cause_critic"


def test_garbage_input_still_yields_valid_critique():
    out = a2a_service.critique_for("not json at all")
    assert out["verdict"] == "INSUFFICIENT_EVIDENCE" and out["hypothesis_id"] is None


def test_unknown_verdict_from_model_is_normalised():
    from critic_core import build_critique
    out = build_critique({"hypothesis_id": "H1"}, [], {"verdict": "DEFINITELY", "rationale": "x"})
    assert out["verdict"] == "INSUFFICIENT_EVIDENCE"


def test_evidence_service_follows_the_shared_contract_in_stub_mode():
    import evidence_service
    findings = {"metrics_agent": {"finding_id": "f1", "evidence": [{"evidence_id": "ev-1"}]}}
    out = evidence_service.hypotheses_for(json.dumps(findings))
    assert out["framework"] == "crewai" and out["usage"]["llm_calls"] == 0
    h = out["hypotheses"][0]
    assert h["hypothesis_id"] == "H1" and h["status"] == "PROPOSED" and 0 <= h["confidence"] <= 1   # ids/status assigned in code
    assert h["framework"] == "crewai"
    assert out["monitoring"]["agent"] == "evidence_agent"


def test_evidence_ids_the_model_invents_are_dropped_by_the_shared_core(monkeypatch):
    import evidence_service
    monkeypatch.setattr(evidence_service.cc, "stub_mode", lambda: False)
    monkeypatch.setattr(evidence_service.cc, "run_crew", lambda **kw: (
        json.dumps({"hypotheses": [{"statement": "slow db", "confidence": 0.9, "supporting_evidence_ids": ["ev-1", "ev-invented"]}]}),
        {"llm_calls": 1, "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}))
    out = evidence_service.hypotheses_for(json.dumps({"a": {"finding_id": "f", "evidence": [{"evidence_id": "ev-1"}]}}))
    assert out["hypotheses"][0]["supporting_evidence_ids"] == ["ev-1"] and out["hypotheses"][0]["dropped_invented_evidence_ids"] == 1
    assert out["usage"]["total_tokens"] == 15          # usage from the (mocked) Crew run reaches the reply


def test_crewai_callbacks_record_into_the_shared_monitor():
    from callbacks import AgentMonitor
    m = AgentMonitor("evidence_agent", echo=False)

    class AgentAction:
        tool = "get_metrics"

    class AgentFinish:
        pass

    class Output:
        raw = "x" * 40

    m.crewai_step(AgentAction())
    m.crewai_step(AgentFinish())
    m.crewai_task(Output())
    kinds = [(r["kind"], r.get("step_type"), r.get("tool"), r.get("output_chars")) for r in m.records]
    assert kinds == [("crewai_step", "AgentAction", "get_metrics", None), ("crewai_step", "AgentFinish", None, None),
                     ("crewai_task_finished", None, None, 40)]


def test_provider_llm_uses_the_selected_provider_and_refuses_a_missing_key(monkeypatch):
    import crewai_common as cc
    monkeypatch.setenv("NEXUS_LLM_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        cc.provider_llm()


def test_usage_from_crew_reads_measured_numbers():
    import crewai_common as cc

    class M:
        successful_requests, prompt_tokens, completion_tokens, total_tokens = 2, 70, 12, 82

    class Out:
        token_usage = M()

    assert cc.usage_from_crew(Out()) == {"llm_calls": 2, "prompt_tokens": 70, "completion_tokens": 12, "total_tokens": 82}
    assert cc.usage_from_crew(object())["total_tokens"] == 0
