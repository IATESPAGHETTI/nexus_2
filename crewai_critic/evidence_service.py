"""Evidence Agent implemented with CrewAI (Agent + Task + Crew), served over real A2A (course requirements 6 and 7).

    .venv-crewai/Scripts/python crewai_critic/evidence_service.py

Same contract and A2A address as the ADK Evidence Agent (`evidence_agent`, port 8105): the instruction,
`build_hypotheses` (ids assigned in code, invented evidence ids dropped) and Pydantic validation live in the
framework-free `agents/evidence/evidence_core.py`. Select it with NEXUS_EVIDENCE_FRAMEWORK=crewai.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import crewai_common as cc  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "agents" / "evidence"))

import uvicorn  # noqa: E402
from callbacks import AgentMonitor  # noqa: E402
from evidence_core import AGENT_NAME, DESCRIPTION, INSTRUCTION, hypotheses_reply  # noqa: E402
from json_extract import extract_json  # noqa: E402
from nexus_guard import redact_text  # noqa: E402
from prompt_variants import apply_variant  # noqa: E402

PORT = int(os.environ.get("EVIDENCE_PORT", "8105"))


def hypotheses_for(question: str) -> dict:
    """Pure function used by the A2A executor and by tests."""
    monitor = AgentMonitor(AGENT_NAME)
    if os.environ.get("NEXUS_GUARDRAILS", "1") != "0":
        question, guard_flags = redact_text(question)
        if guard_flags:
            monitor._add("input_redacted", flags=guard_flags)
    try:
        findings = json.loads(question)
    except json.JSONDecodeError:
        findings = {}
    if not isinstance(findings, dict):
        findings = {}

    if cc.stub_mode():
        raw_text = json.dumps([{"statement": "stub hypothesis (no model call)", "confidence": 0.1, "supporting_evidence_ids": []}])
        usage = {"llm_calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    else:
        raw_text, usage = cc.run_crew(
            role="NEXUS Evidence Agent",
            goal="Turn the diagnostic findings into explicit, evidence-backed hypotheses.",
            backstory=apply_variant(INSTRUCTION, AGENT_NAME),
            description="Read these findings and reply with the JSON array of hypotheses described in your instructions.\n\nFINDINGS:\n" + question,
            expected_output="A JSON array of hypothesis objects",
            monitor=monitor,
        )
    monitor.after_agent(None)

    reply = hypotheses_reply(findings, extract_json(raw_text), raw_text)
    reply["framework"] = "crewai"
    for h in reply["hypotheses"]:
        h["framework"] = "crewai"   # provenance: which framework produced this hypothesis
    reply["usage"] = usage
    reply["monitoring"] = monitor.summary()
    return reply


app = cc.build_a2a_app(
    name=AGENT_NAME, description=DESCRIPTION, port=PORT, skill_id="synthesize_hypotheses",
    skill_description="Synthesize diagnostic findings into hypotheses", tags=["evidence"],
    executor=cc.CrewAIExecutor(hypotheses_for, AGENT_NAME),
)

if __name__ == "__main__":
    uvicorn.run(app, host=cc.HOST, port=PORT, log_level="warning")
