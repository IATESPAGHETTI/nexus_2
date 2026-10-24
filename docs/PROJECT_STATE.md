# NEXUS Project State

## Course minimum-requirements review (2026-10-15)
- Gap analysis of the 11 course requirements: `docs/REVIEW_GAP_ANALYSIS.md` (review only, no code changed, nothing run).
- Result: MCP tools met; CrewAI (req. 7) and cloud deployment (req. 11) not started; blackboard, Pydantic models,
  ADK callbacks, input guardrails, prompt variants, tracing and repeated-run cost evaluation are partial or missing.
- Next action: CrewAI Critic spike over A2A (req. 6/7), then input guardrails + prompt variants.

## Gemini key rotation in the experiment runner (2026-10-18) — implemented + tested with fake keys; NOT yet used live
- `evaluation/run_matrix.py::KeyRing`: when the provider is Gemini and `GEMINI_API_KEY_2` (and `_3`) exist in `.env`, three empty runs in a row switch to the next key, restart the agents
  on it (they read the key at start-up) and REDO the empty runs; empty runs that were not redone are recorded as invalid. Key values are never printed. Owner's decision (college project);
  Google's free-tier terms may restrict using several projects to get around quotas, so this is the owner's risk. Results must still name one model and one provider.

## Held-out run, PARTIAL (2026-10-18) — see docs/EVALUATION_RESULTS_HOLDOUT.md
- 52 valid runs, 5 arms, Gemini `gemini-3.5-flash-lite`. Free tier = 15 requests/min AND 500/day/model: the run hit the daily cap; 13 empty runs removed (raw kept).
  Runner now also treats zero-token runs as invalid and stops after 3 in a row. `hub_analysis_tools` and `hub_crewai_both` were not run yet; resume command in the results file.
- Partial finding (n=1-2 per cell, NOT significant): baseline 11/11; multi-agent arms 56-70%. The healthy control looked like a failure for all multi-agent arms; that was a SCORER bug (hypotheses said "operating normally" and were read as a database fault). Fixed (`healthy` class), all stored runs re-scored: control 100%. The DeepSeek 144-run set was re-scored too (only hub_persona_sre false diagnoses 13% -> 7%).

## Held-out scenarios + rate-limit-aware runner (2026-10-18) — implemented + tested; NOT yet run
- `fault_injection/scenarios.py::HOLDOUT_SCENARIOS` (8) + `HOLDOUT_CONTROLS` (1): the five faults described in NEW customer wording, and three TWO-FAULT combinations
  (db+dependency, deploy+db, resource+dependency; the shop's fault flags are independent, verified live). Truth `"a|b"` accepts either injected cause
  (`scoring.score_run`). `injector.inject` posts every fault of a scenario. Symptoms are tested to be new and not to name causes.
- Rule: run them with prompts, triage rules and scorer FROZEN and record the commit; they exist because the core five were tuned on. `run_matrix.py --set core|holdout|all`.
- Runner now detects runs whose agents reported errors (e.g. provider 429s), retries after a pause (`--retries`, `--retry-wait`), and marks still-failing runs `invalid`:
  excluded from accuracy and shown as "Runs (invalid)". Without this a rate-limited run would look like an abstention.
- Provider rule: any results must say which model produced them; do not mix providers in one table.

## A2A interoperability limit found (2026-10-18)
- ADK 2.9.1 agents publish A2A 1.0 style agent cards (`supportedInterfaces`). The CrewAI environment's `a2a-sdk` 0.3.26 client cannot parse them (`url` field required), so
  a CrewAI agent cannot call an ADK agent directly with the versions CrewAI 1.15.28 pins. ADK -> CrewAI works (ADK's client reads both card formats; verified live and in tests).
- Consequence: the planned "CrewAI critic asks an ADK specialist directly" (peer-to-peer) was NOT built. Workarounds (a second legacy card on the ADK side, or a hand-written
  JSON-RPC client) were rejected: they would re-implement the protocol instead of using the SDK. A2A is bidirectional only in the sense that both frameworks serve and are called over A2A.

## OpenTelemetry export + trace timing + light incident view (2026-10-18)
- `nexus_otlp.py`: converts the stored span tree to OTLP/HTTP JSON (one service per agent + `nexus-orchestrator`, real trace id, parent links, error status) and POSTs it to
  `NEXUS_OTLP_ENDPOINT` after each investigation (`TRACE_EXPORTED` event, fail-soft). Plain JSON over HTTP, so no OpenTelemetry SDK (its pins conflict with the ADK stack).
  Tested against a throwaway local collector (`tests/test_nexus_otlp.py`, 6 tests). Verified in real Jaeger 1.62 (2026-10-19): a stored 21-span investigation trace (hub_crewai_both) was exported and read back from Jaeger's API under its own trace id, 5 services. `NEXUS_OTLP_ENDPOINT` is the FULL URL, e.g. `http://jaeger:4318/v1/traces`.
- Trace timing: agents now record their own wall-clock start/end (`started_unix`/`finished_unix` in `AgentMonitor.summary`), so spans are placed correctly even in the
  pipeline (before, every agent was placed at the time its trace event was written). Older incidents fall back to event time minus duration. Times are good to ~1 s at the root.
- Dashboard: the incident ("Mission Control" detail) view was a black shell on a light site (user complaint: "it sucks, it's just black"); it now uses the light theme
  (`.nx-light` token overrides in `styles/global.css`, light header and body). Checked in the browser: no dark blocks, no white-on-white text.
- Dashboard timeline (Audit panel): one bar per agent placed by its real clock. Live pipeline run (Gemini): Metrics 3.5-7.6 s, then Logs and Database both start at 7.9 s, then Evidence 14.2 s, Critic 16.7 s.
- Note: the backend can only stop agents it started itself; after changing agent code, stop them by port (8101-8107) or they keep running the old code.

## Pipeline topology + board view (2026-10-18) — implemented + tested; verified live on Gemini (NOT yet measured against hub/blackboard)
- `NEXUS_TOPOLOGY=pipeline` (third topology): the Metrics agent runs FIRST and alone (where/when); the other selected specialists then run in parallel over the shared
  board, each told what Metrics found (`HANDOFF from the metrics_agent ...`, built from its own interpretation, bounded to 900 chars and passed through the injection
  redactor because it is model output travelling to another model). `HANDOFF` event; falls back to the plain blackboard without Metrics or with one agent.
- Tests: `orchestrator/tests/test_pipeline.py` (5, board transport mocked). Live (Gemini, db_slowdown): bb-3 metrics finding -> bb-4 hand-off request -> bb-5/6 database + logs findings,
  DIAGNOSED in 16 s, 12 calls, 48k tokens.
- Dashboard: the Audit panel narrates every board entry (description, who was asked, finding + confidence, hand-off, hypotheses, verdict).
- New matrix arms ready (not run): `pipeline`, `hub_analysis_tools`, `hub_crewai_both`.
- Dashboard nav link renamed Overview -> Mission Control (user could not find "Mission Control" on the main page).

## Second MCP server (2026-10-18) — implemented + tested; verified live on Gemini
- `mcp/analysis_server.py`: runbook file parser, safe calculator, latency step-change statistics tool (9 MCP tools across 2 independent servers). Tests: 32 unit + 2 real-protocol.
- Behind `NEXUS_ENABLE_ANALYSIS_TOOLS=1` (default OFF so the measured baseline is unchanged). Live (Gemini, db_slowdown): Metrics agent called `detect_latency_step`
  (35 requests, step found) and `evaluate_expression`; DIAGNOSED in 12 s, 12 calls, 39.5k tokens. The runbook tool was not used in that run.
- Not measured: whether these tools change accuracy; they need their own matrix arm (week 4).

## CrewAI: Crew/Task, callbacks, second agent (2026-10-18) — implemented + tested; verified live on Gemini
- The CrewAI Critic and a NEW CrewAI Evidence Agent now use real `Agent` + `Task` + `Crew` (`crewai_critic/crewai_common.py`), with `step_callback` /
  `task_callback` writing into the same `AgentMonitor` as the ADK callbacks and token usage measured from `Crew.token_usage` (the earlier "0 tokens for the CrewAI
  critic" gap is closed). Provider-aware (deepseek | gemini | groq). Evidence logic split into ADK-free `agents/evidence/evidence_core.py` (shared contract).
- Select with `NEXUS_EVIDENCE_FRAMEWORK=crewai` / `NEXUS_CRITIC_FRAMEWORK=crewai` (backend launcher, experiment stack, compose `--profile crewai`); `run_config` records both.
- Tests: crewai_critic 8, orchestrator ADK->CrewAI over A2A for critic AND evidence (stub, trace id propagated). Live: ADK specialists + CrewAI evidence + CrewAI critic -> DIAGNOSED in 20 s.
- Limit: CrewAI `step_callback` only fires on tool steps; these agents use no tools.

## Report tables + download (2026-10-18) — implemented + tested; verified live on Gemini
- `IncidentReport` now carries a Summary TABLE (14 rows: symptom, outcome, root cause, confidence, critic verdict, loops, agents, evidence count,
  calls/tokens, duration, topology/prompt/critic, recovery, approval), a Hypotheses table and an Agents table, plus `trace_id`, `duration_seconds`.
- `GET /incidents/{id}/report?format=md|json` (backend), a Download button + tables in the dashboard's Audit panel.
- Decision: agents keep validating their output against Pydantic models after parsing; ADK `output_schema` was NOT adopted because structured-output
  support differs across DeepSeek/Gemini/Groq and would change behaviour for every provider.
- Found: the CrewAI critic reports 0 tokens (CrewAI `usage_metrics` is empty), so CrewAI-arm cost is under-reported. To fix in the CrewAI step.

## Guard hardening + red-team suite (2026-10-18) — implemented + tested (0 tokens)
- `nexus_guard.py` now normalises text before matching (NFKC, zero-width, look-alike letters, leetspeak, split letters, URL/HTML/hex/base64/rot13) and
  matches a categorised catalogue (override, leak, role, delimiter, tool_hijack, exfil) in English plus 8 other languages; abuse list extended
  (plurals, romanised Hindi/Spanish/French/German).
- `tests/redteam_corpus.py` + `tests/test_redteam.py` (209 checks) + `docs/REDTEAM_RESULTS.md`. HONEST NUMBERS: first pass on 30 unseen attacks = 21/30 (70%);
  after generalising 30/30 but no longer independent; the 14 "hard" paraphrases are all missed by design; 0 false positives on 79 benign texts.
- Still heuristic, not a proof of safety.

## Gemini free-tier test (2026-10-18) — one live investigation, NOT a benchmark
- Purpose: avoid DeepSeek spend while developing. `NEXUS_LLM_PROVIDER=gemini` works end to end through ADK + LiteLLM (tool calling over MCP, A2A, critic).
- `gemini-2.5-flash` (the old default) returns 404 for new accounts; the key can use `gemini-3.x` models. `gemini-3.8-flash` is a thinking model limited
  to 5 requests/min on the free tier: the first investigation abstained because agents hit HTTP 429 after LiteLLM's retries. `gemini-3.5-flash-lite` (and
  `gemini-3.1-flash-lite`) took 14 rapid calls without limiting. Default changed to `gemini-3.5-flash-lite`.
- Result on `gemini-3.5-flash-lite` (db_slowdown, hub, ADK critic): DIAGNOSED in ~20 s, 10 model calls, 31.4k tokens, 6 agents, no errors, recovery plan pending
  approval (not clicked). Cost $0 (free tier). One run only: it says the pipeline works with this provider, not that accuracy is comparable to DeepSeek.
- Rules: results must name the provider/model; do not mix providers in one comparison; free-tier prompts may be used by Google for training (nothing sensitive is sent);
  daily quotas were not measured.

## Azure deployment + experiment matrix results (2026-10-16)
- **Azure for Students VM is LIVE**: `Standard_B2as_v2` (2 vCPU, 8 GB) in Central India, Docker Compose full stack + Caddy HTTPS
  (`deploy/AZURE.md`, `docker-compose.tls.yml`). Verified on the VM: all 5 images built on Linux, 12 containers up (backend, orchestrator,
  shop healthy), `/demo/status` = 7 of 7 agents reachable over the Docker network, dashboard reachable over HTTPS behind basic auth.
  NOT yet verified there: a full investigation through the cloud dashboard, Approve -> execute -> verify, the CrewAI critic profile.
  The images were not built/run on Docker Desktop locally (the VM build is the verification). The student region policy only allows
  indiasouthcentral, malaysiawest, uaenorth, centralindia, koreacentral; `Standard_B2ms` was out of capacity in centralindia.
- **Cost control**: VM costs ~$60-70/month running; deallocate (`az vm deallocate`) between uses. End-term is late Nov / early Dec 2026.
- **Experiment matrix finished**: 8 arms x 6 scenarios (5 faults + healthy control) x 3 repeats = 144 live runs; results and an honest
  interpretation in `docs/EVALUATION_RESULTS_2026-10-16.md`. Headline: the single-agent baseline scored 87% (cheapest/fastest), the
  no-critic arm 100%, shipped hub 80%, blackboard 67%, few-shot 40%; differences are mostly within noise (n=18 per arm).
  Real cost ~ $0.004/run (estimate at peak list price is ~3x higher).
- Pilot findings fixed on the way: non-blind scenario text in the old benchmark, scorer keyword-order bug, evidence-agent output shapes.

## Platform mode + cloud deployment files (2026-10-16) — implemented + unit-tested; images NOT built or run (Docker engine was off)
- Full stack in `docker-compose.yml` (production, backend, orchestrator, 7 agent services, dashboard; optional CrewAI critic via
  `--profile crewai`); Dockerfiles: `agents/` (one image, 7 commands), `orchestrator/`, `crewai_critic/`, `dashboard/` (nginx).
  `docker compose config` passes (also with the profile). Guide: `deploy/DEPLOY.md` (local compose, single-VM cloud recipe,
  security checklist). CI gained jobs for the new suites and `compose config`.
- Code changes that make containers possible, all default-off (local behaviour unchanged): `orchestrator/service.py` (HTTP trigger,
  one investigation at a time, optional `X-Internal-Token`); backend `demo.py` platform mode when `NEXUS_ORCHESTRATOR_URL` is set
  (HTTP instead of subprocess, no process start/stop); agent addresses from `NEXUS_AGENT_URL_<NAME>`; `NEXUS_BIND_HOST` /
  `NEXUS_ADVERTISE_HOST` for services; `NEXUS_MCP_PYTHON` for the MCP stdio server. nginx proxy allows only `GET /orders[/id]` of
  the shop, adds the approver token server-side, optional basic auth (`DASHBOARD_PASSWORD`).
- Bug found while auditing the container wiring: the MCP SDK starts the tool server with a minimal environment, so
  `PRODUCTION_BASE_URL` never reached it (it silently used 127.0.0.1:8001). Now passed explicitly (`mcp_server_env`, tested).
- NOT done: building/running the images, `docker compose up` health checks, an actual cloud deployment (needs the owner's cloud
  account and a decision on provider/TLS). Do not claim Docker or cloud works until those are run.

## Blackboard topology (2026-10-15) — implemented + tested (0 tokens, real backend + real A2A, fake reasoning); NOT yet run live
- `NEXUS_TOPOLOGY=blackboard` (default `hub`). The shared board is the incident record's `blackboard` list
  (`backend/app/incident_store.py::append_board_entry`, `POST/GET /incidents/{id}/blackboard`, six typed entries, atomic,
  bounded at 200, each write also emits a `BOARD_ENTRY` event). In this mode the A2A message is only a pointer
  (`{"nexus_board": {incident_id, role}}`); the AGENT reads the board (`agents/common/board_io.py`), does its work and WRITES its
  `finding` / `hypotheses` / `critique` back; the controller (`orchestrator/blackboard.py`) posts `description` / `request` /
  `review_request` and reads the results back. Same return shapes as the hub calls, so the verdict loop, budget, guardrails,
  recovery, report and trace run unchanged. Usage/monitoring bookkeeping rides in the A2A ack, never on the board.
- Both frameworks support it (ADK executor and the CrewAI critic). The backend address is NOT taken from the message (no SSRF).
- Proven by `agents/tests/test_blackboard_flow.py` (real backend process + 3 real A2A servers; inputs rebuilt from the board,
  outputs authored on the board, hub path still works), `agents/tests/test_board_io.py`, `tests/test_blackboard_api.py`.
- `run_config.topology` records which topology produced a run. Recovery Agent still uses the hub path (no board role).
- Not done: live comparison hub vs blackboard (benchmark), dashboard view of the board.

## Tracing + provenance (2026-10-15) — implemented + tested (0 tokens); NOT yet run live
- `nexus_trace.py` (stdlib only): W3C `traceparent`. `run_investigation` starts one trace per incident (`incident.trace_id`,
  `root_span_id`); every A2A call carries a `traceparent` header (`agents/common/remote_agent.py`, fresh child span per call);
  every agent service (ADK `a2a_server.py` and the CrewAI service) runs `TraceContextMiddleware`; `AgentMonitor` stamps the
  received trace_id on its records. Every orchestrator event payload also carries `trace_id`.
- Proven over the wire: `agents/tests/test_trace_propagation.py` (ADK service) and `orchestrator/tests/test_crewai_critic_a2a.py`
  (CrewAI service) assert the agent saw the orchestrator's trace_id with a child parent span.
- Stored at the end of each investigation: `incident.trace` (span tree: incident -> a2a call -> agent -> model/tool calls;
  inner starts are reconstructed from durations and flagged `start_estimated`) and `incident.lineage` (conclusion -> evidence
  with tool/arguments/agent/finding -> critique -> plan -> approval/execution; never invents ids). Not an OTLP export.
- Not done: dashboard panel for trace/lineage; export to an external collector.

## Security guardrails + prompt variants (2026-10-15) — implemented + tested (0 tokens); NOT yet run live
- `nexus_guard.py`: `screen_user_text` (abuse, prompt injection, empty/too long), `guard_tool_result` (type check, size bound,
  redaction of instruction-like text, flags), `redact_text`. `agents/common/guard_callbacks.py` applies them as ADK callbacks
  (before_model blocks a bad first message; after_tool sanitises results, so stored evidence is the sanitised version) chained
  after the monitor. CrewAI Critic redacts its input too. Orchestrator rejects bad descriptions: `INPUT_REJECTED`, status
  ABSTAINED, no agent called. Honest limit: regex heuristics (tested for false positives on normal log lines), not a proof.
- Red-team tests run on the real ADK runner with a spy model: hostile text in a log line never reaches the model; an injected
  question never causes a model call (`agents/tests/test_guard_callbacks.py`).
- `agents/common/prompt_variants.py`: default / react / fewshot / persona_sre / persona_auditor (architecture vs content
  variance), contract text never edited, no scenario causes named (tested). `run_config` (variant, guardrails, critic framework,
  triage, llm) is stored on each incident and printed in the report; AGENT_MONITOR carries `prompt_variant`.
- Tests: root 83, agents fast 63, orchestrator logic 53, crewai_critic 3. Agent services must be restarted to pick up new code.

## CrewAI Critic over A2A (2026-10-15) — implemented + tested; verified live twice
- `crewai_critic/` (see its CLAUDE.md): the Root-Cause Critic as a CrewAI agent behind an a2a-sdk server, same address and
  contract as the ADK Critic; select with `NEXUS_CRITIC_FRAMEWORK=crewai` (default ADK). Shared ADK-free
  `agents/critic/critic_core.py` and `agents/common/json_extract.py` were split out of the ADK modules.
- Live runs (DeepSeek, db_slowdown, backend + shop + 7 agents started through the real ON switch): both DIAGNOSED, critic
  `framework=crewai` SUPPORTED, 9 model calls / 16,559 and 17,165 tokens (recovery calls not counted), AGENT_MONITOR events
  from 5-6 agents, final report stored (now built at diagnosis time too). Approval was not clicked. Cost of both runs ~ $0.01
  (balance 1.48 -> 1.48, granted 0.94 -> 0.93): real runs are much cheaper than the earlier 80k-token estimate.
- Tests: root 67 + guardrails 24, agents fast 36, orchestrator/eval 81 (incl. ADK->CrewAI A2A), crewai_critic 3.
  Not in CI yet (needs `.venv-crewai`).

## CrewAI + A2A spike (2026-10-15) — passed
- `crewai_critic/SPIKE_RESULT.md`: CrewAI 1.15.28 has no A2A server, so a2a-sdk 0.3.26 serves a real CrewAI agent; the ADK
  client (a2a-sdk 1.1.4) called it over A2A (stub run 0 tokens, then one real DeepSeek call, <1k tokens). Isolated `.venv-crewai`.
- Next: build the real CrewAI Critic service (new port, Pydantic output, usage/monitoring), orchestrator switch, tests.

## Pydantic contracts + ADK monitoring callbacks (2026-10-15) — implemented + tested; NOT run against a live LLM
- `nexus_models.py` (root): Pydantic `Finding/Hypothesis/Critique/RecoveryPlan/IncidentReport`; `build_finding`,
  `build_hypotheses`, `build_critique`, `build_recovery_plan` now validate their output. `attach_report` stores the final
  `incident.report` (JSON fields + Markdown) after every investigation (fail-soft).
- `agents/common/callbacks.py`: `AgentMonitor` wired into `DiagnosticAgent` and `ReasoningAgent` via the real ADK
  callback hooks; trace travels as `monitoring`, orchestrator pops it into an `AGENT_MONITOR` event (`event_bridge.emit_monitor`).
- Tests: root 67 (+8 models), agents fast 36 (+4 callbacks, run on the real ADK runner with a scripted fake model,
  0 tokens), orchestrator deterministic 55 + 3 new, guardrails 24, evaluation 22. The 3 orchestrator tests that fail
  here (`test_incident_manager` x2, `test_investigation_e2e`) need the live agent services; they were not run.
- Not verified: a live investigation emitting `monitoring` and `report` (needs agents ON + DeepSeek tokens).
  Dashboard does not show AGENT_MONITOR or the report yet.

## Five failures, agent triage, live-section redesign (2026-10-13)
- **Five injectable failures** in the dashboard (`dashboard/src/lib/scenarios.ts`): slow database, bad release, wrong setting,
  payment service down, out of memory. Each sends only a customer-side symptom to the agents (blind-evaluation rule).
- **Incident Manager triage** (`orchestrator/triage.py`, 5 tests): keyword rules over the symptom text (never the injected
  fault) pick which diagnostic agents to call; Metrics is always first, at least 2 agents are used, and later rounds only
  re-ask the agents the Critic's request points at. Emits `AGENTS_SELECTED`. `NEXUS_TRIAGE=0` calls all four (and passing
  `agent_names` explicitly also bypasses it). NOTE: this changes which agents the benchmark calls; state it in any results.
- **Found live**: for every failure except the slow database no agent could see WHY requests failed, because the error text
  (`ConfigError: ...`) was only in HTTP response bodies, not the shop's logs. A "wrong setting" run guessed `restart_service`,
  was approved, and the live check correctly failed (5/5 requests still failing). Fix: 5xx log entries now carry the app's
  own error message (`production/service.py`, `tests/test_error_logging.py`); the remedy guardrail's text markers can now fire.
- **Dashboard**: live section re-themed light (matches the site); animated agent flow map (packets, "waiting for reply"
  dots, callback pulse); "Agent conversation" panel (every A2A request and its callback); "In plain English" box with a
  glossary where technical words are explained only if they actually appear; skipped agents show as "not called" with the reason.
- **End-to-end practice runs after the log fix (one each, NOT a benchmark, approvals made by the assistant as labelled tests)**:
  bad release, wrong setting and payment service down were diagnosed, fixed (rollback / reset_config / restart) and verified
  by the live check; slow database and out of memory ABSTAINED (the Critic would not call them proven). Triage picked
  2-3 agents each time; the slow-database run widened to all four in round 2.
- **Presentation page**: new "What we break on purpose" section (`components/story/FailuresSection.tsx`, nav pill "Failures")
  describing the five failures, the clue, the fix and which agents were called first in the practice runs.
- Tests: root 58, orchestrator/guardrails 56 (spot run), MCP 23, `tsc -b` clean.

## Why runs abstained, and the fixes (2026-10-13)
Three separate causes found by reading the abstained incidents, not by guessing:
- **Dirty shop between trials**: the shop's metrics, logs and change history carried leftovers of earlier incidents (old error
  spikes, old "1.2.0-bad" deployments and rollbacks), which the agents treated as contradicting evidence. Fix: `POST
  /admin/reset` on the shop (clears faults, metrics, logs, traces, queries, extra change entries, extra orders; test in
  `tests/test_reset.py`), `POST /demo/reset-shop` on the backend, and the dashboard's Inject flow now resets first.
  Practice harness resets before every trial.
- **Over-demanding Critic**: it kept asking for evidence no tool can return (the payment service's own health, network captures,
  child spans), so it could never be satisfied. Its prompt now lists what evidence can ever exist and says to return SUPPORTED when
  the evidence explains the symptoms, sources agree and nothing contradicts it.
- **Runaway Logs agent**: one run spent 95k tokens (cap 80k) and the budget correctly stopped the incident before the Critic
  could review good evidence. The Logs agent prompt now caps it at 4 tool calls and tells it to quote error text.
- **Presentation page**: new "What testing taught us" section (`components/story/FixesSection.tsx`, nav pill "Fixes") lists 8 real problems found and how each was fixed (answer leak, invisible error text, wrong fix, false "not verified", impossible Critic asks, runaway cost, dirty test shop, lost incidents), with an honest note that results are single runs.
- Result on a clean shop, ONE run each, NOT a benchmark: all five (slow database, bad release, wrong setting, payment service
  down, out of memory) were diagnosed, fixed and verified by the live check. Caveat: the two prompt changes were made after
  seeing failures on these same five scenarios, so they must be re-measured on held-out scenarios before any accuracy claim.
  The out-of-memory plan was `restart_service` + `rollback_deployment`; the rollback was unnecessary (guardrail only blocks
  actions that cannot fix the symptom, not extra ones).

## Leak closed, verification bug fixed, full loop verified live (2026-10-12)
- **Answer leak closed**: `get_git_diff` is now DISABLED by default (`NEXUS_ENABLE_GIT_DIFF=1` to enable) because the repo's
  own history holds the simulator's fault code and docs; the Change Analysis Agent uses only `get_recent_deployments`.
  Scanned the evidence of every post-fix run: no `/admin`, "fault", "inject" or "db_slowdown" text. Also fixed a real
  Windows bug in that tool (git output decoded as cp1252 -> crash; this was the "git diff tool failed" seen in the
  first live run). MCP tests 23 pass.
- **Verification bug fixed (found live)**: the post-fix probe measured ~2050 ms and wrongly reported "not verified"
  even though the shop was healthy. Cause: the default shop address `http://localhost:8001` costs ~2.05 s per request on
  Windows (IPv6 tried first); `127.0.0.1` takes ~10 ms (measured). Defaults changed in `guardrails/config.py`,
  `mcp/config.py`, `fault_injection/injector.py`, `evaluation/production_reader.py`. This also slowed every MCP tool
  call (MCP tests 55 s -> 15 s). It explains the earlier "median 2319 ms" false failure.
- **Guardrail made robust**: `remedy.py` also recognises a slow database from the MEDIAN of `recent_queries` (a real run
  had a diluted 200-query average of 57 ms while every recent query took ~260 ms, so the wrong plan
  `rollback_deployment + restart_service` slipped through). Replayed that real incident: now REJECTED with
  "action(s) that do: ['scale_resources']". +2 tests (guardrails 24).
- **Prompts**: Critic and Evidence instructions now tell the model to read timestamps (a fast->slow step change is an
  onset, not "intermittent"). Motivation: one run abstained because the Critic treated pre-onset fast requests as
  contradicting evidence.
- **Live practice runs (DeepSeek, leak closed, n is SMALL — not a benchmark)**: before the prompt change 1 diagnosed /
  1 abstained; after it 3 of 3 diagnosed, then later 1 abstained and 1 diagnosed. All proposed `scale_resources` when
  they diagnosed. Usage per run 21k-110k tokens (limit 250k). Expect the demo to abstain sometimes: just run it again.
- **Full loop verified live**: INC-8d0d3c86 diagnosed -> `scale_resources` -> approved -> executed -> live probe median
  ~20 ms (limit 100) -> `verified: True` -> **RESOLVED**; shop healthy. NOTE: that approval was made by the assistant
  as a test, recorded as approved_by "assistant-verification-run (authorised by the user, ...)", not a human click.
- UI: system-status window dots are red/amber/green again; "Open the simulated shop" link restyled (was unreadable
  dark-blue on dark). Agent start now relaunches an agent whose process died (a restart left 5/7 down once).
- Still open: benchmark with repeated trials + healthy control scenario; agents in Docker; commit/PR.

## Realistic storefront: catalog, cart, real checkout (2026-10-12)
- New `production/catalog.py` (8 invented products, static, NOT DB-backed), `GET /products`, and **`POST /orders`**
  (checkout; server-computed total; validation 400/422) backed by `db.create_order` (timed, slowed by db_slowdown,
  recorded in the query store; locked INSERT). Checkout runs `_check_order_endpoint_faults`, so config_error /
  bad_deployment break it and db_slowdown slows it. Dockerfile now also copies `catalog.py`.
- `storefront.html` rewritten as a shop: nav + hero, product grid (emoji art, no external assets), cart drawer
  (qty +/-), checkout with name, order list (escaped, last 8), friendly failure message ("Something went wrong", cart
  kept), toasts, and a slim **Demo monitor** strip (Healthy/Slow/Errors from real requests; "Simulate shoppers").
  Phone width checked (375 px, no overflow after hiding the timestamp column).
- Verified in the browser against the live service: healthy checkout 5 ms; same checkout under db_slowdown 262 ms;
  config_error -> friendly error with cart kept; monitor Healthy -> Slow (268 ms) -> Healthy. Tests: root 55
  (+6 checkout: validation, server pricing, fault behaviour, INSERT visible to the Database Agent).
- Side effect to remember: checkout adds rows, so `/db/diagnostics` row counts grow during a demo; restart the
  shop to reset to the 10 seed orders. Agents will also see `POST /orders` and `GET /products` in their metrics.
- `docs/API_CONTRACT.md`, `production/CLAUDE.md`, `docs/DEMO_GUIDE.md` updated.

## Storefront page + demo guide (2026-10-12)
- `production/storefront.html`, served at **`GET /shop`** by the simulated service: orders table, live response-time
  bars, Healthy/Slow/Having-errors badge (100 ms limit, same as recovery verification), optional "Simulate shoppers"
  (1 request/s). Self-contained; calls only `/orders[/id]` (test asserts no `/admin` in the page). Its requests are
  ordinary customer traffic, so they appear in the metrics/logs the agents read (and double as the traffic that makes
  db_slowdown observable). Dashboard Command Center has an "Open the simulated shop" link.
- Verified in the browser: Healthy (~5 ms) -> injected db_slowdown -> Slow (~268 ms, 12 amber bars) -> cleared ->
  Healthy (~5 ms). Tests: root 49.
- **Bug fixed**: `production/Dockerfile` did not copy `state.py` (nor the new HTML), so the container would have crashed
  on import; test now checks the Dockerfile lists every needed file. Docker image NOT built/run.
- `docs/DEMO_GUIDE.md`: step-by-step 5-7 minute demo script with what to say, timings, troubleshooting, likely questions.
- Dashboard: removed stale "incident state is held in memory" empty-state text (store is SQLite now).

## First live run after the 2026-10 changes (2026-10-12) — real DeepSeek run, db_slowdown, stopped at human approval
- Key check: one 12-token call to `deepseek/deepseek-chat` succeeded (the 2026-09-21 rejection is resolved).
- Run INC-2f1cd21c (same steps as the Inject button, via the real backend): 7/7 agents, **DIAGNOSED in ~48 s**, 2 critic
  rounds (INSUFFICIENT_EVIDENCE then SUPPORTED), top cause H4 at 62%; Recovery Agent proposed **`scale_resources`**
  (the correct fix for a slow DB — the earlier run chose `reset_config`), guardrails APPROVED_FOR_HUMAN_REVIEW,
  `HUMAN_APPROVAL_REQUESTED`. **Approval was NOT clicked** by the assistant, so execution + live verification were not
  re-run in this pass.
- **Measured usage** (first real numbers): 22 model calls, 76,109 prompt + 5,377 completion = 81,486 tokens, 0 unmeasured
  tasks, no budget limit hit (defaults 60 calls / 250k tokens). Recovery-stage calls not counted.
- **MCP leak fixed, confirmed live**: tool-server processes stayed at 8 (4 agents x 2, idle baseline) after a full
  2-round investigation. Agents ON/OFF/ON through the endpoints: 7 -> 0 -> 7.
- **NEW FINDING — answer still leaks to the agents through `get_git_diff`**: the metrics/logs/traces no longer show
  `/admin` calls, but the Change Analysis Agent's `get_git_diff` reads this repo's own git history, and its allowlist
  (`mcp/config.py` GIT_DIFF_ALLOWED_PATHS = production, backend, mcp, docs) contains the simulator's source (fault
  switches `db_slowdown` etc. in `production/`, `backend/app/demo.py`) and the docs that describe every fault. The
  diagnosis text ("An injected, reversible runtime 'db_slowdown' fault ...") shows the agents used it. **Do not run the
  official benchmark until this is closed** (move the fault/admin code out of what the tool can read, give the Change
  agent a simulated change log only, or disable `get_git_diff` for evaluation) — otherwise blind evaluation is invalid.

## Autonomy fixes (2026-10-12) — implemented; deterministic tests pass; NOT run against a live LLM
- **OFF switch stops agents**: `POST /demo/agents/stop` (`demo.stop_agents`) kills only the agent processes this
  backend started (process tree via `taskkill /T`); hand-started ones are reported, not killed. Dashboard OFF calls it.
- **MCP process leak fixed**: `DiagnosticAgent.investigate` now closes its toolset in a `finally`. Measured without
  any model call: opening a toolset = 2 processes (launcher + server), after closing = 0.
- **Late approval works**: approving an EXPIRED plan now resumes the SAVED plan (`run_demo.py --resume-recovery`,
  `recovery.resume_approved_recovery`): re-validated against the guardrails (not trusted), then the same
  execute -> verify path; refuses (503) if the orchestrator venv is missing; never acts without a real human
  APPROVED. Dashboard shows "APPROVE SAVED PLAN" in the expired state.
- **Optional approval gate**: if `NEXUS_APPROVER_TOKEN` is set, `/approve` needs header `X-Approver-Token`
  (dashboard dev proxy adds it server-side). Off by default; blocks direct calls to the backend only — NOT real
  user authentication.
- **Stable hypothesis ids**: `reconcile_hypotheses` (plain code) gives a re-proposed theory the same id across
  rounds (word-overlap >= 0.5), plus `revision` and `previous_confidence`. Dashboard does not show them yet.
- **Rulebook**: root `CLAUDE.md`/`AGENTS.md` sections 6-7 now say DeepSeek (owner's decision, 2026-10-12).
- **Archive**: older history moved verbatim to `docs/archive/PROJECT_STATE_HISTORY.md`.
- Tests: root 46, orchestrator/guardrails/evaluation/fault-scenarios 100+, agents-fast 32 — all pass.
- **Not done**: agents in Docker (the stack is tied to local venvs: agents spawn `.venv-mcp`, the backend spawns
  `.venv-orchestrator`; needs a real redesign), real benchmark with repeated trials + healthy control scenario.

## Current state, next steps, known issues
- **Phase**: 1-10 implemented and unit-tested; live end-to-end with a model verified in 2026-09-21 runs (first
  real runs, db_slowdown), NOT re-verified after the 2026-10 changes (budgets, guardrail remedy check, stage
  tracker, late approval).
- **Key**: `DEEPSEEK_API_KEY` verified working 2026-10-12 (rejected on 2026-09-21). Agent services read
  `.env` only at startup — restart them after changing it. A git worktree has no `.env`/`.venv-*`: link/copy them.
- **Next**: run `evaluation/run_experiment.py` (add repeated trials and a
  healthy/ambiguous control scenario first, so false-diagnosis and abstention can be measured).
- **Known issues**: Docker Compose runs only backend + production; the agent services and dashboard run as local
  processes. Recovery Agent / verification model calls are not counted in the budget. The `remedy` guardrail knows
  4 symptom classes only. Single-agent baseline reports no token usage. Dead diagram CSS was removed from
  `LivePipelineSection.module.css`.
- **Rulebook caveat**: root `CLAUDE.md` section 5 ("current verified state") is still the 2026-09 text.

## Spending limits + durable incidents (2026-10-10) — implemented; deterministic tests + a real server-restart check pass; NOT run against a live LLM (no working key this session)
Two Definition-of-Done gaps closed (root CLAUDE.md §8 budgets, §15 persistent incident state):
- **Per-incident budget** (`orchestrator/budget.py`, `IncidentBudget`): env-driven
  `MAX_LLM_CALLS_PER_INCIDENT` (60), `MAX_TOTAL_TOKENS_PER_INCIDENT` (250000), `MAX_TOKENS_PER_AGENT`
  (80000). **The default numbers are guesses sized above a normal 3-round run, not measured — tune after
  a real run.** Usage is MEASURED at the source: `agents/common/usage_tally.py` sums ADK
  `usage_metadata` (filled by LiteLlm from the provider's own usage block) inside each agent; the
  Finding / hypotheses / critique / recovery-plan reply carries a `usage` key; the orchestrator pops it
  (so it never reaches stored evidence or other agents), records it, and persists the snapshot as
  `incident.token_usage`. `investigation.py` checks the budget before evidence synthesis, before each
  critic review, before a re-dispatch of the diagnostic agents, and before recovery; when spent it
  ABSTAINS with the limit named in `decision.reason` (a DIAGNOSED incident keeps its diagnosis but
  recovery is withheld, and says so). A task that reports no usage counts as 1 call (flagged in
  `unmeasured_tasks`), never as free.
  **Limits of this pass**: Recovery Agent and post-fix verification calls are not counted; agents that
  never answered are not counted; provider quota/rate-limit headers are still not captured (panel says
  "Unavailable from provider"). Agent services must be RESTARTED to emit `usage` (they load code at startup).
- **SQLite-backed incident store** (`backend/app/incident_store.py`; same function names, `main.py`
  untouched): `NEXUS_DB_PATH` (default `backend/.data/nexus.db`, gitignored; `:memory:` for tests;
  docker-compose now mounts a `nexus-data` volume at `/data`). `tests/conftest.py` forces `:memory:`;
  `clear()` refuses to run on a file DB. Event ids stay `evt-N`, monotonic across restarts.
- **Dashboard**: `UsagePanel` now renders real calls/tokens vs limits, per-agent usage, and a warning when a
  limit stopped the run; empty state when nothing recorded. `TokenUsage` type added.
- **Tests**: root 35 (was 29; +6 persistence), orchestrator deterministic 40 (was 19; +9 budget unit, +4
  budget-in-loop), agents deterministic 32 (was 27; +5 usage tally), guardrails 14, evaluation 16,
  fault_injection scenarios 5 — all pass. Mutation check: with `exceeded()` disabled the 3 budget-stop tests
  fail. Real restart check: killed and restarted the actual uvicorn backend against one DB file; the
  incident, state and event survived. `npm run build` clean. UsagePanel checked in the browser against test
  data posted through the real API (verification harness, wiped afterward): both the usage and no-usage states.
- **Not verified**: a live investigation emitting real `usage` from a model; `docker compose build/up`
  (only `docker compose config` was run); real-LLM test suites.
- **Pipeline tracker, token cost, CI (2026-10-12)**. (1) `components/presentation/StageTracker.tsx` replaces the
  scroll-fade diagram in `LivePipelineSection`: six FIXED stages top to bottom (gather evidence with the 4
  specialists as rows, form causes, challenge, decide, propose fix, approve/run/verify), no fade-in; each stage's
  state and result line come only from the real incident model (`buildCommandCenterModel`), and with agents OFF
  it shows the structure with no states/results. Checked in the browser with hand-written test incidents posted
  through the real API (verification harness, wiped): full run with failed live check (5 done + red "Problem"),
  mid-gathering (stage 1 "Working now", rest waiting), desktop colours via computed styles, 375px no overflow.
  Not verified: a live LLM run through it; screenshots were unreliable (pane scroll lag), so checks used DOM text
  and computed styles. Old diagram CSS in `LivePipelineSection.module.css` is now dead code (not removed).
  (2) `scoring.token_cost(incident)`: `run_experiment.py` now records measured `token_usage` per run instead of
  hardcoding "Unavailable from provider"; `aggregate()` averages it over runs that have it; baseline arm still
  has none. +6 evaluation tests (22). (3) `.github/workflows/tests.yml`: deterministic suites + dashboard build +
  secret scan on every push; NOT yet run on GitHub. Local totals: root 40, orchestrator/guardrails/evaluation/
  fault-scenarios 89, agents-fast 32, `tsc -b` clean.
- **Recovery fixes after the first live run (2026-10-11)**. Live run: diagnosis supported, but the plan chose
  `reset_config` for a slow database, the live probe measured ~2300 ms (limit 100) and honestly reported "not
  verified"; `db_slowdown` was still on. Also the agents "diagnosed" our own `POST /admin/fault/inject` log line.
  (1) `guardrails/remedy.py` + `policy.validate_plan(plan, evidence_pool)`: a plan is REJECTED when the evidence
  clearly shows a symptom (avg_query_ms >= 100 -> db_slowdown; "ConfigError" / "DependencyTimeoutError" /
  "ResourceExhaustedError" text) and none of the plan's actions addresses it (uses the existing
  `ALLOWED_ACTIONS[...]["addresses_faults"]`). It reads only MCP evidence, never `/admin/state` (that would be an
  oracle). No recognised symptom (e.g. bad_deployment has no marker) = no opinion. The same evidence-derived
  `remedy_guidance` is also sent to the Recovery Agent so it picks a fitting action first time.
  (2) `production/service.py` no longer records `/admin/*` calls in metrics/logs/traces. (3) Dashboard: the third
  stage reads "Not recovered" when verification fails. CORRECTION: I first claimed the stepper lit "Recovered"
  on a failed check; the code showed it did not (Verifying turned red, Recovered stayed unlit) -- label only.
  Tests: guardrails 22 (+8), root 40 (+2: admin hidden; customer traffic still recorded), mutation-checked.
  Verified live: admin paths absent from `/logs` and `/metrics` after an inject. NOT verified: a full live
  investigation with the new guardrail/prompt (needs a working key); restart the Recovery Agent service to load
  the new prompt. Limits: detection only knows 4 symptom classes.
- **Agent ON switch now starts the agents (2026-10-11)**: it used to only flip a display flag. The dashboard
  switch calls new `POST /demo/agents/start` (`backend/app/demo.py::start_agents`), which launches the 7 fixed
  `agents/*/a2a_service.py` scripts (allowlist, no request input) that are not already reachable; idempotent,
  skips agents still booting. Idle agents make no model calls. OFF does NOT stop them yet. `check_agents` now
  probes in parallel. Verified live: 0/7 -> click ON -> 7/7 reachable in ~30s; `tests/test_demo_agents.py`
  (3 tests); root suite 38 passed; `tsc -b` clean. Needs `.venv-agents`, `.venv-mcp`, `.venv-orchestrator`
  and `.env` at the repo root (git-ignored; a git worktree has none, so they were linked/copied in for testing).
- **Docs refreshed in the same pass**: README (status, DB location, plain-English "test data" and "packages"
  sections), `docs/API_CONTRACT.md` (durable store, `usage`/`token_usage` shape), `docs/NEXUS_OVERVIEW.md`,
  `docs/EVALUATION.md`, and the stale Next-list bullets below (marked RESOLVED). Root `CLAUDE.md`/`AGENTS.md`
  were NOT edited (they are the rulebook; §5 "current state" and §6 provider wording are out of date — owner's call).
- **Gap**: `evaluation/run_experiment.py` still hardcodes `token_cost: "Unavailable from provider"`; wiring it to
  `incident.token_usage` would make the benchmark's token-cost metric real (not done, needs a test).
- **Still open from the improvement list**: run a real benchmark (needs a working key; run each scenario
  several times; add a healthy/ambiguous control scenario), MCP process leak, approval decoupled from the
  orchestrator process, `/approve` auth, stable hypothesis ids, agents in Docker, parallel `/demo/status`
  probes, CI, trimming this file, provider wording in root CLAUDE.md §6.

## Presentation: Architecture section (2026-10-01) — implemented; `tsc -b` clean; checked in browser at desktop + 375px
Dashboard-only. New `components/story/ArchitectureSection.tsx` + `Architecture.module.css`, inserted
between the agent bento and the steps rail on `/presentation`; "Architecture" added to `PillarsNav`.
Contents: an SVG hub-and-spoke diagram (Incident Manager, 4 specialists fan-out, Evidence/Critic/Recovery
sequential, guardrails, event store; ports 8101-8107), six communication-pattern cards, six design principles.
- **Honesty**: only hierarchy/hub-and-spoke, parallel fan-out/gather, pipeline+feedback loop and the event
  log are marked "Implemented". Peer-to-peer mesh and agent-to-agent broadcast/pub-sub are marked "Not used,
  by design" — NEXUS agents never call each other; all calls go through the Incident Manager, and the dashboard
  polls the event store (no push stream). The "why not" text is design rationale, not a measured comparison.
- The diagram is labelled as architecture drawn from code, not a recorded run. Static content, no backend data.
- Not verified: animation feel (pane was hidden, so fade-ins were mid-transition in screenshots).

## Recovery fixes + cost guard (2026-09-21/22) — implemented; deterministic tests pass; NOT verified against a live LLM (provider key was revoked mid-session)
- **Found (from `backend/.demo_logs/`)**: (1) a run was approved and marked **RESOLVED** while
  production still had `db_slowdown: true` — `orchestrator/recovery.py::_verify_recovery` only
  checked the metrics error RATE, and a latency-only fault has zero errors, so it always passed.
  (2) 3 of 4 diagnosed runs ended approval `EXPIRED` (window was 120s; once it closes the
  orchestrator has exited, so a late Approve does nothing). (3) Every plan chose
  `restart_service`, which does not clear `db_slowdown` (only `scale_resources` does).
  (4) The plan sat at the bottom of a long card.
- **Fixes**: verification now decided by a deterministic live probe (`_probe_service`: 5 timed
  real GETs each to `/orders` and `/orders/1`, median < `VERIFICATION_LATENCY_MS` (100) and
  failures < 20%); the Metrics Agent re-check is supporting evidence only and fail-soft. New
  `orchestrator/tests/test_verification.py` (6 tests, incl. the exact false-RESOLVED case).
  `MAX_APPROVAL_WAIT_SECONDS` default 120 -> 600 (`guardrails/config.py`). Recovery Agent
  `ACTION_CATALOG`/instruction now state which symptom each action remedies (slow DB queries ->
  `scale_resources`, restart does NOT fix them). Dashboard: approval banner at the TOP of the
  Command Center (Approve / Keep investigating), clear "window closed, nothing executed" state,
  and the real post-fix probe numbers shown for RECOVERED / NOT VERIFIED.
- **Cost guard (UI)**: "Inject Database Slowdown" now asks for confirmation (states it makes
  ~10-30 paid model requests) and is disabled while an investigation is in progress or awaiting
  approval. NEXUS has no per-call token accounting yet (UsagePanel is "Unavailable from
  provider"), so dollar cost cannot be computed here — use the provider's usage page.
- **Cost finding**: idle NEXUS makes zero model calls (agent services logged only agent-card
  GETs plus A2A POSTs for real runs). Five investigations were launched by the button after the
  key was fixed (23:09, 23:11, 23:12, 23:13, 23:44 IST); the 23:44 run used 3 re-evaluation
  rounds (18 agent tasks). Only two were started by the assistant.
- **Housekeeping**: `.gitignore` now also ignores `reference_web/`, `.env.*` (keeps
  `.env.example`). Verified `.env` was never committed and no key-like strings exist in the tree
  or git history. 76 orphaned MCP server processes (leaked per investigation round) were killed;
  the leak itself is NOT fixed. The 7 agent services were left STOPPED on purpose (key rejected
  by DeepSeek, and to avoid surprise spend); restart them only after a new key is set in `.env`.
- Tests: agents 27, guardrails+orchestrator logic 33 (incl. 6 new), backend 10 — all pass.

## UI redesign after the reference site (2026-09-21) — implemented; visually checked; user has NOT yet accepted it
Whole-dashboard redesign modelled on `reference_web/` (a saved copy of a public marketing site).
A first attempt only re-coloured the old layout and was rejected as "merely colors"; this pass
rebuilt page structure and scroll animation. Only the *design language and interaction patterns*
were borrowed: no reference text, logos, images or paid fonts (PolySans / Perfectly Nineties are
NOT used; Inter + JetBrains Mono are self-hosted via `@fontsource-variable/*`).
- **Theme**: the reference is a *light* page with dark product frames inside it. Marketing
  pages (`/`, `/presentation`) are now light (`--lt-*` tokens), with dark frames/bands using the
  existing `--nx-*` dark tokens (kept for the incident pages and all data panels). Brand
  vermilion; green/amber/red stay state-only.
- **New shell** (`components/layout/AppShell`): announcement strip driven by REAL backend status
  (off / connecting / unreachable / live n of 7) + minimal nav with a pill CTA; dark variant on
  incident pages.
- **New story components** (`components/story/`): pinned hero (230vh sticky, word-by-word
  blur/rise headline, perspective grid, a 16:9 product frame that GROWS on scroll while the copy
  swaps — scroll progress via motion `useScroll`, frame UI scaled from a fixed design size);
  tech marquee (names only, no logos); "The problem" marker + two-tone headline; dot-grid
  statement whose words fill on scroll; "The solution" side-by-side window panes (labelled
  illustrative, not a recorded run; content derives from the real architecture and
  `evaluation/baselines.py`); bento agent cards (mono panels list real tool/enum names, never
  results); 6-step rail; dark "live system" band containing the existing real-data pipeline +
  Command Center; closing CTA; floating pillars nav.
- **Pages**: `/presentation` = full story; `/` (Overview) = hero + marquee + live band + recent
  incidents. Removed: old `HeroSection`, `LifecycleSection`, `AgentTeamSection`, their CSS.
- **Honesty rules unchanged**: the hero frame and strip show only real state (agents OFF /
  connecting / unreachable read as such; nothing simulated).
- **Rollback**: previous UI (before any redesign) is in `dashboard/_backup_ui_v1/`. Restore by
  replacing `dashboard/src` with `_backup_ui_v1/src`. Delete the backup once the new UI is accepted.
- **Verified**: `tsc -b` + `npm run build` clean; desktop `/`, `/presentation`, incident page and
  390px checked in the browser; hero growth confirmed by sampling real scroll (frame 576→683px at
  300px scroll, copy fade/swap wired). Screenshots were unreliable after scrolling (tool quirk),
  so lower sections were captured with a tall viewport and the hero hidden.
- **Not done / caveats**: the reference's rolodex/bento product videos and its light "product
  screenshot" imagery were not recreated; animations were checked by sampling, not by eye in a
  real scrolling browser — please judge the feel yourself.

## Presentation page: professor-friendly layer (2026-09-21) — implemented; verified against real backend+production, NOT against a live LLM investigation
Dashboard-only change (`dashboard/`, one `.claude/launch.json` addition). No edits to
`backend/`, `orchestrator/`, `agents/`, `mcp/`, `guardrails/`, `production/`.
- **Route `/presentation`** (nav: Overview | Incidents | Agents | Presentation — no
  "Metrics" page exists in the codebase, so none was invented). All existing pages
  (`/`, `/incidents/:id`) kept and re-checked.
- **Narrative layer**: hero, 6-step lifecycle, hospital-team analogy for the 7 agents,
  live 7-agent pipeline, Agent Master Switch, 7-question Command Center. Technical
  Details drawer holds IDs, MCP calls, A2A task/context IDs, raw events, raw JSON.
  `lib/presentation.ts` derives all plain-English views; every string is either a fixed
  label translating a real event/verdict/action or text the real agents produced.
- **Real-vs-offline rules**: OFF = "AGENTS OFFLINE · ILLUSTRATIVE DEMO", a data-free
  explanation of the 7 questions (no incident, no numbers). ON + probe in flight =
  "CONNECTING…". ON + no backend = "BACKEND UNREACHABLE", nothing substituted. ON + backend
  = real status/events only; pipeline node states (working/reported/failed) come from real
  events. Reasoning-agent "working" is derived from ordered event counts (see docstring).
- **Fake data removed** (was present before this pass): hardcoded static scenario
  (`staticScenario.ts`), live mapper with invented agent names/MCP URIs/filler claims
  (`liveToHuman.ts`), hero telemetry (P99 2,420ms/14.2%/89%), scripted fallback on
  backend-down, inaccurate agent/lifecycle copy ("Prometheus", "replica lag",
  "continuously samples error budgets", "zero hallucinations"). `InvestigationPage` also
  stopped substituting the static scenario when the backend/incident is missing.
- **Demo scenario: `db_slowdown`** (chosen after inspecting `fault_injection/scenarios.py`
  and measuring in-process): with `/orders` traffic, real evidence = query ~260ms vs 0.03ms
  healthy, `/orders` avg ~206ms/p99 ~263ms, 0 errors, no deploy entry. Without traffic the
  fault leaves NO signal, and nothing in NEXUS generates traffic. The button therefore
  sends real `GET /orders` requests (`sendCustomerRequests`, via a narrow Vite proxy
  `/production` that allows only `GET /orders[/id]`; `/admin/*` unreachable). Incident
  description is symptom-only (does not name the cause). Fault logic untouched.
- **Recovery UI**: Approve / Keep Investigating shown only when the real incident has a
  `recovery_plan` with `approval_state.PENDING`; EXECUTING → VERIFYING → RECOVERED are
  derived from real approval state + `RECOVERY_EXECUTED`/`RECOVERY_VERIFIED`/status.
- **Also fixed**: `deriveAgentStates` sorted `evt-N` ids lexically (evt-10 before evt-2);
  now numeric.
- **Verified (2026-09-21)**: `tsc -b` + `npm run build` clean; dev server on :5173. Browser:
  OFF, ON+backend-down, ON+backend/production-up (0/7 agents), real inject flow (baseline
  requests → `POST /demo/investigate` → real incident + production state), Overview,
  incident page, missing-incident page, Technical Details, 390px layout (no overflow;
  pipeline stacks). Abstention, recovery-pending, real `POST /approve`, EXECUTING/
  VERIFYING/RECOVERED were exercised with **hand-written test incidents posted through the
  real backend endpoints (verification harness only, not product data; wiped afterward)**.
- **NOT verified**: a live LLM-driven investigation of the db_slowdown scenario through
  this UI (agent services + DeepSeek were not started). Screenshots were unreliable while
  the pane was hidden (Framer Motion does not animate then), so most checks were DOM text.
- **First real run through the UI (2026-09-21, later)**: with all 7 agent services up
  (7/7) the inject button worked end to end (real incident, real orchestrator subprocess,
  real events), but **every agent's DeepSeek call was rejected: "Authentication Fails …
  api key is invalid"** (key in `.env` has a valid shape: 35 chars, `sk-`, no quotes/space;
  no OS env var shadows it) → 4/4 diagnostic agents failed → Evidence Agent had nothing →
  honest ABSTAIN. Blocker is the key (revoked/expired/wrong), NOT the UI. Fix: replace
  `DEEPSEEK_API_KEY` in `.env`, then restart the agent services (they read `.env` at
  startup). The dashboard now explains "no agent returned evidence" and keeps polling while
  the tab is in the background. `.claude/launch.json` gained the 7 agent configs (the
  preview tool caps at 5 servers, so 5 agents were started as background processes).
- **Live run PASSED (2026-09-21, after the key was replaced and the 7 agent services
  restarted — they read `.env` only at startup)**: clicking the UI button ran the real
  chain twice: 4/4 diagnostic agents reported (real MCP evidence: `/orders` avg ~248ms,
  p99 ~266ms, 0 errors; DB queries ~256-261ms), Evidence Agent 3 hypotheses (85% top),
  Critic SUPPORTED, DIAGNOSED, Recovery Agent proposed a plan, guardrails validated,
  `HUMAN_APPROVAL_REQUESTED`. **Approval was not clicked** (so execution/verification not
  exercised live). Observation: both runs the Recovery Agent proposed `restart_service`,
  which per `production/state.py` does NOT clear `db_slowdown` (only `scale_resources`
  does) → approving would run, then honestly fail verification. Recovery logic untouched.
- **Bug fixed**: `deriveAgentStates` read `source` for `AGENT_STARTED`, but the
  orchestrator emits source=incident_manager/target=<agent>, so agents never showed
  RUNNING (also affects `InvestigationPage`). Verified: the 4 agents now show "working now"
  during a real run. Card also clamps long agent text and no longer repeats it 3x.
- **Known limitation**: `GET /demo/status` takes ~14s when no agent service is up
  (sequential probes), so ON shows "CONNECTING…" that long. Existing backend behaviour.



_Older history: see `docs/archive/PROJECT_STATE_HISTORY.md`._

## 2026-10-19 - Held-out matrix complete
- 126/126 valid runs (Gemini `gemini-3.5-flash-lite`, 3 owner keys used in turn, same model). Baseline 94%; multi-agent arms 62-75% (not separable at n=18); hub/no-critic/blackboard/pipeline named a fault on the healthy control in 1 of 2 runs. Details: `docs/EVALUATION_RESULTS_HOLDOUT.md`. Raw results are gitignored under `evaluation/results/`.
- Web search tool (2026-10-19): `web_search` on the analysis MCP server, opt-in (`NEXUS_ENABLE_WEB_SEARCH=1`), refuses secret/URL/IP/internal-host queries, results capped and flagged untrusted. 11 new tests (`mcp/tests/test_web_search.py`, local fake page). Seen live: a real DuckDuckGo query returned results, and the Logs agent chose to call it during an A2A request.
- CrewAI -> ADK A2A (2026-10-19): ADK services now serve a card with the 0.3 fields added (`agents/common/legacy_card.py`); a 0.3 client and CrewAI's `execute_a2a_delegation` completed tasks against the live Metrics agent. A full CrewAI Agent with `a2a=A2AClientConfig` failed only because gemini-3.5-flash-lite filled `a2a_ids` with the card name. Reverses the earlier 'cannot' note.
- Jaeger verified afterwards (see OTLP note above). Still not verified: Azure scripts and Approve on the VM. Full test run 2026-10-19: root 316, evaluation 47, mcp 57, crewai 8 pass; agents (89) and orchestrator (76) pass except tests needing live agents/model quota, which pass when the agents are started (test_a2a 6/6, test_incident_manager 2/2); the live end-to-end test was not rerun (Gemini daily quota used).
