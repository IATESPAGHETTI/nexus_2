"""Prompt variants for experiments (course requirements 8 and 10). ADK-free, so ADK and CrewAI agents share it.

NEXUS_PROMPT_VARIANT selects how every agent is prompted; the OUTPUT CONTRACT never changes (the parsers and
Pydantic models are the same), only the way the model is steered:

  default         the prompts as shipped
  react           architecture change: explicit Reason -> Act -> Observe discipline (state what a step should reveal,
                  act, compare the observation with the expectation); a short stated rationale, not a free-form dump
  fewshot         architecture change: compact worked examples of the output format and of good/bad judgement
  persona_sre     content change: a senior on-call SRE persona (symptom first, recent change, onset time)
  persona_auditor content change: a sceptical incident-review auditor persona (every claim needs evidence)

The examples are about FORMAT and reasoning habits; they never name a scenario's cause, so they cannot leak a
ground truth into the blind benchmark. Unknown names fall back to `default` and are reported.
"""

from __future__ import annotations

import os

VARIANTS = ("default", "react", "fewshot", "persona_sre", "persona_auditor")

_REACT = (
    "\n\nWORKING STYLE (ReAct): proceed in explicit steps. THINK: in one sentence say what you expect the next "
    "step to reveal and why. ACT: do exactly that step (a tool call, or one judgement). OBSERVE: compare what came "
    "back with the expectation and note any surprise. Repeat only while a step can still change your answer, then "
    "give the final reply in EXACTLY the required format. Keep each THINK/OBSERVE to one sentence."
)

_FEWSHOT = {
    "diagnostic": (
        "\n\nEXAMPLES of the expected style (the numbers are made up for illustration only).\n"
        "Good: 'p99 for GET /x is 480 ms against 12 ms earlier in the window; error rate is 0%. The step change "
        "starts at 10:42.' CONFIDENCE: 0.7\n"
        "Bad: 'The database is probably overloaded.' (a cause stated without any observation)\n"
        "Always quote the numbers or error text your tool returned and say when the change started."
    ),
    "evidence": (
        "\n\nEXAMPLE (illustrative; ids and wording are made up). A good hypothesis cites real evidence ids from the "
        "findings and lists what is still missing:\n"
        '[{"statement": "Requests slowed at 10:42 and the slowness comes from the data layer, not the app",'
        ' "supporting_evidence_ids": ["ev-aaaa1111", "ev-bbbb2222"], "contradicting_evidence_ids": [],'
        ' "confidence": 0.7, "missing_evidence": ["what changed at 10:42"], "requested_next_investigation": null}]\n'
        "Never cite an evidence id that is not in the findings."
    ),
    "critic": (
        "\n\nEXAMPLES (illustrative). SUPPORTED: 'metrics and the database statistics agree on a step change at the "
        "same time and no item contradicts it'. REQUEST_MORE_EVIDENCE: 'the claim names a deployment but no change "
        "history item was gathered'. CONTRADICTED: 'ev-x shows the same latency before the claimed onset'. Always cite "
        "evidence ids in contradictions."
    ),
    "recovery": (
        "\n\nEXAMPLE (illustrative): one action that matches the diagnosed symptom, a stated blast radius, and a "
        "rollback plan; never more actions than needed."
    ),
}

_PERSONA = {
    "persona_sre": (
        "\n\nPERSONA: you are a senior on-call site-reliability engineer with 15 years of production experience. "
        "You check the customer-visible symptom first, then what changed recently, then WHEN it started. You prefer "
        "the simplest explanation that fits all the evidence."
    ),
    "persona_auditor": (
        "\n\nPERSONA: you are a sceptical incident-review auditor. You accept nothing without evidence, you look for "
        "the observation that would prove the leading idea wrong, and you say plainly when evidence is thin."
    ),
}


def current_variant() -> tuple[str, bool]:
    """(effective variant, was_unknown). Unknown names fall back to default."""
    name = os.environ.get("NEXUS_PROMPT_VARIANT", "default").strip().lower() or "default"
    if name in VARIANTS:
        return name, False
    return "default", True


def agent_kind(agent_name: str) -> str:
    name = agent_name.lower()
    if "evidence" in name:
        return "evidence"
    if "critic" in name:
        return "critic"
    if "recovery" in name:
        return "recovery"
    return "diagnostic"


def apply_variant(instruction: str, agent_name: str) -> str:
    variant, _ = current_variant()
    if variant == "react":
        return instruction + _REACT
    if variant == "fewshot":
        return instruction + _FEWSHOT[agent_kind(agent_name)]
    if variant in _PERSONA:
        return instruction + _PERSONA[variant]
    return instruction
