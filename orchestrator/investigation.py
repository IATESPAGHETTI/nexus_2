"""Phase 6: bounded evidence -> hypothesis -> critic re-evaluation loop.

```
Incident description
   |
Incident Manager dispatch (Phase 5 incident_manager.investigate_incident,
   real A2A fan-out to the 4 diagnostic agents)
   |
Findings (real Finding objects, each with real MCP evidence)
   |
Evidence Agent (real A2A call -- agents/evidence/a2a_service.py) -> Hypotheses
   |
Root-Cause Critic (real A2A call -- agents/critic/a2a_service.py), bounded loop
(MAX_REEVALUATION_LOOPS iterations, never infinite -- root CLAUDE.md section 14):
   SUPPORTED                                  -> diagnosis reached, stop
   CONTRADICTED                               -> reject hypothesis, try the next one
   INSUFFICIENT_EVIDENCE / REQUEST_MORE_EVIDENCE
                                               -> real second-round A2A dispatch to
                                                  the diagnostic agents for more
                                                  evidence, hypotheses regenerated,
                                                  loop continues (if budget remains)
   ABSTAIN                                    -> abstain, stop
   loop exhausted without SUPPORTED/ABSTAIN   -> abstain (never force a diagnosis)
```

Every transition is persisted to the backend event store and running incident
state via `orchestrator/event_bridge.py` (real HTTP calls to `backend/`).
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import event_bridge  # noqa: E402
import recovery  # noqa: E402
from budget import IncidentBudget  # noqa: E402
from incident_manager import DIAGNOSTIC_AGENTS, investigate_incident  # noqa: E402
import triage  # noqa: E402
from remote_call import call_remote_agent  # noqa: E402

MAX_REEVALUATION_LOOPS = int(os.environ.get("MAX_REEVALUATION_LOOPS", "3"))

EVIDENCE_AGENT_NAME = "evidence_agent"
EVIDENCE_AGENT_DESCRIPTION = "NEXUS Evidence Agent: synthesizes diagnostic Findings into Hypotheses."
CRITIC_AGENT_NAME = "root_cause_critic"
CRITIC_AGENT_DESCRIPTION = "NEXUS Root-Cause Critic: independently challenges the leading Hypothesis."

_OPEN_STATUSES = ("PROPOSED", "UNDER_REVIEW", "NEEDS_EVIDENCE")


def _flatten_evidence(findings_by_agent: dict) -> list[dict]:
    pool: list[dict] = []
    for finding in findings_by_agent.values():
        pool.extend(finding.get("evidence", []) or [])
    return pool


def _leading_hypothesis(hypotheses: list[dict]) -> dict | None:
    open_ones = [h for h in hypotheses if h.get("status") in _OPEN_STATUSES]
    if not open_ones:
        return None
    return max(open_ones, key=lambda h: h.get("confidence", 0.0))


_SAME_THEORY_OVERLAP = 0.5
_WORD_RE = re.compile(r"[a-z0-9_]{3,}")


def _words(statement: str | None) -> set[str]:
    return set(_WORD_RE.findall((statement or "").lower()))


def reconcile_hypotheses(previous: list[dict], new: list[dict]) -> list[dict]:
    """Gives a re-proposed theory the SAME id across rounds (root CLAUDE.md section 12:
    revision history). The Evidence Agent renumbers H1, H2... on every call, so without
    this a hypothesis_id is not a stable identity. Pure code, no model: a new hypothesis
    inherits the id of the previous one whose statement shares at least half its words
    (best matches first, one-to-one); it then records `revision` (previous + 1) and
    `previous_confidence`. Unmatched hypotheses get a fresh id that collides with none.
    Mutates and returns `new`."""
    if not previous:
        return new
    candidates = []
    for i, n in enumerate(new):
        nw = _words(n.get("statement"))
        for j, p in enumerate(previous):
            pw = _words(p.get("statement"))
            if nw and pw:
                overlap = len(nw & pw) / len(nw | pw)
                if overlap >= _SAME_THEORY_OVERLAP:
                    candidates.append((overlap, i, j))
    used_new: set[int] = set()
    used_prev: set[int] = set()
    for _, i, j in sorted(candidates, key=lambda c: -c[0]):
        if i in used_new or j in used_prev:
            continue
        used_new.add(i)
        used_prev.add(j)
        new[i]["hypothesis_id"] = previous[j].get("hypothesis_id")
        new[i]["revision"] = int(previous[j].get("revision", 1)) + 1
        new[i]["previous_confidence"] = previous[j].get("confidence")
    taken = {h.get("hypothesis_id") for h in previous} | {new[i].get("hypothesis_id") for i in used_new}
    counter = 1
    for i, n in enumerate(new):
        if i in used_new:
            continue
        while f"H{counter}" in taken:
            counter += 1
        n["hypothesis_id"] = f"H{counter}"
        taken.add(n["hypothesis_id"])
    return new


def _persist_usage(incident_id: str, budget: IncidentBudget) -> None:
    event_bridge.update_state(incident_id, token_usage=budget.snapshot())


async def _dispatch_diagnostic_agents(
    incident_id: str, question: str, agent_names: list[str], budget: IncidentBudget
) -> dict:
    for name in agent_names:
        event_bridge.emit_event(incident_id, "AGENT_STARTED", source="incident_manager", target=name)

    result = await investigate_incident(question, agent_names=agent_names)

    for name in result["agents_responded"]:
        finding = result["findings"][name]
        # Usage is bookkeeping, not evidence: take it off the Finding so it is
        # neither stored as agent_findings nor sent on to the Evidence Agent.
        budget.record(name, finding.pop("usage", None))
        a2a_meta = result["a2a"].get(name, {})
        event_bridge.emit_event(
            incident_id,
            "A2A_MESSAGE_SENT",
            source="incident_manager",
            target=name,
            status="completed",
            payload={"task_id": a2a_meta.get("task_id"), "context_id": a2a_meta.get("context_id")},
        )
        # mcp/audit.py bridge: these are the same real tool/arguments/result
        # facts recorded locally inside this agent's own MCP server process --
        # see orchestrator/event_bridge.py's module docstring.
        for item in finding.get("evidence", []) or []:
            ok = item["result"].get("ok") if isinstance(item.get("result"), dict) else None
            event_bridge.emit_event(
                incident_id,
                "MCP_TOOL_CALL",
                source=name,
                status="ok" if ok else "unknown",
                payload={"tool": item["tool"], "arguments": item["arguments"], "evidence_id": item["evidence_id"]},
            )
            event_bridge.emit_event(
                incident_id,
                "MCP_TOOL_RESULT",
                source=name,
                payload={"evidence_id": item["evidence_id"], "tool": item["tool"]},
            )
        event_bridge.emit_event(
            incident_id,
            "AGENT_COMPLETED",
            source=name,
            payload={"finding_id": finding["finding_id"], "confidence": finding["confidence"]},
        )
        event_bridge.emit_event(
            incident_id,
            "EVIDENCE_FOUND",
            source=name,
            payload={
                "finding_id": finding["finding_id"],
                "evidence_ids": [e["evidence_id"] for e in finding.get("evidence", []) or []],
            },
        )

    for name in set(agent_names) - set(result["agents_responded"]):
        event_bridge.emit_event(
            incident_id,
            "AGENT_COMPLETED",
            source=name,
            status="failed",
            payload={"reason": "no A2A response (Groq rate limit or agent unavailable)"},
        )

    _persist_usage(incident_id, budget)
    return result


async def _call_evidence_agent(
    incident_id: str, findings_by_agent: dict, budget: IncidentBudget, previous: list[dict] | None = None
) -> list[dict]:
    call = await call_remote_agent(EVIDENCE_AGENT_NAME, EVIDENCE_AGENT_DESCRIPTION, json.dumps(findings_by_agent))
    event_bridge.emit_event(
        incident_id,
        "A2A_MESSAGE_SENT",
        source="incident_manager",
        target=EVIDENCE_AGENT_NAME,
        status="completed",
        payload={"task_id": call["task_id"], "context_id": call["context_id"]},
    )
    response = call["response"] if isinstance(call["response"], dict) else {}
    budget.record(EVIDENCE_AGENT_NAME, response.pop("usage", None))
    _persist_usage(incident_id, budget)
    hypotheses = response.get("hypotheses", [])
    if not isinstance(hypotheses, list):
        hypotheses = []
    reconcile_hypotheses(previous or [], hypotheses)
    for hypothesis in hypotheses:
        event_bridge.emit_event(incident_id, "HYPOTHESIS_CREATED", source=EVIDENCE_AGENT_NAME, payload=hypothesis)
    return hypotheses


async def _call_critic(incident_id: str, hypothesis: dict, evidence_pool: list[dict], budget: IncidentBudget) -> dict:
    payload = {"hypothesis": hypothesis, "evidence_pool": evidence_pool}
    call = await call_remote_agent(CRITIC_AGENT_NAME, CRITIC_AGENT_DESCRIPTION, json.dumps(payload))
    event_bridge.emit_event(
        incident_id,
        "A2A_MESSAGE_SENT",
        source="incident_manager",
        target=CRITIC_AGENT_NAME,
        status="completed",
        payload={"task_id": call["task_id"], "context_id": call["context_id"]},
    )
    critique = call["response"] if isinstance(call["response"], dict) else None
    budget.record(CRITIC_AGENT_NAME, critique.pop("usage", None) if critique else None)
    _persist_usage(incident_id, budget)
    if not critique:
        critique = {
            "critique_id": None,
            "hypothesis_id": hypothesis.get("hypothesis_id"),
            "verdict": "INSUFFICIENT_EVIDENCE",
            "rationale": "critic A2A call returned no parseable response",
        }
    event_bridge.emit_event(
        incident_id, "CRITIC_CHALLENGE", source=CRITIC_AGENT_NAME, target=hypothesis.get("hypothesis_id"), payload=critique
    )
    return critique


def _stalled(critique: dict, previous_requests: set[str]) -> str | None:
    """A re-dispatch only helps if the critic asks for something new that the tools can
    fetch. Returns the reason to stop instead, or None to keep going."""
    requested = {str(r).strip().lower() for r in critique.get("requested_evidence") or [] if str(r).strip()}
    if not requested:
        return "critic requested no further obtainable evidence"
    if requested == previous_requests:
        return "critic repeated its previous evidence request; re-investigation added nothing"
    return None


async def run_investigation(
    incident_description: str,
    agent_names: list[str] | None = None,
    max_loops: int | None = None,
    trigger_recovery: bool = True,
    skip_critic: bool = False,
    incident_id: str | None = None,
    budget: IncidentBudget | None = None,
) -> dict:
    """Runs the full Phase 6 investigation and returns the final persisted
    incident state (fetched back from the backend, not an in-memory copy).
    `trigger_recovery=False` (Phase 9 evaluation baselines/ablation) stops
    right after DIAGNOSED/ABSTAINED -- no Recovery Agent call, no guardrails
    involvement at all. `skip_critic=True` (Phase 9 evaluation's "ablation
    without the critic/falsification loop" arm, per docs/EVALUATION.md) makes
    the leading hypothesis DIAGNOSED as soon as it exists, with ZERO real A2A
    calls to root_cause_critic -- a genuine ablation of the falsification
    loop, not a simulated one. `incident_id` (Phase 10 dashboard "Inject
    Controlled Failure" trigger): if given, attaches this investigation to an
    incident the caller already created via a real `POST /incidents` call
    (e.g. `backend/app/main.py`'s `/demo/investigate`, so the dashboard can
    redirect to the incident before the investigation itself finishes)
    instead of creating a new one -- the incident must already exist in
    `backend/`. `budget` (default: limits read from the environment, see
    `orchestrator/budget.py`): once it reports the call/token limit reached,
    no further model-backed step starts and the investigation ABSTAINS with
    the budget named as the reason -- it never forces a diagnosis."""
    max_loops = MAX_REEVALUATION_LOOPS if max_loops is None else max_loops
    # `agent_names` given = the caller forces exactly this set (no triage).
    # Otherwise the Incident Manager triages: only agents the report points at
    # are called (set NEXUS_TRIAGE=0 to always call all four).
    forced = bool(agent_names)
    available = list(agent_names) if forced else list(DIAGNOSTIC_AGENTS)
    use_triage = not forced and os.environ.get("NEXUS_TRIAGE", "1") != "0"
    budget = budget or IncidentBudget.from_env()

    incident_id = incident_id or event_bridge.create_incident(incident_description)
    event_bridge.emit_event(
        incident_id, "INCIDENT_CREATED", source="incident_manager", payload={"description": incident_description}
    )

    if use_triage:
        agent_names, skipped = triage.select_agents(incident_description, available)
    else:
        agent_names, skipped = available, []
    event_bridge.emit_event(
        incident_id, "AGENTS_SELECTED", source="incident_manager", payload=triage.describe(agent_names, skipped, 1)
    )

    dispatch = await _dispatch_diagnostic_agents(incident_id, incident_description, agent_names, budget)
    findings_by_agent = dispatch["findings"]
    event_bridge.update_state(incident_id, agent_findings=findings_by_agent, agent_messages=dispatch["a2a"])

    decision = None
    reason = None
    hypotheses: list[dict] = []
    critic_results: list[dict] = []
    loops_used = 0

    stop = budget.exceeded()
    if stop:
        decision, reason = "ABSTAINED", f"{stop} -- stopped before evidence synthesis"
    else:
        hypotheses = await _call_evidence_agent(incident_id, findings_by_agent, budget)
        event_bridge.update_state(incident_id, hypotheses=hypotheses)

    if skip_critic and decision is None:
        leading = _leading_hypothesis(hypotheses)
        loops_used = 1
        if leading is None:
            decision, reason = "ABSTAINED", "no open hypothesis left to evaluate (critic skipped -- ablation)"
        else:
            leading["status"] = "SUPPORTED"
            event_bridge.emit_event(incident_id, "HYPOTHESIS_UPDATED", source=EVIDENCE_AGENT_NAME, payload=leading)
            decision = "DIAGNOSED"
            reason = f"hypothesis {leading['hypothesis_id']} accepted without critic review (ablation: skip_critic=True)"
            synthetic_critique = {
                "critique_id": None,
                "hypothesis_id": leading["hypothesis_id"],
                "verdict": "SUPPORTED",
                "rationale": "critic skipped for this run (ablation study)",
            }
            critic_results.append(synthetic_critique)
            event_bridge.emit_event(
                incident_id, "DIAGNOSIS_REACHED", source="incident_manager", payload={"hypothesis": leading, "critique": synthetic_critique}
            )

    previous_requests: set[str] = set()
    for loop_index in range(1, max_loops + 1) if (not skip_critic and decision is None) else ():
        stop = budget.exceeded()
        if stop:
            decision, reason = "ABSTAINED", f"{stop} -- stopped before critic review"
            break
        loops_used = loop_index
        leading = _leading_hypothesis(hypotheses)
        if leading is None:
            decision, reason = "ABSTAINED", "no open hypothesis left to evaluate"
            break

        event_bridge.emit_event(
            incident_id,
            "RE_EVALUATION_STARTED",
            source="root_cause_critic",
            target=leading["hypothesis_id"],
            payload={"loop": loop_index, "max_loops": max_loops},
        )
        evidence_pool = _flatten_evidence(findings_by_agent)
        critique = await _call_critic(incident_id, leading, evidence_pool, budget)
        critic_results.append(critique)
        verdict = critique.get("verdict", "INSUFFICIENT_EVIDENCE")

        if verdict == "SUPPORTED":
            leading["status"] = "SUPPORTED"
            event_bridge.emit_event(incident_id, "HYPOTHESIS_UPDATED", source=EVIDENCE_AGENT_NAME, payload=leading)
            decision = "DIAGNOSED"
            reason = f"hypothesis {leading['hypothesis_id']} SUPPORTED by root-cause critic"
            event_bridge.emit_event(
                incident_id, "DIAGNOSIS_REACHED", source="root_cause_critic", payload={"hypothesis": leading, "critique": critique}
            )
            break

        if verdict == "CONTRADICTED":
            leading["status"] = "REJECTED"
            event_bridge.emit_event(incident_id, "HYPOTHESIS_UPDATED", source=EVIDENCE_AGENT_NAME, payload=leading)
            event_bridge.update_state(incident_id, hypotheses=hypotheses, critic_results=critic_results)
            continue  # try the next-leading open hypothesis within the same loop budget

        if verdict == "ABSTAIN":
            leading["status"] = "ABSTAINED"
            event_bridge.emit_event(incident_id, "HYPOTHESIS_UPDATED", source=EVIDENCE_AGENT_NAME, payload=leading)
            decision = "ABSTAINED"
            reason = critique.get("rationale", "root-cause critic abstained")
            break

        # INSUFFICIENT_EVIDENCE / REQUEST_MORE_EVIDENCE (or any unrecognized verdict,
        # which agents/critic/agent.py already normalizes down to this bucket).
        leading["status"] = "NEEDS_EVIDENCE"
        event_bridge.emit_event(incident_id, "HYPOTHESIS_UPDATED", source=EVIDENCE_AGENT_NAME, payload=leading)
        event_bridge.emit_event(
            incident_id,
            "EVIDENCE_REQUESTED",
            source="root_cause_critic",
            target="incident_manager",
            payload={"requested_evidence": critique.get("requested_evidence", []), "hypothesis_id": leading["hypothesis_id"]},
        )

        if loop_index == max_loops:
            break  # no loops left to re-dispatch; falls through to the abstain path below

        stop = budget.exceeded()
        if stop:
            decision, reason = "ABSTAINED", f"{stop} -- stopped before requesting more evidence"
            break

        stall_reason = _stalled(critique, previous_requests)
        if stall_reason:
            decision = "ABSTAINED"
            reason = f"{stall_reason} (loop {loop_index} of {max_loops})"
            break
        previous_requests = {str(r).strip().lower() for r in critique.get("requested_evidence") or []}

        follow_up = (
            f"Re-investigate incident: {incident_description}. The root-cause critic "
            f"requested more evidence for hypothesis '{leading['statement']}': "
            f"{critique.get('requested_evidence', [])}. Missing evidence noted: "
            f"{leading.get('missing_evidence', [])}."
        )
        if use_triage:
            ask_text = f"{critique.get('requested_evidence', [])} {leading.get('missing_evidence', [])}"
            again, skipped_again = triage.select_agents(ask_text, available, first_round=False)
            event_bridge.emit_event(
                incident_id, "AGENTS_SELECTED", source="incident_manager", payload=triage.describe(again, skipped_again, loop_index + 1)
            )
        else:
            again = agent_names
        more = await _dispatch_diagnostic_agents(incident_id, follow_up, again, budget)
        for name, finding in more["findings"].items():
            findings_by_agent[name] = finding  # latest finding per agent supersedes the prior one
        event_bridge.update_state(incident_id, agent_findings=findings_by_agent)

        hypotheses = await _call_evidence_agent(incident_id, findings_by_agent, budget, previous=hypotheses)
        event_bridge.update_state(incident_id, hypotheses=hypotheses, critic_results=critic_results)

    if decision is None:
        decision = "ABSTAINED"
        reason = f"reached MAX_REEVALUATION_LOOPS ({max_loops}) without a supported diagnosis"

    if decision == "ABSTAINED":
        event_bridge.emit_event(
            incident_id, "ABSTENTION", source="incident_manager", payload={"reason": reason, "loops_used": loops_used}
        )

    decision_record = {"outcome": decision, "reason": reason, "loops_used": loops_used, "max_loops": max_loops}
    event_bridge.update_state(
        incident_id,
        status=decision,
        hypotheses=hypotheses,
        critic_results=critic_results,
        decision=decision_record,
        token_usage=budget.snapshot(),
    )
    event_bridge.emit_event(incident_id, "INCIDENT_STATUS_CHANGED", source="incident_manager", payload={"status": decision})

    if decision == "DIAGNOSED" and trigger_recovery:
        stop = budget.exceeded()
        if stop:
            # The diagnosis stands; only the (model-backed) recovery proposal is
            # withheld, and the decision says so instead of failing silently.
            event_bridge.update_state(
                incident_id, decision={**decision_record, "reason": f"{reason}; recovery not started: {stop}"}
            )
            return event_bridge.get_incident(incident_id)
        # Phase 8: bounded recovery flow (propose -> validate -> human
        # approval -> execute -> verify). Never runs for ABSTAINED -- there
        # is nothing diagnosed to recover from. `leading`/critic_results[-1]
        # are the exact hypothesis/critique that were just SUPPORTED above.
        await recovery.run_recovery(
            incident_id, leading, critic_results[-1] if critic_results else {}, evidence_pool=_flatten_evidence(findings_by_agent)
        )

    return event_bridge.get_incident(incident_id)
