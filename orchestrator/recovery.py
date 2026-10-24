"""Phase 8: bounded recovery flow, run after `investigation.py` reaches a
DIAGNOSED decision (root CLAUDE.md section 20):

```
DIAGNOSED
   |
Recovery Agent (real A2A, agents/recovery/) -> RecoveryPlan
   |
guardrails.policy.validate_plan (local, deterministic, no LLM)
   |-- REJECTED --------------------------------------------> stop, incident stays DIAGNOSED
   |-- APPROVED_FOR_HUMAN_REVIEW
        |
        approval_state = PENDING, HUMAN_APPROVAL_REQUESTED emitted
        |
        poll backend/ for a human's real POST /incidents/{id}/approve,
        up to MAX_APPROVAL_WAIT_SECONDS
        |-- REJECTED by human -----------------------------> stop, incident stays DIAGNOSED
        |-- timed out ---------------------------------------> stop, approval_state EXPIRED
        |-- APPROVED by human
             |
             guardrails.executor.execute_plan (bounded, kill-switch-gated,
             real HTTP calls to production/'s admin endpoints)
             |
             verification: a deterministic live probe (timed real requests to
             production/: latency AND failures must be healthy) decides; the
             Metrics Agent re-check is kept as supporting evidence only
             |-- verified ------------------------------------> INCIDENT_RESOLVED
             |-- not verified --------------------------------> RECOVERY_FAILED,
                                                                  incident stays DIAGNOSED
```

Never executes anything the RecoveryAgent (an LLM with no tools) said
directly -- `guardrails/policy.py` and `guardrails/executor.py` independently
re-validate and are the only code path with real execution capability (root
CLAUDE.md section 20). Every transition is persisted to `backend/` via
`event_bridge.py`, same as `investigation.py`.
"""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "guardrails"))

import event_bridge  # noqa: E402
import executor as guardrails_executor  # noqa: E402
import policy as guardrails_policy  # noqa: E402
import remedy as guardrails_remedy  # noqa: E402
from config import APPROVAL_POLL_INTERVAL_SECONDS, MAX_APPROVAL_WAIT_SECONDS, PRODUCTION_BASE_URL  # noqa: E402
from remote_call import call_remote_agent  # noqa: E402

RECOVERY_AGENT_NAME = "recovery_agent"
RECOVERY_AGENT_DESCRIPTION = "NEXUS Recovery Agent: proposes a bounded RecoveryPlan for a diagnosed incident."
METRICS_AGENT_NAME = "metrics_agent"
METRICS_AGENT_DESCRIPTION = "NEXUS Metrics Agent: real-time request/latency/error metrics."

VERIFICATION_ERROR_RATE_THRESHOLD = 0.2
# Live probe used to decide whether a recovery actually worked. A healthy simulated
# service answers in ~1ms; the injected db_slowdown adds ~250ms per query.
VERIFICATION_LATENCY_MS = float(os.environ.get("VERIFICATION_LATENCY_MS", "100"))
VERIFICATION_PROBE_REQUESTS = int(os.environ.get("VERIFICATION_PROBE_REQUESTS", "5"))
_PROBE_PATHS = ("/orders", "/orders/1")  # /orders/{id} also exercises the dependency path


async def _call_recovery_agent(incident_id: str, hypothesis: dict, critique: dict, evidence_pool: list[dict]) -> dict:
    payload = {"hypothesis": hypothesis, "critique": critique, "evidence_pool": evidence_pool}
    # Deterministic, evidence-derived hint: which actions fix the symptoms the
    # evidence shows (guardrails/remedy.py). The same check re-validates the plan.
    remedy_guidance = guardrails_remedy.guidance(evidence_pool)
    if remedy_guidance:
        payload["remedy_guidance"] = remedy_guidance
    call = await call_remote_agent(RECOVERY_AGENT_NAME, RECOVERY_AGENT_DESCRIPTION, json.dumps(payload))
    event_bridge.emit_event(
        incident_id,
        "A2A_MESSAGE_SENT",
        source="incident_manager",
        target=RECOVERY_AGENT_NAME,
        status="completed",
        payload={"task_id": call["task_id"], "context_id": call["context_id"]},
    )
    response = call["response"] if isinstance(call["response"], dict) else {}
    event_bridge.emit_monitor(incident_id, RECOVERY_AGENT_NAME, response.pop("monitoring", None))
    plan = response.get("recovery_plan")
    if not isinstance(plan, dict):
        plan = {"plan_id": None, "actions": [], "risk_level": None, "rollback_plan": None}
    event_bridge.emit_event(incident_id, "RECOVERY_PROPOSED", source=RECOVERY_AGENT_NAME, payload=plan)
    return plan


def _wait_for_human_approval(incident_id: str, timeout_seconds: int) -> dict:
    """Polls backend/ for a real out-of-band POST /incidents/{id}/approve.
    Bounded -- root CLAUDE.md forbids an indefinite autonomous hang just as
    much as an indefinite autonomous loop."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        incident = event_bridge.get_incident(incident_id)
        approval = incident.get("approval_state") or {}
        if approval.get("decision") in ("APPROVED", "REJECTED"):
            return approval
        time.sleep(APPROVAL_POLL_INTERVAL_SECONDS)
    return {"decision": "EXPIRED"}


def _probe_service(get=httpx.get, now=time.perf_counter) -> dict:
    """Deterministic post-recovery check: send real, timed requests to the live
    service and require BOTH latency and failures to be healthy.

    Why this exists: the metrics store is cumulative and the old check only
    looked at the error RATE, so a latency-only fault (db_slowdown: zero errors,
    ~260ms per request) always "passed" and an unfixed incident was marked
    RESOLVED. No LLM involved; `get`/`now` are injectable for tests."""
    per_path: dict[str, dict] = {}
    for path in _PROBE_PATHS:
        latencies: list[float] = []
        failures = 0
        for _ in range(VERIFICATION_PROBE_REQUESTS):
            started = now()
            try:
                ok = get(f"{PRODUCTION_BASE_URL}{path}", timeout=5.0).status_code < 500
            except httpx.HTTPError:
                ok = False
            latencies.append((now() - started) * 1000.0)
            failures += 0 if ok else 1
        per_path[path] = {
            "median_ms": round(statistics.median(latencies), 1),
            "failures": failures,
            "requests": VERIFICATION_PROBE_REQUESTS,
        }
    healthy = all(
        p["median_ms"] < VERIFICATION_LATENCY_MS and p["failures"] / p["requests"] < VERIFICATION_ERROR_RATE_THRESHOLD
        for p in per_path.values()
    )
    return {"healthy": healthy, "latency_limit_ms": VERIFICATION_LATENCY_MS, "per_path": per_path}


async def _verify_recovery(incident_id: str) -> dict:
    """Decides whether the recovery worked. The live probe (`_probe_service`)
    is the ONLY thing that can pass verification. The Metrics Agent re-check
    (real second A2A dispatch) is kept as supporting evidence for the audit
    trail, fail-soft: if the model is unavailable it cannot break, or pass,
    verification."""
    probe = await asyncio.to_thread(_probe_service)
    finding: dict = {}
    error_rate = None
    try:
        call = await call_remote_agent(
            METRICS_AGENT_NAME,
            METRICS_AGENT_DESCRIPTION,
            "Recovery actions were just executed for this incident. Check current error rate and latency.",
        )
        finding = call["response"] if isinstance(call["response"], dict) else {}
        finding.pop("monitoring", None)  # callback trace is for the event log, not evidence
    except Exception as exc:  # noqa: BLE001 -- supporting evidence only; never gates the result
        finding = {"unavailable": f"{type(exc).__name__}"}
    for item in finding.get("evidence", []) or []:
        result = item.get("result") if isinstance(item, dict) else None
        if isinstance(result, dict) and "error_rate" in result:
            error_rate = result["error_rate"]
        elif isinstance(result, dict) and "error_count" in result and "request_count" in result:
            total = result.get("request_count") or 0
            errors = result.get("error_count") or 0
            error_rate = (errors / total) if total else 0.0
    return {"verified": probe["healthy"], "probe": probe, "error_rate": error_rate, "finding": finding}


async def run_recovery(incident_id: str, hypothesis: dict, critique: dict, evidence_pool: list[dict] | None = None) -> dict:
    """Entry point called by investigation.py right after a DIAGNOSED
    decision. Returns a dict describing the outcome; never raises for a
    REJECTED/EXPIRED/failed-verification outcome -- those are legitimate,
    logged stopping points, not exceptions (same "abstain, never force it"
    philosophy as investigation.py's re-evaluation loop, applied to recovery).
    `evidence_pool` (the same flattened real MCP evidence the critic saw) is
    the Recovery Agent's ONLY real source for a concrete target_version --
    without it, it has no way to name a real prior version for
    rollback_deployment (verified live: the agent correctly refuses to
    invent one when evidence_pool is empty, which guardrails/policy.py then
    correctly REJECTS for missing required params -- see docs/PROJECT_STATE.md).
    """
    plan = await _call_recovery_agent(incident_id, hypothesis, critique, evidence_pool or [])

    validation = guardrails_policy.validate_plan(plan, evidence_pool=evidence_pool or [])
    event_bridge.emit_event(
        incident_id, "SAFETY_VALIDATION", source="guardrails", target=plan.get("plan_id"), payload=validation
    )
    event_bridge.update_state(incident_id, recovery_plan=plan)

    if validation["verdict"] == "REJECTED":
        event_bridge.update_state(incident_id, approval_state={"decision": "NOT_REQUESTED", "reason": "plan rejected by safety validation"})
        return {"outcome": "REJECTED_BY_SAFETY_VALIDATION", "plan": plan, "validation": validation}

    event_bridge.update_state(incident_id, approval_state={"decision": "PENDING", "requested_at": validation["timestamp"]})
    event_bridge.emit_event(
        incident_id, "HUMAN_APPROVAL_REQUESTED", source="guardrails", target="human", payload={"plan_id": plan.get("plan_id")}
    )

    approval = _wait_for_human_approval(incident_id, MAX_APPROVAL_WAIT_SECONDS)

    if approval["decision"] == "EXPIRED":
        event_bridge.update_state(incident_id, approval_state={"decision": "EXPIRED"})
        event_bridge.emit_event(incident_id, "HUMAN_APPROVAL_REQUESTED", source="guardrails", status="expired", payload={"plan_id": plan.get("plan_id")})
        return {"outcome": "APPROVAL_EXPIRED", "plan": plan, "validation": validation}

    if approval["decision"] == "REJECTED":
        event_bridge.emit_event(incident_id, "HUMAN_APPROVAL_REJECTED", source="human", payload={"plan_id": plan.get("plan_id")})
        return {"outcome": "REJECTED_BY_HUMAN", "plan": plan, "validation": validation, "approval": approval}

    event_bridge.emit_event(incident_id, "HUMAN_APPROVAL_GRANTED", source="human", payload={"plan_id": plan.get("plan_id")})

    return await _execute_and_verify(incident_id, plan, validation, approval)


async def _execute_and_verify(incident_id: str, plan: dict, validation: dict, approval: dict) -> dict:
    """Everything after a human approved: execute (kill-switch-gated), verify with the live probe,
    resolve only on verified success. Shared by the normal flow and a late-approval resume."""
    execution = guardrails_executor.execute_plan(plan)
    event_bridge.emit_event(incident_id, "RECOVERY_EXECUTED", source="guardrails", payload=execution)
    event_bridge.update_state(incident_id, action_history=execution["action_history"])

    if not execution["all_succeeded"]:
        event_bridge.update_state(incident_id, status="DIAGNOSED")
        return {"outcome": "EXECUTION_FAILED", "plan": plan, "validation": validation, "approval": approval, "execution": execution}

    verification = await _verify_recovery(incident_id)
    event_bridge.emit_event(incident_id, "RECOVERY_VERIFIED", source="guardrails", payload=verification)

    if not verification["verified"]:
        event_bridge.update_state(incident_id, status="DIAGNOSED")
        return {
            "outcome": "VERIFICATION_FAILED",
            "plan": plan,
            "validation": validation,
            "approval": approval,
            "execution": execution,
            "verification": verification,
        }

    event_bridge.update_state(incident_id, status="RESOLVED")
    event_bridge.emit_event(incident_id, "INCIDENT_RESOLVED", source="incident_manager", payload={"plan_id": plan.get("plan_id")})
    return {
        "outcome": "RESOLVED",
        "plan": plan,
        "validation": validation,
        "approval": approval,
        "execution": execution,
        "verification": verification,
    }


async def resume_approved_recovery(incident_id: str) -> dict:
    """Late approval: the approval window closed (the orchestrator process exited,
    approval_state EXPIRED) but a human later approved the SAVED plan. Re-checks the
    plan from scratch against the guardrails -- the saved plan is not trusted -- then
    runs the same execute -> verify path. Only ever acts on an incident whose
    approval_state is a real human APPROVED decision."""
    incident = event_bridge.get_incident(incident_id)
    plan = incident.get("recovery_plan")
    approval = incident.get("approval_state") or {}
    if not isinstance(plan, dict) or approval.get("decision") != "APPROVED":
        return {"outcome": "NOTHING_TO_RESUME"}

    evidence_pool = [
        item for finding in (incident.get("agent_findings") or {}).values() for item in (finding.get("evidence") or [])
    ]
    validation = guardrails_policy.validate_plan(plan, evidence_pool=evidence_pool)
    event_bridge.emit_event(
        incident_id, "SAFETY_VALIDATION", source="guardrails", target=plan.get("plan_id"), payload=validation
    )
    if validation["verdict"] == "REJECTED":
        return {"outcome": "REJECTED_BY_SAFETY_VALIDATION", "plan": plan, "validation": validation}
    return await _execute_and_verify(incident_id, plan, validation, approval)
