# Experiment matrix results (2026-10-16): topology, prompting, critic framework, single-agent baseline

Raw output of `evaluation/run_matrix.py` (144 live runs, DeepSeek, blind symptom-only scenarios, 3 repeats, healthy control included),
re-scored with the final scorer (`--report-only`). Per-run data: `evaluation/results/matrix-20261016*.jsonl` (git-ignored; regenerate with the runner).

## How to read it (honest interpretation)

- **Sample size.** 18 runs per arm (15 fault runs + 3 control). One run is ~5-7 percentage points, and a 95% interval around 80% is roughly
  +/-18 points. Differences of a few runs between arms are NOT statistically meaningful; only the large gaps (e.g. few-shot 40%) are suggestive.
- **The single-agent baseline did very well (87%) and was ~15x cheaper and ~12x faster.** On these five simulated faults the evidence is
  easy to read from one flat snapshot, so a multi-agent system has little room to add accuracy. The multi-agent value that IS demonstrated is
  auditability (evidence ids, per-agent tool calls, critic challenge, provenance, human-approved recovery), not accuracy on these scenarios.
- **The critic did not improve accuracy here.** Without the critic (`hub_no_critic`) accuracy was 100% with no abstentions; with it, 80%
  with 13% false diagnoses and 7% abstention. See the offline critic analysis below: the gap is not significant (p = 0.16) and sits almost entirely in one ambiguous scenario.
  The healthy control was handled correctly by every arm except ReAct (2 of 3), so the critic's possible benefit (avoiding false positives)
  is not visible in this data either.
- **Blackboard vs hub-and-spoke:** 67% vs 80% accuracy, 22 s vs 18 s, 11.6 vs 11.0 model calls: no reliable difference at this sample size.
  The blackboard's measurable cost is extra board round trips; its benefit is that agents share state they read themselves.
- **Prompting:** few-shot was worst (40%, mostly abstentions); ReAct and persona did not beat the default. Prompts were tuned earlier on these
  scenarios with the default wording, so the default has an advantage.
- **CrewAI critic vs ADK critic:** identical accuracy (80%) and similar cost: the framework boundary (A2A between ADK and CrewAI) works and does not change behaviour.
- **Hardest scenario:** resource exhaustion (1 of 3 for most arms). Repeatability across repeats of the same scenario was low for the variant arms (0.33-0.67).
- **Cost.** Estimates below use deepseek-flash PEAK list price and are an upper bound; the measured account balance fell by ~$0.40 for the first 111 runs
  (~$0.004/run), about a third of the estimate. Time is wall-clock and includes provider latency.
- **Scorer.** The first scorer mislabelled correct configuration diagnoses (keyword order bug) and a statement that only ruled causes out. Both were fixed
  and tested on the real statements, and every run was re-scored by the same final scorer. Abstention counts as "not correct" and not as a false diagnosis.
- **Not measured:** recovery success (recovery is excluded from every arm), held-out scenarios, other models, concurrent load.

## Critic analysis (offline, from the 126 stored investigations; no model calls)

Pooling the two critic arms (ADK and CrewAI critic, 30 fault runs) against the no-critic arm (15 fault runs):

| | Correct | Wrong or abstained |
|---|---|---|
| With critic | 24 (80%) | 6 |
| Without critic | 15 (100%) | 0 |

Fisher exact test, two-sided: p = 0.16. **The gap is not statistically significant**, and 5 of the 6 failures are in one ambiguous scenario
(resource exhaustion: critic arms 2/6, no-critic 3/3; every other scenario differs by at most one run).

What the stored runs show:
- **The critic mostly approves.** Of 39 verdicts, 28 were SUPPORTED, 7 INSUFFICIENT_EVIDENCE, 2 REQUEST_MORE_EVIDENCE, 2 CONTRADICTED.
- **When it approved on the first review** (23 runs) the diagnosis was right 21 times (91%). **When it asked for more evidence and the loop ran again**
  (7 runs) it was right 3 times (43%). Re-evaluation is where accuracy drops; ambiguous cases enter the loop and the loop did not rescue them.
- **It can approve a wrong hypothesis.** Examples: resource exhaustion approved as "database slowdown" (a latency step-change was real but the 500s
  carried a memory error); a database slowdown approved as a dependency failure. A critic that only checks "does anything in the pool contradict this?"
  cannot catch a wrong cause that is consistent with the evidence it was shown.
- **It still asks for evidence no tool can return** (memory/GC time series, connection-pool statistics) even though its prompt lists what exists,
  which produced the 3-loop abstentions on resource exhaustion.
- A mechanism that would test the system's weakest point: give the critic an explicit alternative-hypothesis check (e.g. "which different cause would
  also explain this evidence, and what discriminating tool call separates them?"). Not implemented; it would need new live runs to evaluate.

Limits: n is small, the Evidence Agent's sampling varies run to run (so "critic effect" is confounded with sampling noise), and the one
scenario driving the gap is also the one with the least clear evidence in this simulator.

## Scorer fix (2026-10-18)
After this document was first written, the scorer was corrected twice: statements that only RULE a cause out no longer count as naming it (2026-10-16), and a statement that says
"nothing is wrong" is now recognised as `healthy` instead of being read as a fault because it mentions "database" or "latency" (2026-10-18). All 144 runs were re-scored with the
final scorer. The only visible change in this set: `hub_persona_sre` false diagnoses 13% -> 7%. The conclusions in this document did not change.

## Generated report
Code version: `6d3b4ea` (prompts, triage rules and scorer are as of this commit).
Runtime: `deepseek/deepseek-chat`. Scenarios: FI-bad-deployment, FI-config-error, FI-db-slowdown, FI-dependency-failure, FI-resource-exhaustion, CTRL-healthy. Repeats per scenario/arm: 3.
Cost is an ESTIMATE: tokens x list price (in $0.3/M, out $1.2/M; deepseek-flash peak price, an assumption because deepseek-chat is not on the pricing page).

## Per-arm results

| Arm | Runs (invalid) | Accuracy | False dx | Abstain | Control OK | Time s (mean±sd) | Tokens (mean±sd) | Calls | Est $/run |
|---|---|---|---|---|---|---|---|---|---|
| baseline_single_agent | 18 (0) | 87% | 7% | 7% | 100% | 1.5±0.4 | 2463±151 | 1.0 | 0.0008 |
| hub_default | 18 (0) | 80% | 13% | 7% | 100% | 17.6±12.3 | 35178±22911 | 11.0 | 0.0123 |
| hub_no_critic | 18 (0) | 100% | 0% | 0% | 100% | 10.2±1.4 | 25401±5875 | 7.3 | 0.0085 |
| blackboard | 18 (0) | 67% | 7% | 20% | 100% | 22.1±17.4 | 41170±33477 | 11.6 | 0.0146 |
| hub_react | 18 (0) | 67% | 7% | 7% | 67% | 18.9±14.5 | 38078±24559 | 10.9 | 0.0134 |
| hub_fewshot | 18 (0) | 40% | 13% | 40% | 100% | 21.1±14.8 | 44372±32278 | 12.4 | 0.0155 |
| hub_persona_sre | 18 (0) | 60% | 7% | 13% | 100% | 16.5±7.9 | 33777±19702 | 9.3 | 0.0117 |
| hub_crewai_critic | 18 (0) | 80% | 13% | 7% | 100% | 17.3±12.0 | 32296±19717 | 10.0 | 0.0108 |

## Comparisons the arms answer

- **baseline_single_agent**: one model call over a flat evidence snapshot, no tools, no critic -> pattern: single agent vs multi-agent
- **hub_default**: hub-and-spoke, default prompts, ADK critic (the shipped system) -> reference
- **hub_no_critic**: hub-and-spoke, critic skipped (ablation) -> pattern: reflection/critic
- **blackboard**: shared blackboard topology, default prompts -> messaging: hub-and-spoke vs blackboard
- **hub_react**: ReAct-style prompting (architecture variance) -> prompting: ReAct vs default
- **hub_fewshot**: few-shot prompting (architecture variance) -> prompting: few-shot vs default
- **hub_persona_sre**: senior-SRE persona (content variance) -> prompting: persona vs default
- **hub_crewai_critic**: hub-and-spoke with the CrewAI critic (ADK <-> CrewAI over A2A) -> framework: ADK critic vs CrewAI critic

## Repeatability (same scenario, repeated)

- baseline_single_agent: 0.833 (6 scenarios repeated)
- hub_default: 0.667 (6 scenarios repeated)
- hub_no_critic: 1.0 (6 scenarios repeated)
- blackboard: 0.5 (6 scenarios repeated)
- hub_react: 0.333 (6 scenarios repeated)
- hub_fewshot: 0.333 (6 scenarios repeated)
- hub_persona_sre: 0.333 (6 scenarios repeated)
- hub_crewai_critic: 0.667 (6 scenarios repeated)

## Per-scenario outcomes (correct runs / runs)

| Scenario | baseline_single_agent | hub_default | hub_no_critic | blackboard | hub_react | hub_fewshot | hub_persona_sre | hub_crewai_critic |
|---|---|---|---|---|---|---|---|---|
| FI-bad-deployment | 3/3 | 3/3 | 3/3 | 1/3 | 2/3 | 1/3 | 2/3 | 3/3 |
| FI-config-error | 3/3 | 3/3 | 3/3 | 2/3 | 3/3 | 1/3 | 1/3 | 3/3 |
| FI-db-slowdown | 3/3 | 3/3 | 3/3 | 3/3 | 1/3 | 3/3 | 2/3 | 2/3 |
| FI-dependency-failure | 3/3 | 2/3 | 3/3 | 3/3 | 3/3 | 1/3 | 3/3 | 3/3 |
| FI-resource-exhaustion | 1/3 | 1/3 | 3/3 | 1/3 | 1/3 | 0/3 | 1/3 | 1/3 |
| CTRL-healthy | 3/3 | 3/3 | 3/3 | 3/3 | 2/3 | 3/3 | 3/3 | 3/3 |

## Caveats

- Small sample: with few repeats per scenario a difference of one run is within noise; do not read rankings as significant.
- Prompts, guardrail logic and the Critic were tuned earlier on these same five scenarios; held-out scenarios are needed before claiming accuracy.
- Scenario text given to the agents is symptom-only (fault_injection/scenarios.py `blind_symptom`); the ground truth is read only for scoring.
- Triage chooses which specialists are called from the symptom text, so arms call different numbers of agents.
- Recovery calls are excluded from every arm (trigger_recovery=False), so token totals cover diagnosis only.
- Latency includes provider rate-limit retries and shared-machine noise.
- Runs whose agents reported errors (for example provider rate limits) were retried; runs still failing are listed as invalid and excluded from accuracy.
