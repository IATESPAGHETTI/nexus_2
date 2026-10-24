# NEXUS Event Schema

Live event contract. Every major transition in the system emits one of these events.
The dashboard subscribes to the event stream and must never fabricate or replay events
that didn't actually happen.

## Envelope

```json
{
  "event_id": "evt-123",
  "incident_id": "INC-001",
  "timestamp": "2026-01-01T12:00:00Z",
  "event_type": "AGENT_HANDOFF",
  "source": "evidence_agent",
  "target": "root_cause_critic",
  "status": "started",
  "payload": { "message": "Review hypothesis H1" }
}
```

- `event_id`: unique, monotonically orderable within an incident.
- `incident_id`: foreign key into incident state.
- `timestamp`: ISO 8601 UTC.
- `event_type`: one of the minimum set below (extend, never repurpose).
- `source` / `target`: component or agent name; `target` optional for non-directed events.
- `status`: free-form short status (`started`, `completed`, `failed`, ...) where applicable.
- `payload`: event-specific structured data. No private model chain-of-thought — only
  auditable artifacts (observation, evidence, hypothesis, supporting/contradicting
  evidence, requested evidence, decision).

## Minimum event types

```text
INCIDENT_CREATED
INCIDENT_STATUS_CHANGED
AGENT_STARTED
AGENT_COMPLETED
AGENTS_SELECTED
A2A_MESSAGE_SENT
MCP_TOOL_CALL
MCP_TOOL_RESULT
EVIDENCE_FOUND
HYPOTHESIS_CREATED
HYPOTHESIS_UPDATED
CRITIC_CHALLENGE
EVIDENCE_REQUESTED
RE_EVALUATION_STARTED
DIAGNOSIS_REACHED
ABSTENTION
RECOVERY_PROPOSED
SAFETY_VALIDATION
HUMAN_APPROVAL_REQUESTED
HUMAN_APPROVAL_GRANTED
HUMAN_APPROVAL_REJECTED
RECOVERY_EXECUTED
RECOVERY_VERIFIED
INCIDENT_RESOLVED
```

Renamed from an earlier draft (`RECOVERY_PLAN_CREATED`, `SAFETY_CHECK`,
`HUMAN_APPROVAL_REQUIRED`, `HUMAN_APPROVED`, `RECOVERY_STARTED`/
`RECOVERY_COMPLETED`, `VERIFICATION_STARTED`/`VERIFICATION_COMPLETED`) to
match root `CLAUDE.md` section 16's canonical names exactly, at Phase 8
implementation time -- root `CLAUDE.md` is the non-negotiable master spec, so
this file is the one that had to change. `HUMAN_APPROVAL_REJECTED` is an
addition beyond section 16's list (a human explicitly rejecting a plan is a
distinct, real outcome from an approval being granted) -- an intentional
extension, not a repurposing of an existing type, per this file's own rule.
`RECOVERY_EXECUTED`/`RECOVERY_VERIFIED` are each emitted once per recovery
attempt (not split into STARTED/COMPLETED pairs) -- `guardrails/executor.py`'s
`execute_plan()` and `orchestrator/recovery.py`'s `_verify_recovery()` are
each a single bounded call, not a long-running process worth a start/finish
pair of events.

## Status

Implemented (Phase 6 + Phase 8). Producer: `orchestrator/event_bridge.py` (real
HTTP POST to `backend/`), called throughout `orchestrator/investigation.py`'s
bounded re-evaluation loop and `orchestrator/recovery.py`'s bounded recovery
flow. Consumer/store: `backend/app/incident_store.py` +
`backend/app/main.py`'s `/incidents/{id}/events` endpoints. Event types
actually emitted: `INCIDENT_CREATED`, `AGENTS_SELECTED`, `AGENT_STARTED`, `A2A_MESSAGE_SENT`,
`MCP_TOOL_CALL`, `MCP_TOOL_RESULT`, `AGENT_COMPLETED`, `EVIDENCE_FOUND`,
`HYPOTHESIS_CREATED`, `HYPOTHESIS_UPDATED`, `RE_EVALUATION_STARTED`,
`CRITIC_CHALLENGE`, `EVIDENCE_REQUESTED`, `DIAGNOSIS_REACHED`, `ABSTENTION`,
`INCIDENT_STATUS_CHANGED`, `RECOVERY_PROPOSED`, `SAFETY_VALIDATION`,
`HUMAN_APPROVAL_REQUESTED`, `HUMAN_APPROVAL_GRANTED`,
`HUMAN_APPROVAL_REJECTED`, `RECOVERY_EXECUTED`, `RECOVERY_VERIFIED`,
`INCIDENT_RESOLVED`, `INPUT_REJECTED` (input guardrail blocked the incident description; no agent is called), `AGENT_MONITOR` (2026-10-15: one per agent task; payload = the ADK callback trace from `agents/common/callbacks.py`: model calls, tool calls, durations, errors; keys and sizes only). `MCP_TOOL_CALL`/`MCP_TOOL_RESULT` are sourced from the
real evidence already present in each diagnostic agent's Finding, not a
direct read of `mcp/audit.py`'s in-process deque — see
`orchestrator/event_bridge.py`'s module docstring for why, and
`docs/PROJECT_STATE.md`'s "Known limitations" for this documented as an
explicit scope boundary, not an oversight. `dashboard/` has no consumer yet
for the Phase 8 event types (its Phase 7 `RecoveryPlaceholder` is still
disabled/unwired — see `docs/PROJECT_STATE.md`).

## AGENTS_SELECTED (2026-10-13)

Emitted by the Incident Manager before each dispatch round (source `incident_manager`). Payload:
`{"round": 1, "selected": ["metrics_agent", ...], "skipped": [{"agent": "change_analysis_agent", "reason": "..."}]}`.
Round 1 is chosen from the reported symptom text only; later rounds from what the Critic requested. The dashboard
shows skipped agents as "not called" with the reason. One event per round, not per agent.