"""Controlled fault scenarios (Phase 9, root CLAUDE.md section 19).

Each scenario's `fault_type` maps 1:1 onto `production/state.py`'s
`FAULT_TYPES` -- the actual mutable flag `injector.py` flips via
`production/service.py`'s `/admin/fault/inject` endpoint (real degraded
behavior, not a fabricated label). `ground_truth_root_cause` and
`recovery_expectation` are the ONLY place this information lives; nothing in
`agents/`, `orchestrator/`, or `guardrails/` ever reads this module (enforced
by dependency isolation -- those packages have no import path to
`fault_injection/`). Only `evaluation/` (scoring, after the fact) is meant to
read `get_ground_truth()`.
"""

from __future__ import annotations

SCENARIOS = [
    {
        "scenario_id": "FI-bad-deployment",
        "blind_symptom": "Orders suddenly started failing with errors for some customers. Investigate the cause.",
        "description": (
            "A new deployment introduces a bug in order total calculation, "
            "causing ~35% of /orders and /orders/{id} requests to fail with a 500."
        ),
        "fault_type": "bad_deployment",
        "injection_method": "POST production/admin/fault/inject {\"fault_type\": \"bad_deployment\"}",
        "expected_symptoms": [
            "elevated 5xx error rate specifically on GET /orders and /orders/{id}",
            "a new deployment entry in /changes at/after the injection time",
            "no db-latency or config-error signal",
        ],
        "ground_truth_root_cause": "bad_deployment",
        "recovery_expectation": "rollback_deployment to the prior known-good version",
    },
    {
        "scenario_id": "FI-db-slowdown",
        "blind_symptom": "Customers report that order requests are responding slowly. Investigate the cause.",
        "description": "The database becomes slow, adding real latency to every query.",
        "fault_type": "db_slowdown",
        "injection_method": "POST production/admin/fault/inject {\"fault_type\": \"db_slowdown\"}",
        "expected_symptoms": [
            "elevated avg_query_ms in /db/diagnostics' query_summary",
            "elevated p99 latency on endpoints that touch the DB (/orders, /orders/{id})",
            "error rate NOT particularly elevated -- this is a latency fault, not an error fault",
        ],
        "ground_truth_root_cause": "db_slowdown",
        "recovery_expectation": "scale_resources (relieve DB-adjacent load) -- no deployment/config change needed",
    },
    {
        "scenario_id": "FI-config-error",
        "blind_symptom": "Every order request is failing with an error right now. Investigate the cause.",
        "description": (
            "A configuration value is invalid (DB_POOL_SIZE=0), causing every "
            "/orders and /orders/{id} request to fail deterministically."
        ),
        "fault_type": "config_error",
        "injection_method": "POST production/admin/fault/inject {\"fault_type\": \"config_error\"}",
        "expected_symptoms": [
            "100% (deterministic, not flaky) error rate on GET /orders and /orders/{id}",
            "log entries containing 'ConfigError: DB_POOL_SIZE'",
            "no new entry in /changes -- distinguishes this from bad_deployment's partial/random errors",
        ],
        "ground_truth_root_cause": "config_error",
        "recovery_expectation": "reset_config",
    },
    {
        "scenario_id": "FI-dependency-failure",
        "blind_symptom": "Looking up a single order takes a long time and then fails. Investigate the cause.",
        "description": "A downstream payment-service dependency becomes unreachable for order-detail lookups.",
        "fault_type": "dependency_failure",
        "injection_method": "POST production/admin/fault/inject {\"fault_type\": \"dependency_failure\"}",
        "expected_symptoms": [
            "elevated latency (~1.5s) and 5xx on GET /orders/{id} specifically, not GET /orders",
            "log entries containing 'DependencyTimeoutError: payment-service unreachable'",
        ],
        "ground_truth_root_cause": "dependency_failure",
        "recovery_expectation": "restart_service",
    },
    {
        "scenario_id": "FI-resource-exhaustion",
        "blind_symptom": "The whole shop is getting slower and sometimes refuses requests. Investigate the cause.",
        "description": "The service runs out of available memory/CPU headroom under load.",
        "fault_type": "resource_exhaustion",
        "injection_method": "POST production/admin/fault/inject {\"fault_type\": \"resource_exhaustion\"}",
        "expected_symptoms": [
            "elevated latency across EVERY endpoint (not just /orders*) -- broad impact distinguishes this from the targeted faults above",
            "log entries containing 'ResourceExhaustedError: memory limit exceeded'",
            "elevated error rate across every endpoint, not just order-related ones",
        ],
        "ground_truth_root_cause": "resource_exhaustion",
        "recovery_expectation": "scale_resources (or restart_service)",
    },
]

# Healthy control (no fault is injected). Ground truth is "none": the correct outcome is to NOT name a cause,
# which is what makes false-diagnosis and abstention-correctness measurable. Kept out of SCENARIOS so the
# "five fault classes" invariant stays true.
CONTROL_SCENARIOS = [
    {
        "scenario_id": "CTRL-healthy",
        "description": "No fault is injected; the shop is healthy.",
        "blind_symptom": "Some customers say the shop might be a little slow today. Investigate the cause.",
        "fault_type": None,
        "injection_method": "none (healthy shop with normal customer traffic)",
        "expected_symptoms": ["normal latency", "no elevated error rate", "no recent bad change"],
        "ground_truth_root_cause": "none",
        "recovery_expectation": "no action needed",
    },
]

# HELD-OUT scenarios (course requirement 10). The prompts, triage rules, critic and scorer were tuned on the five SCENARIOS above, so
# accuracy on those is optimistic. These are NEW: (a) the same five faults described in different customer words, which tests how
# much triage keywords and prompts depend on the exact wording they were tuned on, and (b) two faults at once, where the evidence
# is mixed. `fault_types` lists every fault to inject; `ground_truth_root_cause` is "a|b" when any listed cause is an acceptable
# diagnosis. They must be run with prompts and scorer frozen (record the commit in the results).
HOLDOUT_SCENARIOS = [
    {"scenario_id": "HO-reworded-db-slowdown", "fault_type": "db_slowdown", "fault_types": ["db_slowdown"],
     "description": "Held-out wording of the slow-database fault.",
     "blind_symptom": "Browsing orders feels sluggish today; pages take a while to show up although nothing seems broken. Please find out why.",
     "injection_method": "POST production/admin/fault/inject db_slowdown", "expected_symptoms": ["same as FI-db-slowdown"],
     "ground_truth_root_cause": "db_slowdown", "recovery_expectation": "scale_resources"},
    {"scenario_id": "HO-reworded-bad-deployment", "fault_type": "bad_deployment", "fault_types": ["bad_deployment"],
     "description": "Held-out wording of the bad-release fault.",
     "blind_symptom": "Since this morning some customers get a failure message when they try to place or view an order, while others are fine. What changed?",
     "injection_method": "POST production/admin/fault/inject bad_deployment", "expected_symptoms": ["same as FI-bad-deployment"],
     "ground_truth_root_cause": "bad_deployment", "recovery_expectation": "rollback_deployment"},
    {"scenario_id": "HO-reworded-config-error", "fault_type": "config_error", "fault_types": ["config_error"],
     "description": "Held-out wording of the invalid-setting fault.",
     "blind_symptom": "The orders section stopped working completely for everybody. Even the simplest request now returns an error.",
     "injection_method": "POST production/admin/fault/inject config_error", "expected_symptoms": ["same as FI-config-error"],
     "ground_truth_root_cause": "config_error", "recovery_expectation": "reset_config"},
    {"scenario_id": "HO-reworded-dependency-failure", "fault_type": "dependency_failure", "fault_types": ["dependency_failure"],
     "description": "Held-out wording of the downstream-dependency fault.",
     "blind_symptom": "Opening one specific order makes the page hang for a moment and then show an error. The list of orders still opens fine.",
     "injection_method": "POST production/admin/fault/inject dependency_failure", "expected_symptoms": ["same as FI-dependency-failure"],
     "ground_truth_root_cause": "dependency_failure", "recovery_expectation": "restart_service"},
    {"scenario_id": "HO-reworded-resource-exhaustion", "fault_type": "resource_exhaustion", "fault_types": ["resource_exhaustion"],
     "description": "Held-out wording of the resource-exhaustion fault.",
     "blind_symptom": "Everything on the site has become slow and a few requests are being turned away, not just orders. Can you tell what is wrong?",
     "injection_method": "POST production/admin/fault/inject resource_exhaustion", "expected_symptoms": ["same as FI-resource-exhaustion"],
     "ground_truth_root_cause": "resource_exhaustion", "recovery_expectation": "scale_resources"},
    {"scenario_id": "HO-two-faults-db-dependency", "fault_type": "db_slowdown", "fault_types": ["db_slowdown", "dependency_failure"],
     "description": "Two simultaneous faults: slow database and a failing downstream dependency.",
     "blind_symptom": "Order lists load slowly, and opening a single order is even worse: it hangs and then fails. Please investigate.",
     "injection_method": "POST production/admin/fault/inject db_slowdown, then dependency_failure",
     "expected_symptoms": ["slow queries everywhere", "slow 5xx on single orders"],
     "ground_truth_root_cause": "db_slowdown|dependency_failure", "recovery_expectation": "scale_resources and restart_service"},
    {"scenario_id": "HO-two-faults-deploy-db", "fault_type": "bad_deployment", "fault_types": ["bad_deployment", "db_slowdown"],
     "description": "Two simultaneous faults: a bad release and a slow database.",
     "blind_symptom": "Orders are both slow and failing for some customers right now. Find the cause.",
     "injection_method": "POST production/admin/fault/inject bad_deployment, then db_slowdown",
     "expected_symptoms": ["partial 5xx rate", "elevated latency", "new deployment entry"],
     "ground_truth_root_cause": "bad_deployment|db_slowdown", "recovery_expectation": "rollback_deployment and scale_resources"},
    {"scenario_id": "HO-two-faults-resource-dependency", "fault_type": "resource_exhaustion", "fault_types": ["resource_exhaustion", "dependency_failure"],
     "description": "Two simultaneous faults: resource exhaustion and a failing downstream dependency.",
     "blind_symptom": "The shop is struggling overall and single-order lookups in particular take long and fail. What is going on?",
     "injection_method": "POST production/admin/fault/inject resource_exhaustion, then dependency_failure",
     "expected_symptoms": ["broad slowdown", "slow 5xx on single orders"],
     "ground_truth_root_cause": "resource_exhaustion|dependency_failure", "recovery_expectation": "scale_resources and restart_service"},
]
HOLDOUT_CONTROLS = [
    {"scenario_id": "HO-healthy-control", "fault_type": None, "fault_types": [],
     "description": "Held-out healthy shop with a differently worded worry.",
     "blind_symptom": "A couple of people mentioned the order page felt a bit slow earlier. Is anything wrong?",
     "injection_method": "none", "expected_symptoms": ["normal latency"], "ground_truth_root_cause": "none", "recovery_expectation": "no action needed"},
]

SCENARIOS_BY_ID = {s["scenario_id"]: s for s in [*SCENARIOS, *CONTROL_SCENARIOS, *HOLDOUT_SCENARIOS, *HOLDOUT_CONTROLS]}


def blind_symptom(scenario_id: str) -> str:
    """The only text an agent may be given for this scenario: what a customer would notice, never the cause."""
    return get_scenario(scenario_id)["blind_symptom"]


def get_scenario(scenario_id: str) -> dict:
    if scenario_id not in SCENARIOS_BY_ID:
        raise ValueError(f"unknown scenario_id: {scenario_id}")
    return dict(SCENARIOS_BY_ID[scenario_id])


def get_ground_truth(scenario_id: str) -> dict:
    """The ONLY function evaluation/ is meant to call for scoring. Never
    imported by agents/, orchestrator/, or guardrails/."""
    scenario = get_scenario(scenario_id)
    return {
        "scenario_id": scenario_id,
        "ground_truth_root_cause": scenario["ground_truth_root_cause"],
        "recovery_expectation": scenario["recovery_expectation"],
    }
