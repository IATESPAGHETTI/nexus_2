"""Evidence Agent (Phase 6).

Receives the structured Findings the 4 diagnostic agents already produced
(each with real MCP evidence) and synthesizes them into explicit Hypotheses
(docs/API_CONTRACT.md "Hypothesis schema"). Reached only over real A2A in
production use (agents/evidence/a2a_service.py); orchestrator/investigation.py
never imports this module directly.

The observation/interpretation split principle from agents/common/finding.py
carries over here as an evidence/hypothesis split: `build_hypotheses` is pure
Python and is the only thing allowed to assign a hypothesis_id or decide which
evidence_ids are real. The model's job is only to propose which existing
evidence_ids support or contradict which statement -- an id it invents that
does not exist in the input findings is dropped, never recorded as fact.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))

from reasoning_agent import ReasoningAgent  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evidence_core import (  # noqa: E402,F401  (re-exported for existing tests/imports)
    AGENT_NAME,
    DEFAULT_QUESTION,
    DESCRIPTION,
    INSTRUCTION,
    _as_hypothesis_list,
    _valid_evidence_ids,
    build_hypotheses,
    hypotheses_reply,
)


class EvidenceAgent:
    """Duck-typed like `DiagnosticAgent` (`build_adk_agent`, `default_question`,
    async `investigate`) so `agents/common/a2a_server.py` serves it unmodified.
    """

    agent_name = AGENT_NAME
    default_question = DEFAULT_QUESTION

    def __init__(self) -> None:
        self._reasoner = ReasoningAgent(
            agent_name=AGENT_NAME,
            instruction=INSTRUCTION,
            default_question=DEFAULT_QUESTION,
            description=DESCRIPTION,
        )

    def build_adk_agent(self):
        return self._reasoner.build_adk_agent()

    async def investigate(self, question: str) -> dict:
        try:
            findings_by_agent = json.loads(question)
        except json.JSONDecodeError:
            findings_by_agent = {}
        if not isinstance(findings_by_agent, dict):
            findings_by_agent = {}

        raw = await self._reasoner.investigate(question)
        result = hypotheses_reply(findings_by_agent, raw.get("parsed"), raw.get("raw_text") or "")
        result["usage"] = raw.get("usage")
        result["monitoring"] = raw.get("monitoring")
        return result


evidence_agent = EvidenceAgent()


async def synthesize(findings_by_agent: dict) -> list[dict]:
    """Direct in-process helper -- used only by this package's own unit tests
    and by the A2A server that hosts this exact object. Never imported by
    orchestrator/ (which must reach this agent only over real A2A)."""
    result = await evidence_agent.investigate(json.dumps(findings_by_agent))
    return result["hypotheses"]
