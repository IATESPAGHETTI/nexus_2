# Held-out experiment (2026-10-18/19): Gemini free tier, 126 valid runs, complete

**Read this first.** One provider (Gemini `gemini-3.5-flash-lite`), one pass over 9 held-out scenarios x 7 arms x 2 repeats. NOT comparable with `EVALUATION_RESULTS_2026-10-16.md` (DeepSeek, different scenarios).

## What was run
- Scenarios: the 8 held-out faults (5 reworded, 3 two-fault) + a reworded healthy control (`fault_injection/scenarios.py::HOLDOUT_*`); prompts, triage and scorer frozen at commit `392b5d7`.
- All 126 planned runs finished and are valid (0 invalid). The free tier allows 15 requests per minute and 500 per day per model per key, so the run used the owner's three Gemini keys in turn
  (same model for all); the runner switched keys when a daily quota ran out and redid the runs that had come back empty. The same model was used throughout, so the runs are comparable. Nothing was estimated or filled in.
- The run was done in two sessions (52 runs, then 74), which is why the log shows quota stops; the earlier 13 empty runs from the first quota stop were discarded and redone.

## How to read the numbers
- Each arm has 18 runs (9 scenarios x 2). **One run is 5-6 percentage points.** Differences between the multi-agent arms (62-75%) are within noise; do not rank them.
- The one difference that is large enough to mention: the single-agent baseline (94%) scored higher than every multi-agent arm (62-75%) on these scenarios, at about a sixth of the tokens and a fifth of the time. This matches the DeepSeek result: on simulated faults that one evidence snapshot makes easy, extra agents did not add accuracy. The value of the multi-agent system here is the audit trail, human approval and interoperability, not accuracy.
- Hardest scenarios for the multi-agent arms: `HO-reworded-db-slowdown` (0-1 of 2 correct for 6 of 7 arms) and `HO-two-faults-deploy-db` (0 of 2 for 5 arms; usually "unknown"). The baseline got both right.
- Healthy control: 100% for the baseline, `hub_analysis_tools` and `hub_crewai_both`; **50% (1 of 2) for hub, hub without critic, blackboard and pipeline**, i.e. in one of two runs those arms named a fault on a healthy shop. This is a real false-alarm weakness, from a sample of two, and replaces the earlier (partial) page's 100%.
- Repeatability (same scenario twice): hub_default is lowest at 0.44, so its answers vary most from run to run.
- Two-fault scenarios accept either injected cause as correct (`"a|b"` truth). Models differ between result files and must not be mixed.
- Cost is an estimate (list price); the account balance did not change at 2-decimal resolution, as Gemini was on the free tier.

## Per-arm results

| Arm | Runs (invalid) | Accuracy | False dx | Abstain | Control OK | Time s (mean±sd) | Tokens (mean±sd) | Calls | Est $/run |
|---|---|---|---|---|---|---|---|---|---|
| baseline_single_agent | 18 (0) | 94% | 0% | 6% | 100% | 2.2±1.8 | 2929±120 | 1.0 | 0.0009 |
| hub_default | 18 (0) | 75% | 0% | 12% | 50% | 12.1±7.6 | 18859±11102 | 8.3 | 0.0062 |
| hub_no_critic | 18 (0) | 69% | 6% | 0% | 50% | 9.7±6.4 | 14533±7944 | 7.4 | 0.0048 |
| blackboard | 18 (0) | 62% | 12% | 0% | 50% | 10.4±1.6 | 18691±9489 | 8.4 | 0.0062 |
| pipeline | 18 (0) | 69% | 0% | 0% | 50% | 18.3±14.2 | 17148±9306 | 8.3 | 0.0057 |
| hub_analysis_tools | 18 (0) | 75% | 6% | 0% | 100% | 9.9±1.1 | 16584±6820 | 8.6 | 0.0056 |
| hub_crewai_both | 18 (0) | 75% | 0% | 6% | 100% | 11.6±4.6 | 16565±8539 | 8.2 | 0.0055 |

## Comparisons the arms answer

- **baseline_single_agent**: one model call over a flat evidence snapshot, no tools, no critic -> pattern: single agent vs multi-agent
- **hub_default**: hub-and-spoke, default prompts, ADK critic (the shipped system) -> reference
- **hub_no_critic**: hub-and-spoke, critic skipped (ablation) -> pattern: reflection/critic
- **blackboard**: shared blackboard topology, default prompts -> messaging: hub-and-spoke vs blackboard
- **pipeline**: sequential hand-off over the board: Metrics first, the others told what it found -> messaging: hub vs blackboard vs pipeline (hand-off)
- **hub_analysis_tools**: default plus the second MCP server (runbook parser, calculator, latency statistics) -> tools: one MCP server vs two
- **hub_crewai_both**: CrewAI Evidence Agent AND CrewAI Critic (ADK specialists) -> framework: ADK vs CrewAI for two agents

## Repeatability (same scenario, repeated)

- baseline_single_agent: 0.889 (9 scenarios repeated)
- hub_default: 0.444 (9 scenarios repeated)
- hub_no_critic: 0.778 (9 scenarios repeated)
- blackboard: 0.889 (9 scenarios repeated)
- pipeline: 0.778 (9 scenarios repeated)
- hub_analysis_tools: 0.889 (9 scenarios repeated)
- hub_crewai_both: 0.778 (9 scenarios repeated)

## Per-scenario outcomes (correct runs / runs)

| Scenario | baseline_single_agent | hub_default | hub_no_critic | blackboard | pipeline | hub_analysis_tools | hub_crewai_both |
|---|---|---|---|---|---|---|---|
| HO-reworded-db-slowdown | 2/2 | 1/2 | 0/2 | 0/2 | 0/2 | 0/2 | 1/2 |
| HO-reworded-bad-deployment | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 1/2 |
| HO-reworded-config-error | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 |
| HO-reworded-dependency-failure | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 |
| HO-reworded-resource-exhaustion | 1/2 | 1/2 | 1/2 | 0/2 | 2/2 | 2/2 | 2/2 |
| HO-two-faults-db-dependency | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 |
| HO-two-faults-deploy-db | 2/2 | 1/2 | 0/2 | 0/2 | 0/2 | 0/2 | 0/2 |
| HO-two-faults-resource-dependency | 2/2 | 1/2 | 2/2 | 2/2 | 1/2 | 2/2 | 2/2 |
| HO-healthy-control | 2/2 | 1/2 | 1/2 | 1/2 | 1/2 | 2/2 | 2/2 |

## Caveats

- Small sample: with few repeats per scenario a difference of one run is within noise; do not read rankings as significant.
- Prompts, guardrail logic and the Critic were tuned earlier on these same five scenarios; held-out scenarios are needed before claiming accuracy.
- Scenario text given to the agents is symptom-only (fault_injection/scenarios.py `blind_symptom`); the ground truth is read only for scoring.
- Triage chooses which specialists are called from the symptom text, so arms call different numbers of agents.
- Recovery calls are excluded from every arm (trigger_recovery=False), so token totals cover diagnosis only.
- Latency includes provider rate-limit retries and shared-machine noise.
- Runs whose agents reported errors (for example provider rate limits) were retried; runs still failing are listed as invalid and excluded from accuracy.
