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

AGENT_NAME = "evidence_agent"

# Closed catalog of fault classes the system knows about (same list the single-agent
# baseline answers from; it is a vocabulary, not a ground truth). "none" = the
# evidence does not support any of them.
FAULT_CLASSES = ("bad_deployment", "db_slowdown", "config_error", "dependency_failure", "resource_exhaustion")

INSTRUCTION = (
    "You are the NEXUS Evidence Agent. You will be given a JSON object mapping "
    "diagnostic agent names to their structured Finding objects. Each Finding "
    "has real evidence gathered from MCP tools: a list under \"evidence\", each "
    "item with an \"evidence_id\", \"tool\", \"arguments\", and \"result\". "
    "Synthesize these findings into a JSON array of hypotheses about the "
    "incident's root cause. Each hypothesis object MUST have exactly these "
    "keys: \"statement\" (string), \"supporting_evidence_ids\" (array of "
    "evidence_id strings copied EXACTLY, character-for-character, from the "
    "input evidence -- never invent an evidence_id), \"contradicting_evidence_ids\" "
    "(array, same rule), \"confidence\" (a number between 0 and 1), "
    "\"missing_evidence\" (array of strings describing what evidence would "
    "strengthen or refute this hypothesis), and \"requested_next_investigation\" "
    "(a short string naming what to investigate next, or null), and "
    "\"fault_class\" (EXACTLY one of: bad_deployment, db_slowdown, "
    "config_error, dependency_failure, resource_exhaustion, or none if the "
    "evidence supports none of them -- the class your statement asserts is the "
    "cause, never a class your statement rules out). Reply with "
    "ONLY the JSON array -- no prose, no markdown code fences. Propose 1 to 3 "
    "hypotheses, most plausible first. If the findings do not support any "
    "specific root cause, reply with an empty JSON array []. "
    "TIME MATTERS: read the timestamps in logs and traces. If requests were fast EARLIER and are consistently slow AFTER some point, that is a step change with an onset time, not intermittent or bimodal behaviour; fast requests that happened BEFORE the onset do NOT contradict a claim about the slowness that followed. Only treat a fast response as conflicting evidence if it occurred during the same period as the slow ones. "
)

DEFAULT_QUESTION = "{}"

DESCRIPTION = (
    "NEXUS Evidence Agent: synthesizes the 4 diagnostic agents' structured "
    "Findings into explicit, evidence-referenced Hypotheses."
)


def _valid_evidence_ids(findings_by_agent: dict) -> set[str]:
    ids: set[str] = set()
    if not isinstance(findings_by_agent, dict):
        return ids
    for finding in findings_by_agent.values():
        if not isinstance(finding, dict):
            continue
        for item in finding.get("evidence", []) or []:
            eid = item.get("evidence_id") if isinstance(item, dict) else None
            if eid:
                ids.add(eid)
    return ids


def build_hypotheses(findings_by_agent: dict, raw_model_output) -> list[dict]:
    """Structurally enforces the Hypothesis schema (docs/API_CONTRACT.md) and
    the evidence-first rule. `hypothesis_id` is always assigned here (never
    trusted from the model); supporting/contradicting evidence_ids are
    filtered down to ids that actually exist in the real findings.
    """
    valid_ids = _valid_evidence_ids(findings_by_agent)
    hypotheses: list[dict] = []
    if not isinstance(raw_model_output, list):
        return hypotheses

    for i, item in enumerate(raw_model_output, start=1):
        if not isinstance(item, dict) or not item.get("statement"):
            continue

        claimed_support = item.get("supporting_evidence_ids") or []
        claimed_contra = item.get("contradicting_evidence_ids") or []
        if not isinstance(claimed_support, list):
            claimed_support = []
        if not isinstance(claimed_contra, list):
            claimed_contra = []
        supporting = [e for e in claimed_support if e in valid_ids]
        contradicting = [e for e in claimed_contra if e in valid_ids]
        dropped = (len(claimed_support) - len(supporting)) + (len(claimed_contra) - len(contradicting))

        try:
            confidence = max(0.0, min(1.0, float(item.get("confidence", 0.3))))
        except (TypeError, ValueError):
            confidence = 0.3

        missing = item.get("missing_evidence")
        missing = list(missing) if isinstance(missing, list) else []
        if not supporting and not contradicting:
            missing = missing + [
                "no real evidence_id from the diagnostic findings was matched to this hypothesis"
            ]

        requested_next = item.get("requested_next_investigation")
        fault_class = item.get("fault_class")
        if fault_class not in FAULT_CLASSES:
            fault_class = "none"  # unrecognised or missing -> asserts no known class

        hypotheses.append(
            {
                "hypothesis_id": f"H{i}",
                "statement": str(item["statement"]),
                "supporting_evidence_ids": supporting,
                "contradicting_evidence_ids": contradicting,
                "confidence": confidence,
                "missing_evidence": missing,
                "requested_next_investigation": str(requested_next) if requested_next else None,
                "fault_class": fault_class,
                "status": "PROPOSED",
                "revision": 1,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "dropped_invented_evidence_ids": dropped,
            }
        )

    hypotheses.sort(key=lambda h: h["confidence"], reverse=True)
    return hypotheses


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
        hypotheses = build_hypotheses(findings_by_agent, raw.get("parsed"))
        return {"hypotheses": hypotheses, "usage": raw.get("usage")}


evidence_agent = EvidenceAgent()


async def synthesize(findings_by_agent: dict) -> list[dict]:
    """Direct in-process helper -- used only by this package's own unit tests
    and by the A2A server that hosts this exact object. Never imported by
    orchestrator/ (which must reach this agent only over real A2A)."""
    result = await evidence_agent.investigate(json.dumps(findings_by_agent))
    return result["hypotheses"]
