# Agents Local Instructions

## Purpose
NEXUS agent implementations. Phase 4 built the 4 independent diagnostic agents.
Phase 5 exposed each as a real, independent A2A service. Phase 6 added the
Evidence Agent and Root-Cause Critic, same real-A2A-service pattern. Phase 8
added the Recovery Agent, same pattern again but with NO execution capability
of any kind (see `recovery/agent.py` below and `guardrails/CLAUDE.md`).

## Owned
- `common/` — shared infrastructure used by all 4 diagnostic agents:
  - `mcp_connection.py` — `StdioConnectionParams` pointed at the real Phase 3 MCP
    server (`mcp/server.py`), launched with **its own** `.venv-mcp/` interpreter,
    not this folder's venv. Agents never import `mcp/tools.py` directly and never
    call `production/` HTTP endpoints themselves.
  - `finding.py` — builds the Agent Finding object (`docs/API_CONTRACT.md`). The
    `observation`/`interpretation` split is enforced **structurally**: `observation`
    is assembled in Python purely from real MCP tool results; `interpretation` is
    only ever the model's own text. Confidence is parsed from a trailing
    `CONFIDENCE: <0-1>` marker, tolerant of markdown emphasis (`**CONFIDENCE:**
    0.68` — a real model output variant hit during Phase 5 testing).
  - `diagnostic_agent.py` — `DiagnosticAgent` class: builds a real ADK `Agent` with
    `McpToolset` (tool-filtered to that agent's allowlist) and
    `LiteLlm(model=f"groq/{GROQ_MODEL}", include_reasoning=False)`, runs it via
    `InMemoryRunner`, collects real tool call/response pairs from the event stream
    as evidence. Also sets `litellm.num_retries = 5` (see Groq rate-limit note
    below). `build_adk_agent()` is public — reused by both `investigate()` (direct,
    Phase 4) and the A2A server (Phase 5).
  - `usage_tally.py` (2026-10-10) — `UsageTally`: sums the real model calls/tokens
    from an ADK event stream (`event.usage_metadata`, skipping streaming
    partials). Both runners use it and return the result under a `usage` key on
    the Finding / hypotheses / critique / recovery-plan reply; the orchestrator
    strips it before storing (`orchestrator/budget.py`). Measured, never
    estimated; 0 calls reported means the provider sent no usage block.
  - `ports.py` — single source of truth for each agent's A2A port
    (metrics=8101, logs_traces=8102, change_analysis=8103, database=8104).
  - `a2a_server.py` — `DiagnosticAgentExecutor` (a real `a2a.server.agent_execution.
    AgentExecutor`) + `build_a2a_app()`. For every real incoming A2A task, runs the
    SAME `DiagnosticAgent.investigate()` as Phase 4 and returns the resulting
    Finding, JSON-encoded, as the task's completion message.
  - `remote_agent.py` — `build_remote_agent(name, description)` returns a real
    `google.adk.agents.RemoteA2aAgent` client proxy pointed at that agent's real
    Agent Card URL.
  - `callbacks.py` (2026-10-15) — `AgentMonitor`: real ADK callbacks (before/after model, before/after
    tool, tool/model error, after agent) attached in `build_adk_agent(monitor)`. Observe-only (all return
    None). Records keys/sizes/durations, never argument values or results. Summary returns under a
    `monitoring` key; the orchestrator pops it and stores an `AGENT_MONITOR` event. Tested with a scripted
    fake model on the real ADK runner (`tests/test_callbacks.py`, 0 tokens).
  - `guard_callbacks.py` + root `nexus_guard.py` (2026-10-15) — security layer: first user message screened for
    abuse/prompt injection (model never called if blocked); every MCP tool result type-checked, size-bounded and
    stripped of instruction-like text (`[REDACTED: ...]` + `security_flags`). Pattern-based heuristics, one layer among
    several. `NEXUS_GUARDRAILS=0` disables it for A/B runs only. Orchestrator also rejects bad incident descriptions
    (`INPUT_REJECTED`).
  - `prompt_variants.py` — `NEXUS_PROMPT_VARIANT` = default | react | fewshot | persona_sre | persona_auditor. Output
    contract never changes; variants only append to the instruction. Stored in each incident's `run_config`.
  - Contracts: `nexus_models.py` (repo root) holds Pydantic models; every `build_*` function validates its output.
- `metrics/agent.py` + `metrics/a2a_service.py` — Metrics Agent. Tools: `get_metrics`.
- `logs_traces/agent.py` + `logs_traces/a2a_service.py` — Logs & Traces Agent.
  Tools: `query_logs`, `get_trace`.
- `change_analysis/agent.py` + `change_analysis/a2a_service.py` — Change Analysis
  Agent. Tools: `get_recent_deployments`, `get_git_diff`.
- `database/agent.py` + `database/a2a_service.py` — Database Agent. Tools:
  `get_database_stats`.
- `common/reasoning_agent.py` (Phase 6) — `ReasoningAgent`: same Groq/LiteLlm
  build as `DiagnosticAgent` but with **no MCP tools** — used by the Evidence
  Agent and Root-Cause Critic, which only ever reason over structured JSON
  they're handed (real Findings / a real Hypothesis + evidence pool), never
  call a tool themselves. Also owns `extract_json()`, the tolerant fenced/plain
  JSON extractor both agents use to parse the model's structured reply.
- `evidence/agent.py` + `evidence/a2a_service.py` (Phase 6) — Evidence Agent.
  `build_hypotheses()` is the Python-side structural enforcement (mirrors
  `common/finding.py`'s `build_finding()`): assigns every `hypothesis_id`,
  clamps confidence to `[0, 1]`, and — critically — drops any
  `supporting_evidence_ids`/`contradicting_evidence_ids` the model claims that
  don't actually exist in the findings it was given. A model-invented
  evidence_id is never recorded as fact.
- `critic/agent.py` + `critic/a2a_service.py` (Phase 6) — Root-Cause Critic.
  `build_critique()` is the same kind of structural enforcement: an
  unparseable or out-of-enum `verdict` from the model is never trusted —
  it's normalized to `INSUFFICIENT_EVIDENCE`, which keeps the orchestrator's
  re-evaluation loop asking for more evidence instead of silently treating a
  garbled reply as support or contradiction.
- `recovery/agent.py` + `recovery/a2a_service.py` (Phase 8) — Recovery Agent
  (port 8107). `ReasoningAgent`-based like Evidence/Critic (`tools=[]`) --
  has NO MCP tools and NO way to call anything in `production/` itself.
  `build_recovery_plan()` is the structural enforcement: any action not in
  its own local `ACTION_CATALOG` is dropped, an out-of-enum `risk_level`
  falls back to `MEDIUM`, and the action list is capped. This local catalog
  is NOT the authoritative allowlist -- `guardrails/config.py`'s
  `ALLOWED_ACTIONS` is, and `guardrails/policy.py` independently
  re-validates every action from scratch before anything can be approved or
  executed (see `guardrails/CLAUDE.md`). Verified live against a real Groq
  call + real A2A round trip (see `docs/PROJECT_STATE.md` "Phase 8") before
  the account's daily token quota was exhausted.

Each `agent.py` exports `investigate(question: str = <default>) -> dict` (direct,
in-process — Phase 4 path, still works unchanged). Each `a2a_service.py` starts
that SAME agent as its own real A2A server process (Phase 5 path):
`.venv-agents/Scripts/python agents/<name>/a2a_service.py`.

## Critical: Groq/GPT-OSS gotchas
- Every `LiteLlm` instance sets `include_reasoning=False` — see
  `orchestrator/spike/SPIKE_RESULT.md` for why. `diagnostic_agent.py` applies this
  centrally; do not construct a `LiteLlm` anywhere in `agents/` without it.
- Groq's free tier limits `openai/gpt-oss-120b` to 8000 tokens/min, **shared
  across all agents**. A single agent call can trip this when run back-to-back
  with others (Phase 4); 4-way parallel A2A dispatch (Phase 5) trips it more
  easily. `diagnostic_agent.py` sets `litellm.num_retries = 5` to absorb
  transient 429s with backoff — this is a real, observed constraint of the
  current free-tier account, not a code defect. See
  `docs/PROJECT_STATE.md` "Known Issues".

## Dependency isolation
Own venv: `.venv-agents/` at repo root (gitignored), own `requirements.txt`:
`google-adk==2.9.1`, `litellm==1.101.0`, `python-dotenv==1.2.3`, `mcp[cli]==2.2.0`,
`httpx==0.28.1`, `a2a-sdk==1.1.4`, `opentelemetry-api==1.42.1` (pinned down from
what `a2a-sdk` pulls, to match `google-adk`'s own constraint — see Known Issues in
`docs/PROJECT_STATE.md`), `uvicorn==0.53.0`, `starlette==1.6.0`, `pytest==9.1.1`,
`pytest-asyncio==1.4.0`. This venv needs `google-adk`/`litellm` (build the agent),
`mcp` (ADK's `McpToolset` client), AND `a2a-sdk` (ADK's `to_a2a`/`RemoteA2aAgent`).
`orchestrator/`'s venv has `google-adk`/`litellm`/`a2a-sdk` but NOT `mcp` — it
never needs an MCP client, only A2A client access to the 4 agent services.

```bash
python -m venv .venv-agents
.venv-agents/Scripts/python -m pip install -r agents/requirements.txt
```

## Contract
Findings are shaped per `docs/API_CONTRACT.md` "Agent finding schema" — unchanged
by Phase 5; the A2A response body IS this same JSON, just delivered over the real
protocol instead of a direct return value:

```json
{
  "finding_id": "find-<hex8>",
  "agent": "<agent_name>",
  "observation": "<deterministic, code-built summary of which tools ran and whether they succeeded>",
  "source": "<agent_name>",
  "window": {"start": "<iso8601>", "end": "<iso8601>"},
  "evidence": [
    {"evidence_id": "ev-<hex8>", "tool": "...", "arguments": {...}, "result": {...}, "timestamp": "<iso8601>"}
  ],
  "interpretation": "<model's own text, CONFIDENCE line stripped>",
  "confidence": 0.0,
  "limitations": "<string, e.g. 'none noted' or notes about defaults/failures applied>"
}
```

## Rules
Do not access production systems directly — only through `mcp/` (enforced here by
using `McpToolset` exclusively; no agent module imports `httpx`/`mcp/tools.py`/
`mcp/production_client.py`). Do not bypass MCP. Do not mutate external state during
diagnosis (all 7 available MCP tools are read-only). Do not hide state inside
unstructured text — every `investigate()`/A2A call returns the structured Finding
above. **Do NOT call another agent's `investigate()` or import another agent's
module from inside an agent** — that is exactly the "Python function calls
labeled as A2A" the spec forbids. Cross-agent communication only ever happens
through `agents/common/remote_agent.py`'s `RemoteA2aAgent` (real network calls to
a separately-running process) — never a direct import.

## Status
Phase 4 + Phase 5 + Phase 6 (Evidence Agent, Root-Cause Critic) + Phase 8
(Recovery Agent): **implemented + tested**.

## Test
```bash
docker compose up -d production   # or: uvicorn service:app --port 8001 from production/
.venv-agents/Scripts/python -m pytest agents/tests -q
```
33 tests:
- `test_finding.py` — 8 fast unit tests, pure Python, no network.
- `test_evidence_critic.py` (Phase 6) — 13 fast unit tests, pure Python, no
  network: `build_hypotheses`/`build_critique`'s structural enforcement
  (invented evidence_ids dropped, confidence clamped, invalid verdicts
  normalized) and `reasoning_agent.extract_json`'s tolerant JSON parsing.
- `test_recovery.py` (Phase 8) — 6 fast unit tests, pure Python, no network:
  `build_recovery_plan`'s structural enforcement (invented actions dropped,
  invalid risk_level normalized, action list capped).
- `test_agents_integration.py` — 5 real end-to-end tests (direct `investigate()`
  path, Phase 4): real Groq calls + real MCP protocol + real production HTTP.
- `test_a2a.py` — 6 real A2A protocol tests (Phase 5, diagnostic agents only —
  Agent Card accessibility parametrized over the 4 diagnostic agents, a real
  `RemoteA2aAgent` request/response round trip with protocol-level assertions
  (`custom_metadata['a2a:task_id']` etc.), and unique-task-id-per-request).
  **Requires all 4 `agents/*/a2a_service.py` processes running** (see their
  docstrings for exact commands) in addition to `production/`. The Evidence
  Agent's and Root-Cause Critic's real A2A behavior is covered instead by
  `orchestrator/tests/test_investigation_e2e.py` (they carry no MCP tool
  allowlist, so the tool-derived-skill assertions in this file don't apply to
  them — see that test's parametrize scoping).

Real-LLM tests are paced (~8-10s between them) because of the Groq TPM limit
described above — this is an external quota, not a bug.

## Usually inspect
`common/diagnostic_agent.py`, `common/reasoning_agent.py`, `common/finding.py`,
`common/a2a_server.py`, `common/remote_agent.py`, `evidence/agent.py`,
`critic/agent.py`, `docs/API_CONTRACT.md`, `docs/PROJECT_STATE.md`

## Usually don't touch
`backend/`, `production/`, `orchestrator/`, `mcp/` (separate verified components,
separate venvs)

## Prompt changes 2026-10-13
- Critic: an EVIDENCE LIMITS paragraph (only metrics, logs with error text, request traces without child spans, change
  history and DB stats can exist; do not ask for anything else; SUPPORTED when sources agree and nothing contradicts).
- Logs & Traces: at most 4 tool calls, no repeated calls, quote error text exactly.
- Tuned after failures on the five known scenarios; re-measure on held-out scenarios before claiming accuracy.