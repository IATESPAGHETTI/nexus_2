# NEXUS Project State

## Three-run benchmark (2026-10-13/14) — measured; supersedes the single-run numbers on /research
Reports `2026-10-13T18-25-37Z`, `2026-10-14T15-45-06Z`, `2026-10-14T15-53-54Z` (gitignored; pooled into `dashboard/src/data/benchmark.json`).
5 faults x 3 runs = 15 fault-runs per arm, deepseek-chat, merged code, 0 errored runs. Correct: single agent 15/15 (2.5k tokens),
full NEXUS 14/15 (33.2k), no critic 14/15 (29.6k), triage 14/15 (32.2k, 3.1 specialists). Every miss was resource_exhaustion and it moved
between arms run to run => noise, not a real difference. Triage used 3% fewer tokens than full overall (483k vs 498k) and was cheaper in
11 of 15 fault-runs; the earlier single-run "triage costs more (38k vs 33k)" was NOT borne out. Cost of this step: balance 0.66 -> 0.56
(live recovery check + 2 repeats, ~5 cents per full run). Conclusions are still limited to simple single-cause faults.

## Architecture diagram completed + live recovery check (2026-10-14) — diagram checked in the browser; recovery check run live
Diagram (`ArchitectureSection.tsx`, on /presentation) now also shows: the simulated shop and the MCP layer under the specialists, the
Critic's evidence loop back to the specialists via the manager (max 3 rounds), Recovery running only after the Critic approves, and the
safety path Guardrails -> Human approval -> the only line that changes the shop. Verified in the pane (loop line re-routed below the
boxes after it first crossed Recovery). **Live recovery check passed**: db_slowdown injected, diagnosed (9 calls, 29,198 tokens),
`scale_resources` proposed (LOW risk), safety validation passed, approved via `POST /incidents/{id}/approve` BY CLAUDE on the user's
instruction (no approver token set), executed, verified (shop 270 ms -> 21 ms, 0 failures), incident RESOLVED. Observed: the event log
has `HUMAN_APPROVAL_GRANTED` twice (backend and orchestrator both emit it); harmless, not fixed.

## Recorded runs for credit-free demos (2026-10-14) — implemented; typecheck clean; played back in the browser
Three real full-NEXUS investigations from the 2026-10-13T18-25-37Z benchmark (db slowdown, bad deployment, config error) were
exported unchanged from `backend/.data/nexus.db` to `dashboard/src/data/recordings/`. They open on the normal investigation page
(`/incidents/<id>`, linked from `/research`) with a red "Recorded run, not live" banner and playback controls. Tokens shown for the
db-slowdown recording (34,445) match the benchmark report. Not a substitute for live runs and never presented as one. Decision
taken after the user asked about faking data: NO benchmark numbers were invented; the replay only re-plays real saved events.

## Triage arm benchmarked on the merged code + research page fixes (2026-10-13)
`evaluation/run_experiment.py` now has a 4th arm `nexus_triage` (Incident Manager triage picks the specialists; the other NEXUS
arms force all four via `agent_names`) and records `agents_consulted`. Report `evaluation/results/2026-10-13T18-25-37Z.json`
(gitignored; numbers copied to `dashboard/src/data/benchmark.json`): 5 faults, 1 run per arm, 0 errors, deepseek-chat.
Accuracy: single agent 100% (2.5k tokens), full NEXUS 80% (33k; missed resource_exhaustion this run), no critic 100% (29k),
triage 100% (38k, 3.2 specialists on average). Triage called fewer specialists but cost MORE tokens overall: -36%, -11%, -14%
on three faults, +76% on config_error and resource_exhaustion (called all four + longer critic loops). Differences in accuracy
are one fault = noise. Not comparable with the earlier tables (different code). Cost: balance 0.73 -> 0.68 (~5 cents).
**Research page was black when scrolled** in the embedded browser (also on /presentation): fixed on /research by removing the
`overflow-x: clip` page wrapper, giving every section its own background and setting the body colour while mounted; checked in
the pane. Same fix applied to `/presentation` afterwards (`Story.module.css` `.page` no longer sets `overflow-x: clip`); both pages
verified at the top, middle and bottom in the pane, no horizontal overflow.
**Still open**: repeat runs for variance; leave-one-out arm; live recovery check; resource telemetry in the simulation.

## Merge of `claude/research-questions-architecture-e9382f` into the improvements branch (2026-10-13)
Both branches had independently built the same token accounting, git UTF-8 fix, `/admin/reset`, hidden admin calls, MCP
close-after-task and an evidence-limits critic prompt. Kept THEIRS for all of those (`usage_tally`, `budget`, critic EVIDENCE
LIMITS prompt, fuller `/admin/reset`, triage, shop). Brought over from mine only what was unique: the `/research` page and its
benchmark data; Evidence Agent `fault_class` + scoring on it (negation guard); loop stall detection (`_stalled`, 3 tests);
the critic's "partial failure is not a contradiction" rule; benchmark runner changes (reset + inject + 30 requests before every
arm, errored arms recorded, baseline tokens via `token_cost`, `errored_runs`); baseline reader 5xx retry; the `_release` MCP
cleanup extracted into a testable method + regression test; the injected deployment no longer tagged `fault_injection`
(their branch still had that leak). The benchmark's full / no-critic arms now pass `agent_names` explicitly = all four
specialists (triage would otherwise change what is measured). **The `/research` numbers were measured on my branch BEFORE triage
existed; triage and a leave-one-out arm are NOT yet benchmarked.** Tests after merge: tests 61, evaluation 25, orchestrator
logic/budget/triage/verification/recovery 83 (incl. evaluation), agents 35, mcp 24 (needs the shop reset first: the live DB
must hold the 10 seed orders), MCP-release 1; dashboard `tsc -b` clean.

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

## Critic fix + harness-leak fix + re-benchmark (2026-10-13) — implemented + tested; supersedes the benchmark numbers below
Reading the abstained incidents' stored critic verdicts showed the cause: the critic demanded evidence no tool can return
(stack traces, spans, CPU/mem), treated partial failure as a contradiction, and `get_git_diff` crashed on Windows
(cp1252 decode) so the diff was missing. Fixes: git tool decodes UTF-8 (+test); critic prompt lists the real MCP tools
(`AVAILABLE_TOOLS`, test keeps it in sync), may only request obtainable evidence, records the rest in
`unobtainable_evidence`, and partial failure is not a contradiction; orchestrator stops the loop when the critic repeats
a request or asks for nothing obtainable (`_stalled`, 3 tests). Found a **harness leak**: `/admin/*` calls were recorded
in production logs/traces/metrics and the injected deployment was tagged `fault_injection`; both removed (+tests).
**Clean benchmark** `evaluation/results/2026-10-13T17-28-19Z.json` (5 scenarios, 1 run/arm, 0 errors): single agent 80%
correct / 2.4k tokens; full NEXUS 80% / 0 false / 0 abstained / 70k tokens / 51s; no critic 40% / 23k tokens. The no-critic
drop is the Evidence Agent ranking "DB is healthy"-style statements first. The previous run (with the leak) had no-critic
at 80% and full NEXUS at 40%, so results swing run to run; ONE run per arm cannot rank arms. Superseded reports are kept as
`SUPERSEDED_*`. Cost: ~$0.07 per full benchmark (balance 0.81 -> 0.74). `/research` + `benchmark.json` refreshed.
**Still open**: repeat runs (3x ~ $0.20) for variance; live recovery approve/execute/verify check; resource telemetry.

## Research page `/research` (2026-10-13) — implemented; `tsc -b` clean; rendered in browser (desktop only, mobile not checked)
Dashboard-only, separate from `/presentation`. `pages/ResearchPage.tsx` + `.module.css`, route in `App.tsx`, "Research"
nav link. Sections: Research question (arms table + per-scenario outcomes from `src/data/benchmark.json`), Design
sequence (11 steps from `orchestrator/investigation.py` + `recovery.py`), Safety net (8 layers + known gaps),
Methodology (design, procedure, scenarios, measures, analysis plan, threats to validity), How it improved (9 fixes + before/after). Text enlarged after the user
reported it was too small. Proposed arms show "Not yet measured". The benchmark JSON is a static copy; refresh it by
hand after a new run.

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
