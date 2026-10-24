"""Root-Cause Critic implemented with CrewAI (Agent + Task + Crew), served over real A2A (course requirements 6 and 7).

    .venv-crewai/Scripts/python crewai_critic/a2a_service.py

Same contract as the ADK Critic (`agents/critic/critic_core.py`: same instruction, verdict enum and `build_critique` +
Pydantic validation) and the SAME A2A address (`root_cause_critic`, port 8106), so the orchestrator cannot tell which
framework answered, except for the `framework` field on the critique. Shared plumbing (LLM selection, Crew run with
step/task callbacks, real token usage, A2A server) lives in `crewai_common.py`.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import crewai_common as cc  # noqa: E402  (also sets up sys.path for the repo root and agents/common)

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "agents" / "critic"))

import uvicorn  # noqa: E402
from callbacks import AgentMonitor  # noqa: E402
from critic_core import AGENT_NAME, DESCRIPTION, INSTRUCTION, build_critique  # noqa: E402
from json_extract import extract_json  # noqa: E402
from nexus_guard import redact_text  # noqa: E402
from prompt_variants import apply_variant  # noqa: E402

PORT = int(os.environ.get("CRITIC_PORT", "8106"))


def critique_for(question: str) -> dict:
    """Pure function used by the A2A executor and by tests."""
    monitor = AgentMonitor(AGENT_NAME)
    if os.environ.get("NEXUS_GUARDRAILS", "1") != "0":
        question, guard_flags = redact_text(question)  # same layer as the ADK agents' tool-output guard
        if guard_flags:
            monitor._add("input_redacted", flags=guard_flags)
    try:
        payload = json.loads(question)
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    hypothesis = payload.get("hypothesis") or {}
    evidence_pool = payload.get("evidence_pool") or []

    if cc.stub_mode():
        raw_text = json.dumps({"verdict": "INSUFFICIENT_EVIDENCE", "rationale": "stub mode (no model call)"})
        usage = {"llm_calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    else:
        raw_text, usage = cc.run_crew(
            role="NEXUS Root-Cause Critic",
            goal="Independently challenge the hypothesis under review using only the evidence given.",
            backstory=apply_variant(INSTRUCTION, AGENT_NAME),
            description="Review this input and reply with the single JSON object described in your instructions.\n\nINPUT:\n" + question,
            expected_output="A single JSON object with keys verdict, contradictions, unsupported_assumptions, alternative_explanations, requested_evidence, rationale",
            monitor=monitor,
        )
    monitor.after_agent(None)

    critique = build_critique(hypothesis, evidence_pool, extract_json(raw_text))
    critique["framework"] = "crewai"
    critique["usage"] = usage
    critique["monitoring"] = monitor.summary()
    return critique


app = cc.build_a2a_app(
    name=AGENT_NAME, description=DESCRIPTION, port=PORT, skill_id="critique_hypothesis",
    skill_description="Challenge a hypothesis against an evidence pool", tags=["critic"],
    executor=cc.CrewAIExecutor(critique_for, AGENT_NAME),
)

if __name__ == "__main__":
    uvicorn.run(app, host=cc.HOST, port=PORT, log_level="warning")
