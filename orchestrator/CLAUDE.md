# Orchestrator Local Instructions

## Purpose
Incident Manager: dispatches an incident to all 4 diagnostic agents in parallel
over real A2A, collects their structured Findings (Phase 5). Phase 6 added the
bounded evidence -> hypothesis -> critic re-evaluation loop
(`investigation.py`), a real-HTTP event bridge into `backend/`'s incident
state + event store (`event_bridge.py`), and a generic single-agent A2A call
helper (`remote_call.py`) reused for both the Evidence Agent and Root-Cause
Critic. Deepu's primary responsibility (see root CLAUDE.md).

## Framework decision
**Google ADK (Python)**, gated by the mandatory spike in root CLAUDE.md section 9.1.
The spike PASSED — see `orchestrator/spike/SPIKE_RESULT.md`. Runtime model: GPT-OSS
120B via Groq, through ADK's `LiteLlm` wrapper. A2A: real `a2a-sdk` +
`google.adk.agents.RemoteA2aAgent` (Phase 5, PASSED — see `docs/PROJECT_STATE.md`).

## Critical: Groq/GPT-OSS gotchas (read before writing any agent)
- Every `LiteLlm` model instance for a Groq-backed agent **must** set
  `include_reasoning=False`. Without this, multi-turn tool-calling fails on the
  second turn (`GroqException` about `reasoning_content`). `litellm.drop_params =
  True` does **not** fix this. Full writeup: `orchestrator/spike/SPIKE_RESULT.md`.
  (This module doesn't construct any `LiteLlm` itself — the 4 diagnostic agents
  it dispatches to do, in `agents/common/diagnostic_agent.py`.)
- Groq's free tier limits `openai/gpt-oss-120b` to 8000 tokens/min, shared across
  ALL agents. Dispatching to 4 agents in parallel (`investigate_incident()`) can
  trip a real `RateLimitError` — `agents/common/diagnostic_agent.py` sets
  `litellm.num_retries = 5` to absorb this with backoff. See
  `docs/PROJECT_STATE.md` "Known Issues" for the observed failure/fix.

## Owned
- `incident_manager.py` — **implemented (Phase 5)**.
  - `DIAGNOSTIC_AGENTS`: name -> description for the 4 diagnostic agents.
  - `build_incident_manager(agent_names=None) -> ParallelAgent`: builds an ADK
    `ParallelAgent` whose `sub_agents` are `RemoteA2aAgent` proxies (from
    `agents/common/remote_agent.py`) for the named agents (all 4 by default).
    `ParallelAgent` dispatches to all sub-agents concurrently — genuine parallel
    A2A fan-out, not a loop of direct calls.
  - `investigate_incident(incident_description, agent_names=None) -> dict`: runs
    the above via `InMemoryRunner`, parses each agent's real A2A response text
    as JSON (the Finding produced by `agents/common/a2a_server.py`), and returns
    `{"findings": {...}, "a2a": {...task_id/context_id per agent...},
    "agents_dispatched": [...], "agents_responded": [...]}`.
- `investigation.py` — **implemented (Phase 6)**. `run_investigation(incident_description,
  agent_names=None, max_loops=None, trigger_recovery=True, skip_critic=False,
  incident_id=None) -> dict`: the full bounded re-evaluation loop (root
  CLAUDE.md section 14). `incident_id` (Phase 10, additive, default `None`
  preserves all prior behavior): attaches to an incident the caller already
  created via `POST /incidents` — used by `backend/app/demo.py`'s
  "Inject Controlled Failure" trigger so the dashboard can redirect to the
  incident immediately, before the investigation itself finishes — instead
  of always creating a new one. Creates a real incident in `backend/`,
  dispatches to the diagnostic agents (via `incident_manager.investigate_incident`),
  calls the Evidence Agent over real A2A to get Hypotheses, then loops up to
  `MAX_REEVALUATION_LOOPS` (env var, default 3) calling the Root-Cause Critic
  over real A2A on the leading open hypothesis: `SUPPORTED` -> diagnosis
  reached; `CONTRADICTED` -> reject, try the next hypothesis (same loop
  budget); `INSUFFICIENT_EVIDENCE`/`REQUEST_MORE_EVIDENCE` -> real second-round
  A2A dispatch to the diagnostic agents for more evidence, hypotheses
  regenerated, loop continues if budget remains; `ABSTAIN` -> abstain. If the
  loop exhausts its budget without `SUPPORTED`/`ABSTAIN`, it abstains rather
  than forcing a diagnosis (root CLAUDE.md "never force a diagnosis"). Every
  transition is persisted to `backend/` via `event_bridge.py` (real HTTP, not
  an in-memory log).
- `budget.py` — **implemented (2026-10-10)**. `IncidentBudget`: per-incident
  spending limits (root CLAUDE.md section 8) from `MAX_LLM_CALLS_PER_INCIDENT`
  (60), `MAX_TOTAL_TOKENS_PER_INCIDENT` (250000), `MAX_TOKENS_PER_AGENT` (80000)
  — defaults are unmeasured guesses. `record(agent, usage)` adds the model usage
  an agent task reported (no usage -> counted as 1 unmeasured call);
  `exceeded()` says why no more model calls may start; `snapshot()` is what is
  persisted as `incident.token_usage`. `investigation.py` pops the `usage` key
  off every agent reply, checks the budget before evidence synthesis, each
  critic review, each re-dispatch and recovery, and ABSTAINS naming the limit
  when spent (never forces a diagnosis). Not yet counted: Recovery Agent and
  post-fix verification calls.
- `event_bridge.py` — **implemented (Phase 6)**. Thin real `httpx` client to
  `backend/`'s `/incidents`, `/incidents/{id}/events`, `/incidents/{id}/state`
  endpoints (`NEXUS_BACKEND_URL`, default `http://127.0.0.1:8000`). This is how
  `mcp/audit.py`'s and the A2A layer's activity reach the shared event store —
  see this module's own docstring for the exact (documented, not overclaimed)
  mechanism: the real tool/arguments/result facts already present in each
  Finding's `evidence` list are emitted as `MCP_TOOL_CALL`/`MCP_TOOL_RESULT`
  events, since `mcp/audit.py`'s in-process deque (inside each diagnostic
  agent's own OS process, reached over stdio) has no network-queryable API by
  design.
- `remote_call.py` — **implemented (Phase 6)**. `call_remote_agent(agent_name,
  description, message_text) -> dict`: builds a `RemoteA2aAgent` for the named
  agent and runs it directly through `InMemoryRunner` (same mechanism
  `agents/tests/test_a2a.py` proves works for a bare `RemoteA2aAgent`), parses
  the JSON response, and returns it with the real `task_id`/`context_id`.
  Used for the Evidence Agent (port 8105), Root-Cause Critic (port 8106), and
  (Phase 8) the Recovery Agent (port 8107) + a post-recovery verification
  call back to the Metrics Agent — never a direct import of any agent module.
- `recovery.py` — **implemented (Phase 8)**. `run_recovery(incident_id,
  hypothesis, critique, evidence_pool) -> dict`: the bounded recovery flow
  (root CLAUDE.md section 20), called automatically by `investigation.py`
  right after a `DIAGNOSED` decision (`trigger_recovery=True`, the default).
  Recovery Agent (real A2A) proposes a RecoveryPlan -> `guardrails.policy.
  validate_plan()` (independent, deterministic, no LLM) -> REJECTED stops;
  else `approval_state=PENDING`, polls `backend/` for a real
  `POST /incidents/{id}/approve` up to `MAX_APPROVAL_WAIT_SECONDS` ->
  REJECTED/EXPIRED stops; else `guardrails.executor.execute_plan()` (bounded,
  kill-switch-gated, real HTTP to `production/`'s admin endpoints) -> a real
  second A2A call to the Metrics Agent verifies the fix -> `RESOLVED` only on
  verified success. Every branch persists to `backend/` via `event_bridge.py`
  and never forces a resolution it can't verify (same "abstain, never force
  it" philosophy `investigation.py`'s re-evaluation loop already applies to
  diagnosis, now applied to recovery). Imports `guardrails/` via `sys.path`
  (no dedicated venv needed there — see `guardrails/CLAUDE.md`).

## Dependency isolation
This folder has its OWN `requirements.txt` and must be installed into its OWN venv
(`.venv-orchestrator/` at repo root, gitignored) — never into the shared venv used
by `backend/`/`production/`. Installing `mcp`/`google-adk`/`litellm` into the shared
venv previously broke the pinned `fastapi==0.115.0` (upgraded `starlette`
transitively) and had to be reverted. Do not repeat that mistake.

`orchestrator/requirements.txt`: `google-adk==2.9.1`, `litellm==1.101.0`,
`python-dotenv==1.2.3`, `a2a-sdk==1.1.4`, `opentelemetry-api==1.42.1` (pinned down
to match `google-adk`'s own constraint — installing `a2a-sdk` alone pulls a newer
`opentelemetry-api` that conflicts; `pip show` will warn about `google-api-core`
wanting the newer one back, but this is a benign, non-blocking resolver warning —
verified by successful imports), `httpx==0.28.1` (Phase 6: `event_bridge.py`'s
real calls to `backend/` — was already present transitively via `a2a-sdk` at
this exact version, now pinned explicitly since this venv uses it directly too),
`pytest==9.1.1`, `pytest-asyncio==1.4.0`. Note: this venv does **not** have the
`mcp` package — `RemoteA2aAgent` doesn't need it (only `McpToolset`, used inside
each diagnostic agent's own process, does).

```bash
python -m venv .venv-orchestrator
.venv-orchestrator/Scripts/python -m pip install -r orchestrator/requirements.txt
```

## Contract
Consumes agent Findings shaped per `docs/API_CONTRACT.md` "Agent finding schema"
— arriving as real A2A task-completion messages, not local return values. See
`docs/API_CONTRACT.md` "A2A protocol (implemented)" for the exact request/response
shapes.

## Rules
Never force a diagnosis just to finish the loop — must be able to abstain.
`investigation.py`'s bounded loop enforces this: if `MAX_REEVALUATION_LOOPS` is
exhausted without a `SUPPORTED`/`ABSTAIN` verdict, the outcome is `ABSTAINED`,
never a fabricated diagnosis. Do not mutate infrastructure directly; only
through `mcp/` tools invoked by agents. Do not claim "genuine A2A" merely
because separate ADK agent objects exist in the same Python process — this
module's `RemoteA2aAgent` proxies talk to agents running in **separate OS
processes** (`agents/*/a2a_service.py`, now including `evidence/` and
`critic/`), verified during implementation (`netstat`-confirmed distinct
listening ports, real HTTP calls with real task/context IDs). Never import a
diagnostic/evidence/critic agent's Python module directly here — only ever
reach them through `remote_agent.build_remote_agent()` /
`remote_call.call_remote_agent()`.

## Status
Phase 2.5 (ADK/Groq spike): **implemented + tested, PASS**. Phase 5 (A2A +
Incident Manager parallel dispatch): **implemented + tested, PASS**. Phase 6
(bounded evidence -> hypothesis -> critic re-evaluation loop, backend event
bridge): **implemented + tested, PASS**. Phase 8 (bounded recovery flow):
**implemented + tested** (deterministic control-flow tests all pass; the
Recovery Agent's real A2A call and `guardrails/`'s real execution against
live `production/` were each verified live in this same session -- see
`docs/PROJECT_STATE.md` "Phase 8" -- but a full live DIAGNOSED->RESOLVED run
through `run_investigation` itself was blocked by the Groq account's daily
token quota exhausting mid-session; flagged honestly, not claimed).

## Test
```bash
.venv-orchestrator/Scripts/python orchestrator/spike/adk_groq_spike.py
.venv-orchestrator/Scripts/python -m pytest orchestrator/tests -q
```
14 tests: 1 spike regression (`test_adk_groq_spike.py`) + 2 real end-to-end
Incident Manager tests (`test_incident_manager.py`, Phase 5, unchanged) + 7
deterministic orchestration-logic tests (`test_investigation_logic.py`, Phase
6/8 — `run_investigation`'s control flow with the two real-A2A boundaries
monkeypatched: SUPPORTED-first-loop, CONTRADICTED-then-ABSTAIN, zero-hypotheses
abstain, max-loop-exhaustion abstain, the DIAGNOSED->recovery hook wiring, and
the `skip_critic` ablation's two paths) + 1 real end-to-end investigation
test (`test_investigation_e2e.py`, Phase 6 — the full real chain: diagnostic
findings via real A2A -> Evidence Agent via real A2A -> Hypotheses ->
Root-Cause Critic via real A2A -> bounded decision, with every transition
verified present in the real backend event store over a real second HTTP
fetch) + 6 deterministic recovery-flow tests (`test_recovery_logic.py`, Phase
8 — `run_recovery`'s control flow with its A2A/backend/guardrails-execution
boundaries monkeypatched: safety-validation rejection, approval expiry,
human rejection, full approved->executed->verified->RESOLVED path,
execution-failure stop, and verification-failure stop -- none of these ever
claim RESOLVED without a real, checked verification step).

**Requires all 6 `agents/*/a2a_service.py` processes (4 diagnostic +
`evidence/` + `critic/`) + `production/` + `backend/` running** (see
`agents/tests/test_a2a.py` docstring for the diagnostic-agent commands; add
`.venv-agents/Scripts/python agents/evidence/a2a_service.py` and
`agents/critic/a2a_service.py`) and `GROQ_API_KEY` in repo-root `.env` — makes
real Groq API calls and real A2A network calls. `test_investigation_logic.py`
alone needs none of this (network boundaries are monkeypatched) and runs in
under 2 seconds.

## Usually inspect
`incident_manager.py`, `investigation.py`, `event_bridge.py`, `remote_call.py`,
`orchestrator/spike/SPIKE_RESULT.md`, `orchestrator/requirements.txt`,
`docs/API_CONTRACT.md`, `docs/EVENT_SCHEMA.md`, `docs/PROJECT_STATE.md`

## Usually don't touch
`backend/`, `production/`, `mcp/` (separate verified components, separate venv)

## Blackboard topology (2026-10-15)
- `blackboard.py`: with `NEXUS_TOPOLOGY=blackboard`, `investigation.py` swaps three call sites (specialist dispatch, evidence
  synthesis, critic review) for board versions with identical return shapes. Details: `docs/PROJECT_STATE.md`.
- Also new: `INPUT_REJECTED` gate, `run_config`, `trace_id` (nexus_trace.py), `attach_report` (report + trace + lineage).

## Triage (2026-10-13)
- `triage.py`: `select_agents(text, available, first_round=True)` picks which diagnostic agents to call from keyword
  rules over the symptom text (never the injected fault). Metrics is always first and at least 2 agents are used on
  round 1; later rounds ask only agents the Critic's request points at (everyone if none). `investigation.py` emits
  `AGENTS_SELECTED` per round. `NEXUS_TRIAGE=0` or an explicit `agent_names` bypasses it. Tests: `tests/test_triage.py`.