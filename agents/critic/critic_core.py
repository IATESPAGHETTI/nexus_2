"""Root-Cause Critic logic that needs no agent framework: the instruction, the verdict enum and
`build_critique` (structural enforcement + Pydantic validation). Shared by the ADK Critic
(`agents/critic/agent.py`) and the CrewAI Critic (`crewai_critic/a2a_service.py`), so both obey one contract."""

from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from nexus_models import Critique, validated  # noqa: E402

AGENT_NAME = "root_cause_critic"

VALID_VERDICTS = {
    "SUPPORTED",
    "CONTRADICTED",
    "INSUFFICIENT_EVIDENCE",
    "REQUEST_MORE_EVIDENCE",
    "ABSTAIN",
}

INSTRUCTION = (
    "You are the NEXUS Root-Cause Critic. You will be given a JSON object with "
    "two keys: \"hypothesis\" (a single Hypothesis object under review -- "
    "statement, supporting_evidence_ids, contradicting_evidence_ids, "
    "confidence, missing_evidence) and \"evidence_pool\" (a JSON array of ALL "
    "real evidence items available from every diagnostic agent, each with "
    "evidence_id, tool, arguments, result). Your job is to INDEPENDENTLY "
    "challenge this hypothesis -- do not simply agree with it. Actually "
    "inspect evidence_pool for entries that conflict with the hypothesis' "
    "statement, even ones its own supporting_evidence_ids list ignores. "
    "Identify unsupported assumptions and plausible alternative explanations. "
    "Reply with ONLY a single JSON object (no prose, no markdown fences) with "
    "exactly these keys: \"verdict\" (one of \"SUPPORTED\", \"CONTRADICTED\", "
    "\"INSUFFICIENT_EVIDENCE\", \"REQUEST_MORE_EVIDENCE\", \"ABSTAIN\"), "
    "\"contradictions\" (array of strings, each citing a real evidence_id from "
    "evidence_pool when possible), \"unsupported_assumptions\" (array of "
    "strings), \"alternative_explanations\" (array of strings), "
    "\"requested_evidence\" (array of strings describing what additional "
    "evidence or diagnostic experiment would help, empty if none needed), and "
    "\"rationale\" (a 1-3 sentence explanation of the verdict). Use SUPPORTED "
    "only when evidence_pool genuinely backs the hypothesis with no real "
    "contradiction. Use CONTRADICTED when evidence_pool entries actively "
    "conflict with it. Use INSUFFICIENT_EVIDENCE or REQUEST_MORE_EVIDENCE when "
    "the evidence_pool is too thin either way. Use ABSTAIN only if no "
    "reasonable diagnosis is currently supportable at all. "
    "EVIDENCE LIMITS: the only evidence NEXUS can ever gather is per-endpoint request "
    "metrics, request logs (including the error message of failed requests), request "
    "traces (one record per request, with NO child spans), recent deployment and "
    "configuration change history, and database query statistics. Never ask for anything "
    "outside that list (another service's own health or logs, network captures, source "
    "code, debug logs, profilers): it can never be obtained and would only stall the "
    "investigation. Judge the hypothesis on the evidence_pool. If it explains the "
    "symptoms, several independent sources agree, and NO evidence_pool item contradicts "
    "it, return SUPPORTED even though deeper proof would be nice. Use "
    "REQUEST_MORE_EVIDENCE only for evidence those tools could really return. "
    "TIME MATTERS: read the timestamps in logs and traces. If requests were fast EARLIER and are consistently slow AFTER some point, that is a step change with an onset time, not intermittent or bimodal behaviour; fast requests that happened BEFORE the onset do NOT contradict a claim about the slowness that followed. Only treat a fast response as conflicting evidence if it occurred during the same period as the slow ones. "
)

DEFAULT_QUESTION = json.dumps({"hypothesis": {}, "evidence_pool": []})

DESCRIPTION = (
    "NEXUS Root-Cause Critic: independently challenges the leading Hypothesis "
    "for contradictions, unsupported assumptions, and missing evidence."
)


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def build_critique(hypothesis: dict, evidence_pool: list[dict], raw_model_output) -> dict:
    """Structurally enforces a valid verdict enum and a deterministic critique
    shape. An unparseable or out-of-enum verdict from the model is never
    trusted at face value -- it falls back to INSUFFICIENT_EVIDENCE, which
    keeps the re-evaluation loop asking for more evidence rather than silently
    treating a garbled reply as support or contradiction.
    """
    if not isinstance(raw_model_output, dict):
        raw_model_output = {}

    verdict = raw_model_output.get("verdict")
    verdict_was_valid = verdict in VALID_VERDICTS
    if not verdict_was_valid:
        verdict = "INSUFFICIENT_EVIDENCE"

    def _string_list(key: str) -> list[str]:
        value = raw_model_output.get(key)
        return [str(v) for v in value] if isinstance(value, list) else []

    rationale = raw_model_output.get("rationale")
    if not verdict_was_valid:
        rationale = (
            "critic did not return a recognized verdict; defaulted to "
            "INSUFFICIENT_EVIDENCE rather than trust an unparseable judgement"
        )

    critique = {
        "critique_id": f"crit-{uuid.uuid4().hex[:8]}",
        "hypothesis_id": hypothesis.get("hypothesis_id") if isinstance(hypothesis, dict) else None,
        "verdict": verdict,
        "contradictions": _string_list("contradictions"),
        "unsupported_assumptions": _string_list("unsupported_assumptions"),
        "alternative_explanations": _string_list("alternative_explanations"),
        "requested_evidence": _string_list("requested_evidence"),
        "rationale": str(rationale) if rationale else "(no rationale provided)",
        "evidence_pool_size": len(evidence_pool) if isinstance(evidence_pool, list) else 0,
        "timestamp": now_iso(),
    }
    return validated(Critique, critique)
