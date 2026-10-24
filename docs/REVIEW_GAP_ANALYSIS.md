# Project review: gap analysis against the 11 minimum requirements

Date: 2026-10-15. Method: read `docs/PROJECT_STATE.md`, the agent/orchestrator/guardrails/evaluation code and
`git grep` for each requirement's key terms. Nothing was run in this pass; statuses describe what the code
contains, using the root `CLAUDE.md` vocabulary.

| # | Requirement | Status | Short reason |
|---|---|---|---|
| 1 | Shared state, compare messaging architectures, **Blackboard** | blackboard implemented + tested (2026-10-15); measured comparison pending | `NEXUS_TOPOLOGY=hub\|blackboard`; comparison needs the benchmark |
| 2 | MCP tools (>= 2) | implemented + tested | 7 MCP tools (git diff disabled by default) |
| 3 | Pydantic structured output | implemented + tested (2026-10-15) | `nexus_models.py`; builders validate; final `IncidentReport` JSON+Markdown |
| 4 | Agentic design patterns, compared | partially implemented | Several patterns present, none compared |
| 5 | Monitoring via callbacks | implemented + tested (2026-10-15) | ADK callbacks -> AGENT_MONITOR events; CrewAI side records around the call |
| 6 | A2A, ADK <-> CrewAI interop | implemented + tested (Critic) | ADK client -> CrewAI Critic over A2A, verified live 2026-10-15 |
| 7 | Both CrewAI and ADK | implemented + tested (Critic) | `crewai_critic/`; one agent only, others ADK |
| 8 | Guardrails, input/tool-return validation, prompt variance | implemented + tested (2026-10-15) | Input + tool-output guards, red-team tests, 5 prompt variants; heuristics only |
| 9 | Observability: tracing, auditability, provenance | implemented + tested (2026-10-15) | W3C trace id across A2A, span tree, lineage; no external collector, no UI panel yet |
| 10 | End-to-end evaluation, cost/time, prompt variance | partially implemented | 3-arm harness; no repeats, no prompt variants, no dollar cost |
| 11 | Cloud deployment | **not implemented** | Compose runs 2 of ~10 processes; never built or run |

## Per requirement

### 1. Context sharing, messaging architectures, Blackboard — partially implemented
- Have: the Incident Manager fans out to four specialists, passes their Findings to the Evidence Agent, then to
  the Critic, and persists everything to the backend incident record (`orchestrator/investigation.py`,
  `backend/app/incident_store.py`). `docs/ARCHITECTURE` page states agents never call each other.
- Gap: the incident record is written by the orchestrator, not read/written by the agents, so it is a log, not a
  blackboard. Peer-to-peer and pub/sub are explicitly listed as "not used" on the presentation page.
- Needed: (a) a real blackboard mode where agents read the shared incident state and post findings/hypotheses to
  it themselves (new orchestrator mode, not a rewrite of the working one); (b) at least one more topology
  (e.g. sequential pipeline or critic-to-specialist direct requests) run on the same scenarios; (c) a measured
  comparison (accuracy, tokens, latency) of hub-and-spoke vs blackboard.

### 2. MCP tools — implemented + tested
- `get_metrics`, `query_logs`, `get_trace`, `get_recent_deployments`, `get_database_stats`, `run_diagnostic`,
  `get_git_diff` in `mcp/tools.py`; 23 MCP tests. Meets "at least two" (custom tools over a real service).
- Optional strengthening: one external-world tool (e.g. a web/docs lookup of a known error) if the reviewer
  reads "external" strictly.

### 3. Pydantic structured output — partially implemented
- Have: structured Findings, hypotheses, critiques and recovery plans, but as dicts built by helper functions
  (`agents/common/finding.py`); Pydantic only validates HTTP bodies in `backend/` and `production/`.
- Needed: Pydantic models for Finding, Hypothesis, Critique, RecoveryPlan and a final `IncidentReport`; validate
  at each A2A boundary and use ADK `output_schema` where tool use allows; export the final report as JSON and
  Markdown (the requirement names both).

### 4. Agentic design patterns, evaluated against others — partially implemented
- Present, undocumented as such: multi-agent routing/triage, parallel fan-out, evidence-first tool use,
  reflection/critic loop, human-in-the-loop approval, bounded loops.
- Gap: no named-pattern write-up and no comparison beyond single-agent baseline and no-critic ablation.
- Needed: a short pattern map, plus a ReAct-style specialist and a plain-planner variant run on the same
  scenarios (this overlaps with #8 and #10).

### 5. Monitoring with callback functions — partially implemented
- Have: `orchestrator/event_bridge.py` emits structured events; `UsageTally` counts model calls.
- Gap: no ADK `before/after_model_callback`, `before/after_tool_callback` or `after_agent_callback`
  (grep finds none); events are emitted by the orchestrator after the fact, so intermediate model/tool errors
  inside an agent are not observed by callbacks.
- Needed: callbacks in `agents/common/diagnostic_agent.py` and `reasoning_agent.py` that record each model call,
  tool call, tool error and latency (and feed #5, #8, #9 at once).

### 6. A2A with framework interoperability — partially implemented
- Have: seven independent A2A services (`a2a-sdk` + ADK `RemoteA2aAgent`), inspectable agent cards, ports
  8101-8107.
- Gap: every agent is ADK. Requirement wants e.g. ADK talking to CrewAI over A2A.

### 7. Use both CrewAI and ADK — not implemented
- No CrewAI dependency, code or test. Do not add a cosmetic wrapper (root rule 2.1).
- Suggested split: keep ADK for the Incident Manager and the four specialists; make the **Root-Cause Critic**
  (or Evidence Agent) a CrewAI agent exposed as an A2A server. The Critic is the best fit: it is
  tool-free, its input/output is already a JSON contract, and an ADK<->CrewAI boundary then sits on the most
  interesting message in the system. Per root `CLAUDE.md` section 9 spirit, run a small spike first (CrewAI
  version, DeepSeek via LiteLLM, A2A server/client support in the pinned CrewAI release) in its own venv
  (`crewai/requirements.txt`) before building.
- Also: requirement says no other agent framework; current stack (ADK + LiteLLM + a2a-sdk) complies.

### 8. Security and prompt variance — partially implemented
- Have: recovery allowlist, risk limits, evidence-based remedy check, human approval, kill switch, budgets
  (`guardrails/`, 56 tests spot-run).
- Gap: nothing screens the incident description or tool/agent outputs for toxic text or prompt injection
  (grep: no `toxic`, no `injection` outside fault injection). Logs and deployment notes are
  attacker-influenced text that the LLM reads, so this is a real exposure, not just a checkbox.
  No type-check of MCP tool returns beyond dict shape. Only one prompt per agent.
- Needed: (a) input guardrail (before-model callback) for abuse/injection on the incident description;
  (b) tool-return validation callback (Pydantic schema, size, and "instruction-like text in logs" flagging);
  (c) a red-team test file with injected log lines; (d) at least two prompt variants per reasoning agent
  (ReAct vs few-shot, or two personas), selectable by env var and recorded in each run.

### 9. Observability: tracing, auditability, provenance — partially implemented
- Have: persistent event log, MCP audit log, evidence items carrying tool/arguments/result, incident
  `agent_messages`.
- Gap: `opentelemetry-api` is pinned but no spans are created or exported; no trace id links an incident across
  orchestrator -> A2A -> agent -> MCP call -> model call; the MCP audit deque is process-local and not reachable
  from the backend (documented limit in `event_bridge.py`).
- Needed: propagate one trace id through A2A metadata and MCP arguments; callbacks (#5) emit spans; export to a
  local collector or Langfuse/Phoenix; show trace id and evidence->hypothesis provenance in the dashboard.

### 10. End-to-end evaluation, cost, running time — partially implemented
- Have: `evaluation/run_experiment.py` with 3 arms (baseline, full, no-critic), scoring, measured token usage.
- Gap (already in PROJECT_STATE): single runs only, no healthy control scenario, no dollar-cost estimate, baseline
  reports no tokens, no prompt-variant arms, results from practice runs are not benchmark data. Recovery calls
  not counted in budget.
- Needed: N repeated trials per scenario and arm, mean/stdev of time, tokens, cost (token price x provider rate,
  labelled as an estimate); arms for prompt variants (#8) and topology (#1); report written from measured
  values only.

### 11. Cloud deployment — not implemented
- `docker-compose.yml` has only `backend` and `production`; agents and orchestrator run as local processes tied
  to local venvs; compose build/up has never been run; CI exists but has not run on GitHub.
- Needed: Dockerfiles for the agent services (one image per dependency set), orchestrator service, dashboard
  build; compose for the whole stack verified locally; then deploy to one cloud (Cloud Run / Azure Container
  Apps / a single VM with compose are the cheapest options) with secrets from the platform, not `.env`.
  Backend currently spawns agents with `taskkill` and local venv paths, which must be replaced by service
  URLs (the real redesign noted in PROJECT_STATE).

## Suggested order (dependencies first)
1. Pydantic models (#3) + ADK callbacks (#5): small, unblock #8, #9, #10.
2. CrewAI Critic spike, then service over A2A (#6, #7): the biggest hard requirement and the biggest risk.
3. Guardrails on input/tool returns + prompt variants (#8).
4. Tracing with a propagated trace id (#9).
5. Blackboard mode and topology comparison (#1, #4).
6. Containerise everything and deploy (#11); benchmark with repeats and cost on the deployed stack (#10).

Risk notes: CrewAI+A2A support in the pinned release is unverified; the Windows-specific process management in
`backend/app/demo.py` must go before cloud deployment; each new arm multiplies paid model calls, so budget the
benchmark (scenarios x arms x repeats) before running it.
