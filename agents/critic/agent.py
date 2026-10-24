"""Root-Cause Critic (Phase 6).

Independently challenges a single leading Hypothesis (root CLAUDE.md section
13) rather than agreeing with the Evidence Agent by default: inspects the full
evidence pool for contradictions, unsupported assumptions, and alternative
explanations, and can request more evidence or abstain. Reached only over real
A2A in production use (agents/critic/a2a_service.py); orchestrator/investigation.py
never imports this module directly.
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from reasoning_agent import ReasoningAgent  # noqa: E402


from critic_core import (  # noqa: E402,F401  (re-exported for existing tests/imports)
    AGENT_NAME,
    DEFAULT_QUESTION,
    DESCRIPTION,
    INSTRUCTION,
    VALID_VERDICTS,
    build_critique,
    now_iso,
)


class CriticAgent:
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
            payload = json.loads(question)
        except json.JSONDecodeError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        hypothesis = payload.get("hypothesis") or {}
        evidence_pool = payload.get("evidence_pool") or []

        raw = await self._reasoner.investigate(question)
        critique = build_critique(hypothesis, evidence_pool, raw.get("parsed"))
        # Real model usage; the orchestrator pops it before storing the critique.
        critique["usage"] = raw.get("usage")
        critique["monitoring"] = raw.get("monitoring")
        return critique


critic_agent = CriticAgent()


async def challenge(hypothesis: dict, evidence_pool: list[dict]) -> dict:
    """Direct in-process helper -- used only by this package's own unit tests
    and by the A2A server that hosts this exact object. Never imported by
    orchestrator/ (which must reach this agent only over real A2A)."""
    question = json.dumps({"hypothesis": hypothesis, "evidence_pool": evidence_pool})
    return await critic_agent.investigate(question)
