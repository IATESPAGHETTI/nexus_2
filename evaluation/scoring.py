"""Pure scoring functions (docs/EVALUATION.md metrics) -- no network, no LLM.

Ground truth only ever enters here as a parameter passed in by
run_experiment.py (which reads it from fault_injection/scenarios.py); this
module has no import of scenarios.py itself, so it cannot accidentally leak
ground truth into a diagnosis path -- it only ever compares two already-known
strings after the fact.
"""

from __future__ import annotations

# Root-cause keyword vocabulary used to classify a free-text NEXUS Hypothesis
# statement into one of the fixed fault-type labels -- the only place NEXUS's
# ADK agents' free-text output is mapped onto the same closed vocabulary the
# single-agent baseline is asked to answer in directly. Never fed back into
# any agent prompt.
ROOT_CAUSE_KEYWORDS = {
    "bad_deployment": ("deploy", "release", "version", "rollout"),
    "db_slowdown": ("database", "db ", "query", "sql", "slow"),
    "config_error": ("config", "configuration", "setting", "pool size"),
    "dependency_failure": ("dependency", "downstream", "payment-service", "timeout"),
    "resource_exhaustion": ("resource", "memory", "cpu", "exhaust", "capacity"),
}


# A statement that says no cause was found must never be credited as a diagnosis just
# because it mentions a fault word ("no root cause for a database slowdown is supported").
NEGATION_MARKERS = (
    "no root cause", "not supported", "no supported", "cannot determine", "unable to determine",
    "insufficient evidence", "no evidence of", "not reproducible", "no fault",
)


def classify_statement(statement: str | None) -> str:
    """Best-effort classification of a NEXUS Hypothesis's free-text statement
    into the closed root-cause vocabulary, for scoring only. Returns
    "unknown" if no keyword matches -- never guesses."""
    if not statement:
        return "unknown"
    lowered = statement.lower()
    if any(marker in lowered for marker in NEGATION_MARKERS):
        return "unknown"
    for root_cause, keywords in ROOT_CAUSE_KEYWORDS.items():
        if any(kw in lowered for kw in keywords):
            return root_cause
    return "unknown"


def score_run(predicted_root_cause: str, ground_truth_root_cause: str, abstained: bool) -> dict:
    """One run's scoring record. `predicted_root_cause` is "unknown" for an
    abstention or an unclassifiable statement -- both are "no diagnosis
    made", which is correctness-neutral (not counted as a false diagnosis)
    but also not counted as a correct one."""
    made_a_diagnosis = predicted_root_cause != "unknown" and not abstained
    correct = made_a_diagnosis and predicted_root_cause == ground_truth_root_cause
    false_diagnosis = made_a_diagnosis and predicted_root_cause != ground_truth_root_cause
    return {
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
        "errored_runs": sum(1 for r in records if r.get("error")),
    }
