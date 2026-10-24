"""Pure scoring functions (docs/EVALUATION.md metrics) -- no network, no LLM.

Ground truth only ever enters here as a parameter passed in by
run_experiment.py (which reads it from fault_injection/scenarios.py); this
module has no import of scenarios.py itself, so it cannot accidentally leak
ground truth into a diagnosis path -- it only ever compares two already-known
strings after the fact.
"""

from __future__ import annotations

import re

# Root-cause keyword vocabulary used to classify a free-text NEXUS Hypothesis
# statement into one of the fixed fault-type labels -- the only place NEXUS's
# ADK agents' free-text output is mapped onto the same closed vocabulary the
# single-agent baseline is asked to answer in directly. Never fed back into
# any agent prompt.
ROOT_CAUSE_KEYWORDS = {
    "config_error": ("config", "setting", "pool_size", "pool size", "invalid value"),
    "dependency_failure": ("dependency", "downstream", "upstream", "payment", "timeout", "unreachable"),
    "resource_exhaustion": ("resource", "memory", "cpu", "exhaust", "capacity", "out of memory"),
    "bad_deployment": ("deploy", "release", "rollout", "rollback", "new version", "code change"),
    "db_slowdown": ("database", "db ", "query", "queries", "sql", "slow"),  # "latency" is too generic: every cause mentions it
}
# More specific causes win ties: a configuration fault is usually described with database words ("DB_POOL_SIZE"),
# but a slow database is never described with configuration words except to rule them out.
_PRIORITY = ("config_error", "dependency_failure", "resource_exhaustion", "bad_deployment", "db_slowdown")

# Clauses that mention a cause only to exclude it ("no deployment", "not a config issue", "rather than a timeout").
_NEGATED = re.compile(
    r"\b(no|not|without|neither|nor|rather than|instead of|ruled out|rules out|ruling out|rule out|excludes|excluded|unrelated to|excluding|isn't|wasn't)\b[^.;:]{0,60}",
    re.IGNORECASE,
)


# A hypothesis can also say that NOTHING is wrong ("operating normally ... zero errors"). That is the correct answer on a healthy
# shop, so it must not be scored as a fault diagnosis just because it mentions "database" or "latency".
_HEALTH_RE = re.compile(
    r"\b(operating|running|performing|functioning|behaving)\s+(\w+\s+)?(normally|nominally|as expected)\b"
    r"|\b(is|are)\s+healthy\b|\bno\s+(issues?|problems?|anomal(y|ies)|incident|degradation|signs?\s+of)\b|\bnothing\s+(is\s+)?wrong\b",
    re.IGNORECASE,
)
_FAULT_SIGNALS = (
    "step change", "slowdown", "slow quer", "slower", "slowed", "degrad", "spike", "failing", "fails", "failure", "unreachable",
    "timed out", "timeout", "exhaust", "misconfig", "regression", "bug", "increase", "elevated", "jump",
)


def classify_statement(statement: str | None) -> str:
    """Best-effort classification of a NEXUS Hypothesis's free-text statement into the closed root-cause
    vocabulary, for scoring only (never fed back into any agent). Counts distinct keyword hits per cause after
    removing clauses that only rule a cause out; the cause with the most hits wins, ties go to the more specific
    cause. Returns "unknown" when nothing matches -- never guesses."""
    if not statement:
        return "unknown"
    lowered = _NEGATED.sub(" ", statement.lower())
    if _HEALTH_RE.search(statement) and not any(sig in lowered for sig in _FAULT_SIGNALS):
        return "healthy"          # the model says nothing is wrong
    scores = {cause: sum(1 for kw in kws if kw in lowered) for cause, kws in ROOT_CAUSE_KEYWORDS.items()}
    best = max(scores.values())
    if best == 0:
        return "unknown"
    return next(cause for cause in _PRIORITY if scores[cause] == best)


def score_run(predicted_root_cause: str, ground_truth_root_cause: str, abstained: bool) -> dict:
    """One run's scoring record. `predicted_root_cause` is "unknown" for an
    abstention or an unclassifiable statement -- both are "no diagnosis
    made", which is correctness-neutral (not counted as a false diagnosis)
    but also not counted as a correct one."""
    made_a_diagnosis = predicted_root_cause not in ("unknown", "healthy") and not abstained
    acceptable = set(ground_truth_root_cause.split("|"))       # "a|b" = two simultaneous faults, either diagnosis is accepted
    if ground_truth_root_cause == "none":  # healthy control: the only correct answer is "no cause found"
        correct = not made_a_diagnosis
        false_diagnosis = made_a_diagnosis
    else:
        correct = made_a_diagnosis and predicted_root_cause in acceptable
        false_diagnosis = made_a_diagnosis and predicted_root_cause not in acceptable
    return {
        "declared_healthy": predicted_root_cause == "healthy" and not abstained,
        "predicted_root_cause": predicted_root_cause,
        "ground_truth_root_cause": ground_truth_root_cause,
        "abstained": abstained,
        "made_a_diagnosis": made_a_diagnosis,
        "correct": correct,
        "false_diagnosis": false_diagnosis,
    }


TOKEN_COST_UNAVAILABLE = "Unavailable from provider"


def token_cost(incident: dict | None):
    """Measured model usage for one investigation, from `incident.token_usage`
    (orchestrator/budget.py). Never estimated: with no recorded usage this stays
    the old "Unavailable from provider" text. `unmeasured_tasks` > 0 means some
    agent tasks reported no token counts, so `total_tokens` is a lower bound."""
    usage = (incident or {}).get("token_usage") or {}
    total = usage.get("total")
    if not isinstance(total, dict) or not total.get("llm_calls"):
        return TOKEN_COST_UNAVAILABLE
    return {
        "llm_calls": total.get("llm_calls", 0),
        "total_tokens": total.get("total_tokens", 0),
        "unmeasured_tasks": usage.get("unmeasured_tasks", 0),
    }


def aggregate(records: list[dict]) -> dict:
    total = len(records)
    if total == 0:
        return {"total_runs": 0}
    controls = [r for r in records if r.get("ground_truth_root_cause") == "none"]
    if controls:  # healthy-control runs are reported separately so they never inflate or deflate fault accuracy
        faults = [r for r in records if r.get("ground_truth_root_cause") != "none"]
        out = aggregate(faults) if faults else {"total_runs": 0}
        out["control_runs"] = len(controls)
        out["control_correct_rate"] = round(sum(1 for r in controls if r["correct"]) / len(controls), 3)
        out["control_false_diagnosis_rate"] = round(sum(1 for r in controls if r["false_diagnosis"]) / len(controls), 3)
        return out
    diagnosed = [r for r in records if r["made_a_diagnosis"]]
    abstained = [r for r in records if r["abstained"]]
    costs = [r["token_cost"] for r in records if isinstance(r.get("token_cost"), dict)]
    token_summary = (
        {
            "runs_with_token_data": len(costs),
            "avg_llm_calls": round(sum(c["llm_calls"] for c in costs) / len(costs), 1),
            "avg_total_tokens": round(sum(c["total_tokens"] for c in costs) / len(costs)),
        }
        if costs
        else {}
    )
    return {
        **token_summary,
        "total_runs": total,
        "root_cause_accuracy": round(sum(1 for r in records if r["correct"]) / total, 3),
        "false_diagnosis_rate": round(sum(1 for r in records if r["false_diagnosis"]) / total, 3),
        "abstention_rate": round(len(abstained) / total, 3),
        "diagnosis_rate": round(len(diagnosed) / total, 3),
        "avg_latency_seconds": round(sum(r.get("latency_seconds", 0.0) for r in records) / total, 3),
    }
