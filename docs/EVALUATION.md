# NEXUS Evaluation

## Purpose

Quantitatively compare NEXUS against simpler baselines using blind fault-injection
scenarios. Ground truth lives here and in `fault_injection/` — it must never leak into
the diagnostic agents (`agents/metrics`, `logs_traces`, `change_analysis`, `database`,
`evidence`, `critic`).

## Failure classes (minimum)

```text
bad deployment
database slowdown
configuration error
dependency failure
resource exhaustion
```

## Comparison arms (Phase 9)

```text
1. Single-agent baseline
2. Full multi-agent NEXUS
3. Ablation without critic/falsification loop
```

Same blind scenarios and evaluation criteria across all arms. No result manipulation.

## Metrics

```text
root-cause accuracy
evidence accuracy
false diagnosis rate
abstention correctness
diagnosis time
remediation success
tool cost
token cost (reported as `Unavailable from provider` unless Groq returns a
provider value; no quota or token number is inferred)
```

Token cost note: each investigation records measured model usage in
`incident.token_usage` (see `docs/API_CONTRACT.md`). `evaluation/run_experiment.py`
now copies it into each full-NEXUS / no-critic run's `token_cost` (calls, tokens, and
`unmeasured_tasks`; a lower bound if > 0) and `aggregate()` averages it over runs that
have it. With no recorded usage it stays `Unavailable from provider`. The single-agent
baseline does not report usage yet, so it has no token number. Not yet exercised by a
live run.

## Status

Phase 9's fault scenarios, injector, three-arm benchmark runner, and pure
scoring tests are implemented. The runner executes five controlled scenarios
and writes the raw per-run records plus aggregates to `evaluation/results/`.

The first complete live benchmark has not yet been recorded. It is blocked by
the Groq account's exhausted daily token quota (TPD 200000), not substituted
with synthetic output. When quota headroom is available, start the full stack
and run `.venv-orchestrator/Scripts/python evaluation/run_experiment.py`.
Report the generated JSON as the only source for measured evaluation values.

## Notes added 2026-10-13

- **Triage changes what is measured.** `run_investigation` now calls only the diagnostic agents the symptom text points at
  (`orchestrator/triage.py`). Set `NEXUS_TRIAGE=0`, or pass `agent_names`, to call all four. State which was used in any result.
- **Reset between trials.** Use `POST /admin/reset` on the shop before every trial; leftovers from an earlier fault
  (old errors, rollbacks) otherwise act as misleading evidence and invalidate the comparison.
- **Tuning contamination.** The Critic and Logs-agent prompts were adjusted after seeing failures on the five existing
  scenarios. Accuracy must be measured on scenarios not used for that tuning.

First complete live benchmark recorded 2026-10-13 (numbers and the three discarded earlier runs are in
`docs/PROJECT_STATE.md`). One run per arm per scenario, so results are directional. NEXUS arms are scored on the
Evidence Agent's structured `fault_class`; every arm gets a full production reset, fault injection and 30 customer
requests first. Token counts are provider-reported; dollar cost and quota are not computed. Run:
`.venv-orchestrator/Scripts/python evaluation/run_experiment.py` (paid: about 15 model-heavy runs).
