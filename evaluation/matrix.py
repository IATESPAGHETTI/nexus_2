"""Experiment matrix (course requirements 1, 4, 8, 10): arm definitions, per-arm statistics, cost estimate, report.

Pure functions only (no network, no model), so the arithmetic is unit-tested. `run_matrix.py` does the live runs.

An ARM is one way of running the same blind scenarios:
  agent_env   environment the agent SERVICES must be started with (prompt variant, critic framework, guardrails)
  run_env     environment of the orchestrator process (topology)
  kind        "nexus" (full investigation) or "baseline" (one model call, no tools)
Arms that share the same agent_env share one set of agent processes, so services restart only when it changes.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field

DEFAULT_PRICE_IN_PER_M = 0.30   # USD per 1M prompt tokens   -- deepseek-flash PEAK list price (assumption, see report)
DEFAULT_PRICE_OUT_PER_M = 1.20  # USD per 1M completion tokens


@dataclass(frozen=True)
class Arm:
    name: str
    description: str
    kind: str = "nexus"
    agent_env: tuple = ()
    run_env: tuple = ()
    skip_critic: bool = False
    compares: str = ""  # which question this arm helps answer

    def agent_env_dict(self) -> dict:
        return dict(self.agent_env)

    def run_env_dict(self) -> dict:
        return dict(self.run_env)


ARMS: list[Arm] = [
    Arm("baseline_single_agent", "one model call over a flat evidence snapshot, no tools, no critic", kind="baseline",
        compares="pattern: single agent vs multi-agent"),
    Arm("hub_default", "hub-and-spoke, default prompts, ADK critic (the shipped system)", compares="reference"),
    Arm("hub_no_critic", "hub-and-spoke, critic skipped (ablation)", skip_critic=True, compares="pattern: reflection/critic"),
    Arm("blackboard", "shared blackboard topology, default prompts", run_env=(("NEXUS_TOPOLOGY", "blackboard"),),
        compares="messaging: hub-and-spoke vs blackboard"),
    Arm("hub_react", "ReAct-style prompting (architecture variance)", agent_env=(("NEXUS_PROMPT_VARIANT", "react"),),
        compares="prompting: ReAct vs default"),
    Arm("hub_fewshot", "few-shot prompting (architecture variance)", agent_env=(("NEXUS_PROMPT_VARIANT", "fewshot"),),
        compares="prompting: few-shot vs default"),
    Arm("hub_persona_sre", "senior-SRE persona (content variance)", agent_env=(("NEXUS_PROMPT_VARIANT", "persona_sre"),),
        compares="prompting: persona vs default"),
    Arm("pipeline", "sequential hand-off over the board: Metrics first, the others told what it found",
        run_env=(("NEXUS_TOPOLOGY", "pipeline"),), compares="messaging: hub vs blackboard vs pipeline (hand-off)"),
    Arm("hub_analysis_tools", "default plus the second MCP server (runbook parser, calculator, latency statistics)",
        agent_env=(("NEXUS_ENABLE_ANALYSIS_TOOLS", "1"),), compares="tools: one MCP server vs two"),
    Arm("hub_crewai_both", "CrewAI Evidence Agent AND CrewAI Critic (ADK specialists)",
        agent_env=(("NEXUS_CRITIC_FRAMEWORK", "crewai"), ("NEXUS_EVIDENCE_FRAMEWORK", "crewai")),
        run_env=(("NEXUS_CRITIC_FRAMEWORK", "crewai"), ("NEXUS_EVIDENCE_FRAMEWORK", "crewai")),
        compares="framework: ADK vs CrewAI for two agents"),
    Arm("hub_crewai_critic", "hub-and-spoke with the CrewAI critic (ADK <-> CrewAI over A2A)",
        agent_env=(("NEXUS_CRITIC_FRAMEWORK", "crewai"),), run_env=(("NEXUS_CRITIC_FRAMEWORK", "crewai"),),
        compares="framework: ADK critic vs CrewAI critic"),
]
ARMS_BY_NAME = {a.name: a for a in ARMS}


def group_by_agent_env(arms: list[Arm]) -> list[tuple[tuple, list[Arm]]]:
    """Arms grouped so the agent services restart only when their environment actually differs."""
    groups: dict[tuple, list[Arm]] = {}
    for arm in arms:
        groups.setdefault(tuple(sorted(arm.agent_env)), []).append(arm)
    return list(groups.items())


# ---------------------------------------------------------------- statistics


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def stdev(values: list[float]) -> float:
    """Sample standard deviation (n-1); 0.0 for fewer than two values."""
    if len(values) < 2:
        return 0.0
    m = mean(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / (len(values) - 1))


def estimate_cost_usd(prompt_tokens: int, completion_tokens: int, price_in: float | None = None, price_out: float | None = None) -> float:
    price_in = DEFAULT_PRICE_IN_PER_M if price_in is None else price_in
    price_out = DEFAULT_PRICE_OUT_PER_M if price_out is None else price_out
    return prompt_tokens / 1e6 * price_in + completion_tokens / 1e6 * price_out


def run_tokens(record: dict) -> dict:
    """prompt/completion/total/calls for one run record, whatever the arm kind reported."""
    cost = record.get("token_cost")
    if isinstance(cost, dict):
        prompt = cost.get("prompt_tokens") or 0
        completion = cost.get("completion_tokens") or 0
        total = cost.get("total_tokens") or (prompt + completion)
        return {"prompt": prompt, "completion": completion, "total": total, "calls": cost.get("llm_calls", 0)}
    return {"prompt": 0, "completion": 0, "total": 0, "calls": 0}


def summarize_arm(records: list[dict], price_in: float | None = None, price_out: float | None = None) -> dict:
    """Per-arm statistics over repeated runs. Fault runs and healthy-control runs are separated."""
    invalid = [r for r in records if r.get("invalid")]
    records = [r for r in records if not r.get("invalid")]     # runs whose agents kept erroring are not evidence about the system
    faults = [r for r in records if r.get("ground_truth_root_cause") != "none"]
    controls = [r for r in records if r.get("ground_truth_root_cause") == "none"]
    lat = [r.get("latency_seconds", 0.0) for r in records]
    toks = [run_tokens(r) for r in records]
    costs = [estimate_cost_usd(t["prompt"], t["completion"], price_in, price_out) for t in toks]
    out = {
        "runs": len(records),
        "invalid_runs": len(invalid),
        "fault_runs": len(faults),
        "accuracy": round(sum(1 for r in faults if r["correct"]) / len(faults), 3) if faults else None,
        "false_diagnosis_rate": round(sum(1 for r in faults if r["false_diagnosis"]) / len(faults), 3) if faults else None,
        "abstention_rate": round(sum(1 for r in faults if r["abstained"]) / len(faults), 3) if faults else None,
        "control_runs": len(controls),
        "control_correct_rate": round(sum(1 for r in controls if r["correct"]) / len(controls), 3) if controls else None,
        "latency_s_mean": round(mean(lat), 1),
        "latency_s_std": round(stdev(lat), 1),
        "tokens_mean": round(mean([t["total"] for t in toks])),
        "tokens_std": round(stdev([t["total"] for t in toks])),
        "llm_calls_mean": round(mean([t["calls"] for t in toks]), 1),
        "est_cost_usd_per_run": round(mean(costs), 5),
        "est_cost_usd_total": round(sum(costs), 4),
    }
    return out


def repeatability(records: list[dict]) -> dict:
    """Of the (scenario) groups run more than once, how often did all repeats give the same predicted root cause?"""
    by_scenario: dict[str, list[str]] = {}
    for r in (x for x in records if not x.get("invalid")):
        by_scenario.setdefault(r["scenario_id"], []).append(r.get("predicted_root_cause", "unknown"))
    multi = {k: v for k, v in by_scenario.items() if len(v) > 1}
    if not multi:
        return {"scenarios_with_repeats": 0, "consistent_fraction": None}
    return {"scenarios_with_repeats": len(multi),
            "consistent_fraction": round(sum(1 for v in multi.values() if len(set(v)) == 1) / len(multi), 3)}


# -------------------------------------------------------------------- report


def render_markdown(report: dict) -> str:
    """Human-readable report from a finished matrix run. Only measured values; every caveat is printed."""
    lines = [
        f"# NEXUS experiment matrix ({report['timestamp']})",
        "",
        f"Code version: `{report.get('commit', 'unknown')}` (prompts, triage rules and scorer are as of this commit).",
        f"Runtime: `{report['runtime']}`. Scenarios: {', '.join(report['scenarios'])}. Repeats per scenario/arm: {report['repeats']}.",
        f"Cost is an ESTIMATE: tokens x list price (in ${report['price_in_per_m']}/M, out ${report['price_out_per_m']}/M; "
        f"deepseek-flash peak price, an assumption because deepseek-chat is not on the pricing page).",
    ]
    if report.get("balance_delta_usd") is not None:
        lines.append(f"Measured account balance change over the whole matrix: ${report['balance_delta_usd']:.2f} "
                     f"(2-decimal resolution; compare with the estimated total ${report['est_cost_usd_total']:.2f}).")
    lines += [
        "", "## Per-arm results", "",
        "| Arm | Runs (invalid) | Accuracy | False dx | Abstain | Control OK | Time s (mean±sd) | Tokens (mean±sd) | Calls | Est $/run |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]

    def pct(x):
        return "n/a" if x is None else f"{x:.0%}"

    for name, s in report["arms"].items():
        lines.append(
            f"| {name} | {s['runs']} ({s.get('invalid_runs', 0)}) | {pct(s['accuracy'])} | {pct(s['false_diagnosis_rate'])} | {pct(s['abstention_rate'])} | "
            f"{pct(s['control_correct_rate'])} | {s['latency_s_mean']}±{s['latency_s_std']} | {s['tokens_mean']}±{s['tokens_std']} | "
            f"{s['llm_calls_mean']} | {s['est_cost_usd_per_run']:.4f} |")
    lines += ["", "## Comparisons the arms answer", ""]
    for name, arm in report["arm_definitions"].items():
        lines.append(f"- **{name}**: {arm['description']} -> {arm['compares'] or 'reference'}")
    lines += ["", "## Repeatability (same scenario, repeated)", ""]
    for name, r in report["repeatability"].items():
        lines.append(f"- {name}: {r['consistent_fraction'] if r['consistent_fraction'] is not None else 'n/a'} "
                     f"({r['scenarios_with_repeats']} scenarios repeated)")
    lines += ["", "## Per-scenario outcomes (correct runs / runs)", "", "| Scenario | " + " | ".join(report["arms"]) + " |",
              "|---|" + "---|" * len(report["arms"])]
    for sid in report["scenarios"]:
        cells = []
        for name in report["arms"]:
            rs = [r for r in report["runs"] if r["arm"] == name and r["scenario_id"] == sid and not r.get("invalid")]
            cells.append(f"{sum(1 for r in rs if r['correct'])}/{len(rs)}" if rs else "-")
        lines.append(f"| {sid} | " + " | ".join(cells) + " |")
    lines += ["", "## Caveats", ""] + [f"- {c}" for c in report["caveats"]]
    return "\n".join(lines) + "\n"


STANDARD_CAVEATS = [
    "Small sample: with few repeats per scenario a difference of one run is within noise; do not read rankings as significant.",
    "Prompts, guardrail logic and the Critic were tuned earlier on these same five scenarios; held-out scenarios are needed before claiming accuracy.",
    "Scenario text given to the agents is symptom-only (fault_injection/scenarios.py `blind_symptom`); the ground truth is read only for scoring.",
    "Triage chooses which specialists are called from the symptom text, so arms call different numbers of agents.",
    "Recovery calls are excluded from every arm (trigger_recovery=False), so token totals cover diagnosis only.",
    "Latency includes provider rate-limit retries and shared-machine noise.",
    "Runs whose agents reported errors (for example provider rate limits) were retried; runs still failing are listed as invalid and excluded from accuracy.",
]
