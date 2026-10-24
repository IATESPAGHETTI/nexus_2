# NEXUS API Contract

## Backend HTTP API (Phase 1 slice — will grow)

`backend/` exposes the persistence + control API. Dashboard and orchestrator are clients.

### `GET /health`

Liveness check for the NEXUS backend itself.

```json
{ "status": "ok", "service": "nexus-backend" }
```

### Incident state + event store — implemented (Phase 6)

Real, durable persistence (SQLite; survives a backend restart) — `backend/app/incident_store.py`.
The database file is `NEXUS_DB_PATH` (default `backend/.data/nexus.db`; docker-compose mounts a
volume at `/data`; `:memory:` disables persistence and is what the test suite uses). It was
in-memory only until 2026-10-10. Called for real by `orchestrator/event_bridge.py` during a live
investigation, not just by tests.

```text
POST /incidents                 {"description": str} -> full initial incident state
GET  /incidents/{id}            full incident state (404 if unknown)
POST /incidents/{id}/state      partial field merge (any subset of the incident-state
                                 fields below) -> full updated incident state (404 if unknown)
POST /incidents/{id}/events     {"event_type", "source", "target"?, "status"?, "payload"?}
                                 -> the created event (see docs/EVENT_SCHEMA.md envelope),
                                 also appended to the incident's timeline (404 if unknown)
GET  /incidents/{id}/events     {"events": [...]} in emission order (404 if unknown)
POST /incidents/{id}/approve    {"decision": "APPROVED"|"REJECTED", "approved_by": str}
                                 -> full updated incident state (404 if unknown, 400 if
                                 decision is not one of the two values). Persistence
                                 only (backend/CLAUDE.md "no business logic here") --
                                 records a real human decision made outside this
                                 process; also appends a HUMAN_APPROVAL_GRANTED or
                                 HUMAN_APPROVAL_REJECTED event. Implemented Phase 8.
```

Incident state shape (root CLAUDE.md section 15):

```json
{
  "incident_id": "INC-d81b1a61",
  "description": "...",
  "status": "INVESTIGATING | DIAGNOSED | ABSTAINED",
  "created_at": "...", "updated_at": "...",
  "timeline": [{"event_id", "timestamp", "event_type", "source", "target"}],
  "evidence": {}, "agent_findings": {"<agent_name>": {"...Finding..."}},
  "agent_messages": {"<agent_name>": {"task_id", "context_id"}},
  "hypotheses": [{"...Hypothesis..."}],
  "critic_results": [{"...Critique..."}],
  "experiments": [],
  "recovery_plan": {"plan_id", "hypothesis_id", "actions": [{"action", "params", "rationale"}],
                     "risk_level": "LOW | MEDIUM | HIGH", "blast_radius", "rollback_plan",
                     "status": "PROPOSED", "dropped_invalid_actions", "created_at"} | null,
  "approval_state": {"decision": "PENDING | APPROVED | REJECTED | EXPIRED | NOT_REQUESTED",
                      "approved_by"?, "decided_at"?, "requested_at"?} | null,
  "action_history": [{"action", "params", "status": "EXECUTED | FAILED | SKIPPED_KILL_SWITCH",
                       "detail", "timestamp"}],
  "token_usage": {},
  "decision": {"outcome": "DIAGNOSED | ABSTAINED | RESOLVED", "reason": "...", "loops_used": 1, "max_loops": 3}
}
```

Phase 8 (implemented): `POST /incidents/{id}/approve` above is the human
approval gate. `recovery_plan`/`approval_state`/`action_history` are filled
in for real by `orchestrator/recovery.py` (via `event_bridge.update_state`)
once an incident reaches `DIAGNOSED` — see "Recovery flow" below.

### Recovery flow — implemented (Phase 8)

`orchestrator/recovery.py`'s `run_recovery(incident_id, hypothesis, critique,
evidence_pool)`, called automatically by `orchestrator/investigation.py`
right after a `DIAGNOSED` decision (unless `trigger_recovery=False`):

```text
1. Recovery Agent (real A2A, agents/recovery/) proposes a RecoveryPlan from
   the hypothesis + critique + real evidence_pool (the same flattened MCP
   evidence the critic saw -- the agent's only real source for a concrete
   target_version). The Recovery Agent has NO MCP tools and NO execution
   capability -- it can only emit a JSON proposal.
2. guardrails/policy.py's validate_plan() independently re-validates every
   action against guardrails/config.py's ALLOWED_ACTIONS (own authoritative
   allowlist, never trusting the agent's own catalog) -- REJECTED stops here.
3. approval_state -> PENDING, HUMAN_APPROVAL_REQUESTED emitted. Polls
   backend/ for a real POST /incidents/{id}/approve, up to
   MAX_APPROVAL_WAIT_SECONDS (env var, default 120) -- REJECTED or EXPIRED
   stops here.
4. guardrails/executor.py's execute_plan() runs each allowlisted action in
   order via bounded HTTP calls to production/'s admin endpoints below,
   re-checking a file-based kill switch (guardrails/kill_switch.py) before
   EVERY action.
5. Verification: a real second A2A call to the Metrics Agent; VERIFIED only
   if the resulting error-rate evidence is below threshold -- never forced.
6. RESOLVED only on verified success; every other branch leaves the incident
   at DIAGNOSED with the failure reason recorded in the returned outcome.
```

The 4 allowlisted recovery actions (`guardrails/config.py`'s
`ALLOWED_ACTIONS`): `restart_service` (no params), `rollback_deployment`
(params: `target_version`), `reset_config` (no params), `scale_resources`
(no params) -- each bound to exactly one `production/` admin endpoint below.

## Production (simulated) HTTP API — `production/`, separate service, port 8001

Real observability data from real requests against a seeded in-memory SQLite DB.
See `production/CLAUDE.md` for ownership. Every request also gets an `X-Trace-Id`
response header.

```text
GET  /                     {"status": "ok", "service": "nexus-production"}
GET  /health                same shape as /
GET  /metrics               {"request_count", "error_count", "by_endpoint": {...}}
GET  /logs?limit=N          {"entries": [{timestamp, level, trace_id, method, path,
                              status_code, duration_ms}, ...]}
GET  /traces?limit=N        {"traces": [{trace_id, timestamp, method, path,
                              status_code, duration_ms}, ...]}
GET  /traces/{trace_id}     single trace object (404 if unknown)
GET  /changes?limit=N       {"changes": [{change_id, type, version, deployed_at,
                              description, author}, ...]}, newest first
GET  /db/diagnostics        {"engine", "table_row_counts", "orders_by_status",
                              "recent_queries", "query_summary"}
GET  /orders                {"orders": [{id, customer, amount, status, created_at}]}
GET  /orders/{id}           single order (404 if unknown)
```

### Admin endpoints — implemented (Phase 8/9), mutating

Unlike every endpoint above, these actually change `production/state.py`'s
mutable fault state — genuinely degrading/restoring real request behavior,
not a fabricated flag. Only `fault_injection/injector.py` and
`guardrails/production_client.py` are expected to ever call these; no
diagnostic/evidence/critic/recovery agent calls them directly.

```text
GET  /admin/state                                real current fault-state snapshot
POST /admin/fault/inject   {"fault_type", "bad_version"?}   fault_injection/ only
POST /admin/fault/clear                          fault_injection/ only (faults only)
POST /admin/reset                                demo/test reset: clears faults AND the shop's history of earlier incidents
                                                 (metrics, logs, traces, queries, extra change entries, orders above id 10)
POST /admin/recovery/restart_service             guardrails/ only
POST /admin/recovery/rollback_deployment {"target_version"} guardrails/ only
POST /admin/recovery/reset_config                guardrails/ only
POST /admin/recovery/scale_resources             guardrails/ only
```

**Log entries carry the app's error message (2026-10-13).** A 5xx entry from `GET /logs` has an extra
`error` field with the exception text the app raised (for example `ConfigError: DB_POOL_SIZE must be > 0,
got 0`). Healthy and 4xx entries have no `error` field. Without it no agent could tell why requests failed.

`fault_type` is one of `production/state.py`'s `FAULT_TYPES`: `bad_deployment`,
`db_slowdown`, `config_error`, `dependency_failure`, `resource_exhaustion` —
the 5 minimum failure classes from `docs/EVALUATION.md`. Each produces a real,
distinct, observable symptom through the existing read-only endpoints above
(elevated error rate, elevated latency, or both) — see
`fault_injection/scenarios.py`'s `expected_symptoms` for the exact signature
of each.

## MCP diagnostic tools — `mcp/`, real MCP server (stdio transport)

Implemented and tested (Phase 3). See `mcp/CLAUDE.md` for ownership. All 7 tools
return `{"ok": bool, ...}` and never raise to the caller.

```text
get_metrics()
  -> {"ok", "request_count", "error_count", "by_endpoint"}          [wraps GET /metrics]

query_logs(level: "INFO"|"ERROR"|None = None, limit: int = 50)
  -> {"ok", "entries", "count"}                                     [wraps GET /logs, client-side level filter]

get_trace(trace_id: str|None = None, limit: int = 20)
  -> {"ok", "trace"} if trace_id given, else {"ok", "traces"}        [wraps GET /traces[/{id}]]

get_recent_deployments(limit: int = 20)
  -> {"ok", "changes"}                                               [wraps GET /changes]

get_git_diff(paths: list[str]|None = None, max_commits: int = 5)
  -> {"ok", "paths", "commit_history_available", "commit_log_diff",
      "commit_log_truncated", "uncommitted_changes_stat",
      "staged_changes_stat"}
     paths restricted to {"production", "backend", "mcp", "docs"} — real `git log -p`
     / `git diff` on the NEXUS repo itself, not the production HTTP API.

get_database_stats()
  -> {"ok", "engine", "table_row_counts", "orders_by_status",
      "recent_queries", "query_summary"}                             [wraps GET /db/diagnostics]

run_diagnostic(name: "connectivity_check"|"error_rate_check"|"order_status_check")
  -> {"ok", "diagnostic", ...fields depend on name}
     name is validated against a fixed allowlist — never arbitrary code/SQL/shell.
```

These are the endpoints Phase 3's MCP tools wrap (metrics tool -> `/metrics`,
logs/traces tool -> `/logs` + `/traces`, change-analysis tool -> `/changes`, database
tool -> `/db/diagnostics`). `get_git_diff` is the one exception — its evidence
source is this repo's own git history, not a production HTTP endpoint (see
`mcp/git_diff_tool.py`).

Planned (not yet implemented — add here when built, keep this file in sync):

```text
GET  /incidents/{id}/events     currently poll-only; SSE/websocket streaming for
                                 the live dashboard is a future phase
GET  /incidents                 list endpoint, deliberately deferred (Phase 7 decision)
```

## A2A protocol — implemented (Phase 5)

Real [Agent2Agent](https://a2a-protocol.org/) protocol, `a2a-sdk==1.1.4`, via
`google.adk.a2a.utils.agent_to_a2a.to_a2a()` (server) and
`google.adk.agents.RemoteA2aAgent` (client). Not a custom JSON envelope — this
section documents the real shapes as observed, not an illustrative design.

### Topology

```text
agents/metrics/a2a_service.py          -> own process, http://127.0.0.1:8101
agents/logs_traces/a2a_service.py      -> own process, http://127.0.0.1:8102
agents/change_analysis/a2a_service.py  -> own process, http://127.0.0.1:8103
agents/database/a2a_service.py         -> own process, http://127.0.0.1:8104
agents/evidence/a2a_service.py         -> own process, http://127.0.0.1:8105 (Phase 6)
agents/critic/a2a_service.py           -> own process, http://127.0.0.1:8106 (Phase 6)
agents/recovery/a2a_service.py         -> own process, http://127.0.0.1:8107 (Phase 8)
orchestrator/incident_manager.py       -> A2A client only (RemoteA2aAgent x4,
                                           diagnostic agents, Phase 5)
orchestrator/investigation.py          -> A2A client only (RemoteA2aAgent to
                                           evidence_agent + root_cause_critic
                                           via remote_call.py, Phase 6)
orchestrator/recovery.py               -> A2A client only (RemoteA2aAgent to
                                           recovery_agent + metrics_agent
                                           (post-recovery verification) via
                                           remote_call.py, Phase 8)
```

The Evidence Agent, Root-Cause Critic, and Recovery Agent are served by the
exact same `agents/common/a2a_server.py` (`DiagnosticAgentExecutor`/
`build_a2a_app`) as the 4 diagnostic agents — they carry no MCP tools (see
`agents/common/reasoning_agent.py`), but are otherwise indistinguishable at
the protocol level: real Agent Cards, real Task lifecycle, real JSON-RPC. The
Recovery Agent additionally has no execution capability of any kind —
`agents/recovery/agent.py`'s `ACTION_CATALOG` only names actions in prompt
text; nothing in `agents/` ever calls a mutating endpoint.

Ports: `agents/common/ports.py`. Each service is `mcp/server.py`'s diagnostic
agent (unchanged from Phase 4) wrapped by `to_a2a()`.

### Agent Card

`GET http://127.0.0.1:<port>/.well-known/agent-card.json` — auto-built by ADK's
`AgentCardBuilder` from the agent's name/description/tools. Real example
(metrics agent):

```json
{
  "name": "metrics_agent",
  "description": "NEXUS diagnostic agent: investigates request metrics (counts, error rates, p99 latency) via MCP get_metrics.",
  "supportedInterfaces": [{ "url": "http://127.0.0.1:8101", "protocolBinding": "JSONRPC", "protocolVersion": "1.0" }],
  "capabilities": { "streaming": true },
  "skills": [
    { "id": "metrics_agent", "name": "model", "description": "...", "tags": ["llm"] },
    { "id": "metrics_agent-get_metrics", "name": "get_metrics", "description": "Request counts, error counts, and latency (avg/p99) per endpoint...", "tags": ["llm", "tools"] }
  ]
}
```

### Request/response flow

1. `RemoteA2aAgent` (client, in `orchestrator/incident_manager.py` or any test)
   sends a real A2A `Message` (role `ROLE_USER`) to the target service's JSON-RPC
   endpoint.
2. The service's `DiagnosticAgentExecutor` (`agents/common/a2a_server.py`)
   receives it via a real `a2a.server.agent_execution.RequestContext`, enqueues a
   `Task` (state `TASK_STATE_SUBMITTED` -> `TASK_STATE_WORKING`), runs the SAME
   `DiagnosticAgent.investigate()` used in Phase 4 (real MCP tool calls, real
   Groq/GPT-OSS-120B reasoning), and completes the task (state
   `TASK_STATE_COMPLETED`) with an agent `Message` whose text is the JSON-encoded
   Finding (see schema below).
3. The client's ADK `Event` carries `custom_metadata` proving the protocol hop
   actually happened — real example:

```json
{
  "a2a:task_id": "8b0932b3-4e08-458a-9690-94c68a1235f3",
  "a2a:context_id": "dbdf0dde-bcf9-47db-b7fe-a0723fd5a4a1",
  "a2a:request": { "messageId": "...", "role": "ROLE_USER", "parts": [{ "text": "Summarize current request metrics." }] },
  "a2a:response": { "id": "8b0932b3-...", "status": { "state": "TASK_STATE_COMPLETED", "message": { "role": "ROLE_AGENT", "parts": [{ "text": "{\"finding_id\": \"find-f446f278\", ...}" }] } } }
}
```

### Parallel dispatch (Incident Manager)

`orchestrator/incident_manager.investigate_incident(text, agent_names=None)`
builds an ADK `ParallelAgent` whose `sub_agents` are `RemoteA2aAgent` proxies for
each named diagnostic agent (all 4 by default) and runs it once — ADK's
`ParallelAgent` invokes all sub-agents concurrently, so all 4 real A2A requests
are in flight at once, each with its own `task_id`/`context_id`. Returns
`{"findings": {agent_name: Finding}, "a2a": {agent_name: {task_id, context_id}}, "agents_dispatched": [...], "agents_responded": [...]}`.

### Known constraint: Groq free-tier TPM rate limit

Groq's `openai/gpt-oss-120b` free tier is limited to 8000 tokens/min, shared
across all 4 agents. A 4-way parallel burst can trip a real `RateLimitError`.
`agents/common/diagnostic_agent.py` sets `litellm.num_retries = 5` so transient
429s are retried with backoff rather than failing the dispatch — see
`docs/PROJECT_STATE.md` "Known Issues" for the observed failure/fix.

## Agent finding schema — implemented (Phase 4), `agents/common/finding.py`

Every diagnostic agent (`agents/metrics`, `agents/logs_traces`, `agents/change_analysis`,
`agents/database`) returns findings shaped like (real example, not illustrative):

```json
{
  "finding_id": "find-28fc189c",
  "agent": "database_agent",
  "observation": "get_database_stats({}) -> ok=True, fields=['engine', 'table_row_counts', 'orders_by_status', 'recent_queries', 'query_summary']",
  "source": "database_agent",
  "window": { "start": "2026-09-18T09:37:18Z", "end": "2026-09-18T09:37:26Z" },
  "evidence": [
    {
      "evidence_id": "ev-75f02cbd",
      "tool": "get_database_stats",
      "arguments": {},
      "result": { "ok": true, "table_row_counts": { "orders": 10 }, "...": "..." },
      "timestamp": "2026-09-18T09:37:26Z"
    }
  ],
  "interpretation": "The database contains a single orders table with only 10 rows...",
  "confidence": 0.97,
  "limitations": "none noted"
}
```

`finding_id` and each `evidence[].evidence_id` are unique per call. `observation`
is built **in Python**, purely from the raw MCP tool result(s) — never from the
model — so a guess can never be silently recorded as a fact; `interpretation` is
the model's own text (with a trailing `CONFIDENCE: <0-1>` line stripped out into
the `confidence` field). If the model didn't report a parseable confidence, a
conservative default (0.3) is used and noted in `limitations`.

**`usage` (added 2026-10-10)**: on the wire, every agent reply (Finding, Evidence
Agent `{hypotheses}`, Critic critique, Recovery `{recovery_plan}`) also carries
`"usage": {"llm_calls", "prompt_tokens", "completion_tokens", "total_tokens"}` —
the real model usage that task incurred (`agents/common/usage_tally.py`). It is
bookkeeping, not evidence: `orchestrator/investigation.py` pops it before the reply
is stored or forwarded. The orchestrator aggregates it into the incident's
`token_usage`:

```json
{
  "measured_by": "NEXUS, from the model usage each agent reported",
  "total": {"llm_calls": 12, "prompt_tokens": 30000, "completion_tokens": 2000, "total_tokens": 32000},
  "by_agent": {"metrics_agent": {"llm_calls": 2, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "tasks": 1}},
  "unmeasured_tasks": 0,
  "limits": {"max_llm_calls": 60, "max_total_tokens": 250000, "max_tokens_per_agent": 80000},
  "budget_exceeded": null
}
```

(numbers illustrative). `budget_exceeded` is a reason string once a limit is
reached, at which point the investigation abstains. Provider quota is not part of it.

## Hypothesis schema — implemented (Phase 6), `agents/evidence/agent.py`

Produced by the Evidence Agent's `build_hypotheses()` from the diagnostic
agents' real Findings (real example, not illustrative):

```json
{
  "hypothesis_id": "H1",
  "statement": "The database is the primary bottleneck for checkout latency.",
  "supporting_evidence_ids": ["ev-75f02cbd"],
  "contradicting_evidence_ids": [],
  "confidence": 0.8,
  "missing_evidence": ["trace correlation for request X"],
  "requested_next_investigation": "logs_traces_agent: pull traces for window W",
  "status": "PROPOSED",
  "revision": 1,
  "created_at": "2026-09-18T09:37:26Z",
  "dropped_invented_evidence_ids": 0
}
```

`status` in `{PROPOSED, UNDER_REVIEW, CHALLENGED, NEEDS_EVIDENCE, SUPPORTED, REJECTED, ABSTAINED}`
— transitioned only by `orchestrator/investigation.py`'s re-evaluation loop,
never by the Evidence Agent itself (which only ever proposes at `PROPOSED`).
`hypothesis_id` is always assigned in Python (`H1`, `H2`, ... by descending
confidence), never trusted from the model. `supporting_evidence_ids`/
`contradicting_evidence_ids` are filtered to ids that actually exist in the
input Findings — an invented id is dropped and counted in
`dropped_invented_evidence_ids`, never recorded as fact.

## Critique schema — implemented (Phase 6), `agents/critic/agent.py`

Produced by the Root-Cause Critic's `build_critique()` for a single hypothesis
under review (real example):

```json
{
  "critique_id": "crit-3fa1c9d2",
  "hypothesis_id": "H1",
  "verdict": "SUPPORTED",
  "contradictions": [],
  "unsupported_assumptions": [],
  "alternative_explanations": ["A slow downstream payment API could also explain the latency."],
  "requested_evidence": [],
  "rationale": "The database diagnostics show elevated query times consistent with the hypothesis, and no evidence in the pool contradicts it.",
  "evidence_pool_size": 3,
  "timestamp": "2026-09-18T09:41:02Z"
}
```

`verdict` in `{SUPPORTED, CONTRADICTED, INSUFFICIENT_EVIDENCE, REQUEST_MORE_EVIDENCE, ABSTAIN}`.
An unparseable or out-of-enum verdict from the model is never trusted at face
value — `build_critique()` normalizes it to `INSUFFICIENT_EVIDENCE`, which
keeps `orchestrator/investigation.py`'s loop asking for more evidence rather
than silently treating a garbled reply as support or contradiction.

## Re-evaluation loop — implemented (Phase 6), `orchestrator/investigation.py`

`run_investigation(incident_description, agent_names=None, max_loops=None) -> dict`
returns the final persisted incident state (fetched back from `backend/`, not
an in-memory copy). Bounded by `MAX_REEVALUATION_LOOPS` (env var, default 3;
root CLAUDE.md section 8/14) — the loop can only ever end in `DIAGNOSED` or
`ABSTAINED`, never left hanging or forced to a diagnosis. See
`orchestrator/CLAUDE.md` for the exact per-verdict transitions and
`docs/EVENT_SCHEMA.md` for every event type this loop emits.


## Simulated shop additions (2026-10-12): storefront, catalog, checkout

```text
GET  /shop        HTML storefront (production/storefront.html) -- for people, not agents
GET  /products    {"products": [{"id","name","price","emoji","blurb"}, ...]}   static, not DB-backed
POST /orders      {"customer": str(1-40), "items": [{"product_id": int, "quantity": 1-10}] (1-10 items)}
                  -> 201 {"order": {id, customer, amount, status, created_at}, "items": [...]}
                  400 unknown product_id, 422 invalid body. Amount is computed from the catalog; any
                  client-supplied price is ignored.
```
`POST /orders` goes through the same fault checks as `GET /orders` (config_error -> deterministic 500,
bad_deployment -> ~35% 500) and the same database path (db_slowdown adds ~0.25 s to the INSERT, and the
INSERT appears in `/db/diagnostics` `recent_queries`/`query_summary`). All of these requests are recorded as
ordinary customer traffic in `/metrics`, `/logs`, `/traces`; `/admin/*` still is not.

### Demo endpoints added 2026-10-13 (backend)

```text
POST /demo/reset-shop     proxies the shop's POST /admin/reset; the dashboard calls it before every injection
POST /demo/investigate    {fault_type, description}; the description is the symptom the agents receive
```
The Incident Manager's triage reads that symptom text to choose which diagnostic agents to call (see
`orchestrator/triage.py`), so different failures wake different agents.

## Pydantic contracts and final report — implemented (2026-10-15)

`nexus_models.py` (repo root) defines `Finding`, `Hypothesis`, `Critique`, `RecoveryPlan` (extra fields allowed)
and `IncidentReport`. The agent builders validate against them (a broken object raises `ValidationError` in the
agent instead of travelling over A2A). At the end of every investigation `orchestrator/investigation.py::attach_report`
stores `incident.report` = `IncidentReport` fields + `markdown` (a Markdown rendering). Fail-soft: a reporting
error never changes the outcome. Fields: incident_id, description, outcome, reason, root_cause,
root_cause_confidence, supporting_evidence[{evidence_id, tool, agent}], critic_verdict, critic_rationale,
rejected_hypotheses, recovery_actions, approval, loops_used, total_tokens, llm_calls.
