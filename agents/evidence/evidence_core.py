"""Evidence Agent logic that needs no agent framework: the instruction, `build_hypotheses` (structural enforcement +
Pydantic validation) and `hypotheses_reply`. Shared by the ADK Evidence Agent (`agents/evidence/agent.py`) and the CrewAI
one (`crewai_critic/evidence_service.py`), so both obey one contract."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from nexus_models import Hypothesis, validated  # noqa: E402

AGENT_NAME = "evidence_agent"

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
    "(a short string naming what to investigate next, or null). Reply with "
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


def _as_hypothesis_list(raw):
    """The prompt asks for a JSON array, but models sometimes wrap it ({"hypotheses": [...]}) or return one bare
    object. Accept those shapes; anything else is "no usable output" (None), never a guess."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ("hypotheses", "Hypotheses", "results", "items"):
            if isinstance(raw.get(key), list):
                return raw[key]
        if raw.get("statement"):
            return [raw]
    return None


def build_hypotheses(findings_by_agent: dict, raw_model_output) -> list[dict]:
    """Structurally enforces the Hypothesis schema (docs/API_CONTRACT.md) and
    the evidence-first rule. `hypothesis_id` is always assigned here (never
    trusted from the model); supporting/contradicting evidence_ids are
    filtered down to ids that actually exist in the real findings.
    """
    valid_ids = _valid_evidence_ids(findings_by_agent)
    hypotheses: list[dict] = []
    raw_model_output = _as_hypothesis_list(raw_model_output)
    if raw_model_output is None:
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

        hypotheses.append(
            {
                "hypothesis_id": f"H{i}",
                "statement": str(item["statement"]),
                "supporting_evidence_ids": supporting,
                "contradicting_evidence_ids": contradicting,
                "confidence": confidence,
                "missing_evidence": missing,
                "requested_next_investigation": str(requested_next) if requested_next else None,
                "status": "PROPOSED",
                "revision": 1,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "dropped_invented_evidence_ids": dropped,
            }
        )

    hypotheses.sort(key=lambda h: h["confidence"], reverse=True)
    return [validated(Hypothesis, h) for h in hypotheses]


def hypotheses_reply(findings_by_agent: dict, parsed, raw_text: str) -> dict:
    """Shared tail of both implementations: validated hypotheses, plus a warning when the model clearly answered but
    nothing parsed (so that does not look like "nothing to report")."""
    hypotheses = build_hypotheses(findings_by_agent, parsed)
    reply: dict = {"hypotheses": hypotheses}
    text = raw_text or ""
    if not hypotheses and len(text.strip()) > 20 and _as_hypothesis_list(parsed) is None:
        reply["parse_warning"] = "model reply could not be parsed into hypotheses: " + text.strip()[:200]
    return reply
