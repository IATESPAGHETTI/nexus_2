"""Pure tests for evaluation/matrix.py and the healthy-control scoring (no network, no model)."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "fault_injection"))
import matrix  # noqa: E402
import scenarios  # noqa: E402
import scoring  # noqa: E402


def test_stdev_and_mean_basics():
    assert matrix.mean([2, 4, 6]) == 4 and matrix.stdev([2, 4, 6]) == pytest.approx(2.0)
    assert matrix.stdev([5]) == 0.0 and matrix.stdev([]) == 0.0


def test_cost_estimate_uses_both_directions_and_overrides():
    assert matrix.estimate_cost_usd(1_000_000, 1_000_000, 0.3, 1.2) == pytest.approx(1.5)
    assert matrix.estimate_cost_usd(2_000_000, 0, 1.0, 9.0) == pytest.approx(2.0)


def test_healthy_control_scoring():
    assert scoring.score_run("unknown", "none", abstained=True)["correct"] is True
    assert scoring.score_run("unknown", "none", abstained=False)["correct"] is True
    wrong = scoring.score_run("db_slowdown", "none", abstained=False)
    assert wrong["false_diagnosis"] is True and wrong["correct"] is False
    # a normal fault run is unchanged
    assert scoring.score_run("db_slowdown", "db_slowdown", False)["correct"] is True


def test_aggregate_reports_controls_separately():
    recs = [
        {**scoring.score_run("db_slowdown", "db_slowdown", False), "latency_seconds": 1},
        {**scoring.score_run("unknown", "none", True), "latency_seconds": 1},
        {**scoring.score_run("config_error", "none", False), "latency_seconds": 1},
    ]
    agg = scoring.aggregate(recs)
    assert agg["root_cause_accuracy"] == 1.0                      # fault runs only
    assert agg["control_runs"] == 2 and agg["control_correct_rate"] == 0.5


def _rec(arm, sid, correct, truth="db_slowdown", predicted="db_slowdown", lat=10, tokens=1000, abstained=False):
    return {"arm": arm, "scenario_id": sid, "ground_truth_root_cause": truth, "predicted_root_cause": predicted,
            "correct": correct, "false_diagnosis": (not correct) and not abstained and predicted != "unknown",
            "abstained": abstained, "latency_seconds": lat,
            "token_cost": {"llm_calls": 9, "prompt_tokens": tokens * 9 // 10, "completion_tokens": tokens // 10, "total_tokens": tokens}}


def test_summarize_arm_separates_faults_from_controls_and_computes_spread():
    recs = [_rec("a", "s1", True, lat=10, tokens=1000), _rec("a", "s1", False, predicted="config_error", lat=30, tokens=3000),
            _rec("a", "c", True, truth="none", predicted="unknown", abstained=True, lat=20, tokens=2000)]
    s = matrix.summarize_arm(recs, 0.3, 1.2)
    assert s["runs"] == 3 and s["fault_runs"] == 2 and s["accuracy"] == 0.5 and s["false_diagnosis_rate"] == 0.5
    assert s["control_runs"] == 1 and s["control_correct_rate"] == 1.0
    assert s["latency_s_mean"] == 20.0 and s["latency_s_std"] == 10.0 and s["tokens_mean"] == 2000
    assert s["est_cost_usd_total"] > 0


def test_summarize_handles_runs_without_token_data():
    r = _rec("b", "s1", True)
    r["token_cost"] = scoring.TOKEN_COST_UNAVAILABLE
    assert matrix.summarize_arm([r])["tokens_mean"] == 0


def test_repeatability():
    recs = [_rec("a", "s1", True), _rec("a", "s1", True), _rec("a", "s2", True), _rec("a", "s2", False, predicted="config_error")]
    assert matrix.repeatability(recs) == {"scenarios_with_repeats": 2, "consistent_fraction": 0.5}
    assert matrix.repeatability([_rec("a", "s1", True)])["consistent_fraction"] is None


def test_arms_group_so_services_restart_only_when_env_differs():
    groups = dict(matrix.group_by_agent_env(matrix.ARMS))
    default = groups[()]
    assert {a.name for a in default} >= {"baseline_single_agent", "hub_default", "hub_no_critic", "blackboard", "pipeline"}
    assert len(groups) == 7  # default, react, fewshot, persona_sre, crewai critic, analysis tools, crewai evidence+critic
    assert matrix.ARMS_BY_NAME["blackboard"].run_env_dict() == {"NEXUS_TOPOLOGY": "blackboard"}
    assert matrix.ARMS_BY_NAME["blackboard"].agent_env_dict() == {}   # topology needs no agent restart


def test_markdown_report_prints_numbers_and_every_caveat():
    arms = [matrix.ARMS_BY_NAME["hub_default"]]
    runs = [_rec("hub_default", "FI-db-slowdown", True)]
    report = {"timestamp": "t", "runtime": "deepseek/x", "scenarios": ["FI-db-slowdown"], "repeats": 1, "price_in_per_m": 0.3,
              "price_out_per_m": 1.2, "balance_delta_usd": 0.01, "est_cost_usd_total": 0.0,
              "arms": {"hub_default": matrix.summarize_arm(runs)}, "repeatability": {"hub_default": matrix.repeatability(runs)},
              "arm_definitions": {"hub_default": {"description": "d", "compares": "reference"}}, "runs": runs,
              "caveats": matrix.STANDARD_CAVEATS}
    md = matrix.render_markdown(report)
    assert "| hub_default | 1 (0) | 100% |" in md and "ESTIMATE" in md and "1/1" in md
    assert all(c in md for c in matrix.STANDARD_CAVEATS)


def test_every_benchmark_scenario_has_a_symptom_that_does_not_name_its_cause():
    leaks = ("deployment", "deploy", "config", "dependency", "payment", "fault", "inject", "pool", "database")
    for s in [*scenarios.SCENARIOS, *scenarios.CONTROL_SCENARIOS]:
        text = scenarios.blind_symptom(s["scenario_id"]).lower()
        assert not any(w in text for w in leaks if w not in ("database",)), (s["scenario_id"], text)
    assert scenarios.get_ground_truth("CTRL-healthy")["ground_truth_root_cause"] == "none"
    assert len(scenarios.SCENARIOS) == 5   # control is NOT among the five fault classes


def test_classifier_labels_real_pilot_statements_correctly():
    """Real hypothesis statements produced in the 2026-10-15 pilot (kept as fixtures). The old classifier
    labelled the configuration statements 'db_slowdown' because they mention DB_POOL_SIZE."""
    import json
    fixtures = json.loads((Path(__file__).parent / "real_statements.json").read_text(encoding="utf-8"))
    assert len(fixtures) >= 8
    for f in fixtures:
        assert scoring.classify_statement(f["statement"]) == f["truth"], f["statement"][:120]


def test_classifier_ignores_causes_that_are_only_ruled_out():
    assert scoring.classify_statement("Slow queries on the orders table; no deployment or configuration change explains it.") == "db_slowdown"
    assert scoring.classify_statement("A bad release introduced the errors, not a database problem.") == "bad_deployment"
    assert scoring.classify_statement("payment-service timeouts on order lookups") == "dependency_failure"
    assert scoring.classify_statement("The service is out of memory") == "resource_exhaustion"
    assert scoring.classify_statement("nothing recognisable here") == "unknown" and scoring.classify_statement(None) == "unknown"


def test_rescore_uses_the_current_scorer_on_stored_text():
    import run_matrix
    rec = {"arm": "a", "scenario_id": "s", "status": "DIAGNOSED", "ground_truth_root_cause": "config_error",
           "predicted_statement": "A misconfiguration of DB_POOL_SIZE causes the errors", "predicted_root_cause": "db_slowdown",
           "correct": False, "false_diagnosis": True, "abstained": False}
    out = run_matrix.rescore(rec)
    assert out["predicted_root_cause"] == "config_error" and out["correct"] is True
    abst = {**rec, "status": "ABSTAINED"}
    assert run_matrix.rescore(abst)["predicted_root_cause"] == "unknown"
    base = {"arm": "b", "status": "BASELINE", "correct": True}
    assert run_matrix.rescore(base) == base


# ------------------------------------------------------------------ held-out scenarios
def test_holdout_scenarios_are_new_valid_and_blind():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "production"))
    import state as production_state
    core_symptoms = {s["blind_symptom"] for s in scenarios.SCENARIOS} | {s["blind_symptom"] for s in scenarios.CONTROL_SCENARIOS}
    leaks = ("deployment", "deploy ", "config", "dependency", "payment", "fault", "inject", "pool", "memory", "database", "db ", "query")
    for s in [*scenarios.HOLDOUT_SCENARIOS, *scenarios.HOLDOUT_CONTROLS]:
        assert set(s["fault_types"]) <= set(production_state.FAULT_TYPES), s["scenario_id"]
        assert s["blind_symptom"] not in core_symptoms, "held-out wording must differ from the tuned wording"
        assert not any(w in s["blind_symptom"].lower() for w in leaks), (s["scenario_id"], s["blind_symptom"])
        truth = s["ground_truth_root_cause"].split("|")
        assert all(t in production_state.FAULT_TYPES or t == "none" for t in truth)
        if s["fault_types"]:
            assert set(truth) == set(s["fault_types"]), "every injected fault is an acceptable diagnosis"
    assert len(scenarios.HOLDOUT_SCENARIOS) == 8 and sum(1 for s in scenarios.HOLDOUT_SCENARIOS if len(s["fault_types"]) == 2) == 3
    assert len(scenarios.SCENARIOS) == 5                      # the tuned set is unchanged


def test_two_fault_truth_accepts_either_cause_and_rejects_others():
    ok_a = scoring.score_run("db_slowdown", "db_slowdown|dependency_failure", False)
    ok_b = scoring.score_run("dependency_failure", "db_slowdown|dependency_failure", False)
    bad = scoring.score_run("config_error", "db_slowdown|dependency_failure", False)
    assert ok_a["correct"] and ok_b["correct"] and not ok_a["false_diagnosis"]
    assert not bad["correct"] and bad["false_diagnosis"]
    assert scoring.score_run("unknown", "db_slowdown|dependency_failure", True)["correct"] is False


def test_injector_posts_every_fault_of_a_two_fault_scenario(monkeypatch):
    import injector
    posted = []
    monkeypatch.setattr(injector, "_post", lambda path, json=None: posted.append((path, json)) or {"ok": True})
    injector.inject("HO-two-faults-db-dependency")
    assert posted == [("/admin/fault/inject", {"fault_type": "db_slowdown"}), ("/admin/fault/inject", {"fault_type": "dependency_failure"})]
    posted.clear()
    injector.inject("FI-db-slowdown")
    assert len(posted) == 1


def test_runner_scenario_sets():
    import run_matrix
    core = [s["scenario_id"] for s in scenarios.SCENARIOS] + ["CTRL-healthy"]
    assert len(core) == 6 and all(c in scenarios.SCENARIOS_BY_ID for c in core)
    assert "HO-healthy-control" in scenarios.SCENARIOS_BY_ID
    assert run_matrix.main(["--plan", "--set", "holdout", "--repeats", "1", "--arms", "hub_default"]) == 0


def test_invalid_runs_are_excluded_from_accuracy_but_counted():
    good = _rec("a", "s1", True)
    bad = {**_rec("a", "s1", False, predicted="unknown", abstained=True), "invalid": True, "agent_errors": 3}
    s = matrix.summarize_arm([good, bad])
    assert s["runs"] == 1 and s["invalid_runs"] == 1 and s["accuracy"] == 1.0           # the rate-limited run does not count as an abstention
    assert matrix.repeatability([good, bad])["consistent_fraction"] is None            # one valid repeat only


def test_runner_retries_a_run_with_agent_errors_then_marks_it_invalid(monkeypatch):
    import run_matrix
    calls = []

    async def fake_run_one(arm, sid, rep):
        calls.append(1)
        return {"arm": arm.name, "scenario_id": sid, "repeat": rep, "ground_truth_root_cause": "db_slowdown", "predicted_root_cause": "unknown",
                "correct": False, "false_diagnosis": False, "abstained": True, "latency_seconds": 1, "agent_errors": 2, "token_cost": {}}

    class NoStack:
        def start(self, env): pass
        def stop(self): pass

    monkeypatch.setattr(run_matrix, "run_one", fake_run_one)
    monkeypatch.setattr(run_matrix, "AgentStack", NoStack)
    monkeypatch.setattr(run_matrix, "deepseek_balance", lambda: None)
    monkeypatch.setattr(run_matrix.time, "sleep", lambda s: None)
    monkeypatch.setattr(run_matrix, "RESULTS_DIR", Path(__file__).parent / "_tmp_results")
    import json as _json
    run_matrix.main(["--arms", "hub_default", "--scenarios", "FI-db-slowdown", "--repeats", "1", "--retries", "2", "--retry-wait", "0"])
    assert len(calls) == 3                                            # first attempt + 2 retries
    out = sorted((Path(__file__).parent / "_tmp_results").glob("matrix-*.jsonl"))[-1]
    rec = _json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert rec["invalid"] is True and rec["attempts"] == 3
    import shutil
    shutil.rmtree(Path(__file__).parent / "_tmp_results")


def test_an_exception_in_one_run_becomes_an_invalid_record_not_a_crash(monkeypatch):
    import run_matrix

    async def boom(arm, sid, rep):
        raise RuntimeError("RateLimitError: quota exceeded")

    monkeypatch.setattr(run_matrix, "run_one", boom)
    rec = run_matrix.safe_run(matrix.ARMS_BY_NAME["hub_default"], "FI-db-slowdown", 0)
    assert rec["agent_errors"] == 1 and rec["status"] == "ERROR" and "RateLimitError" in rec["error"] and rec["correct"] is False


def test_a_run_with_no_model_output_is_detected_as_empty():
    import run_matrix
    assert run_matrix.produced_nothing({"token_cost": scoring.TOKEN_COST_UNAVAILABLE})
    assert run_matrix.produced_nothing({"token_cost": {"total_tokens": 0}})
    assert not run_matrix.produced_nothing({"token_cost": {"total_tokens": 1234}})


def test_a_statement_that_nothing_is_wrong_is_correct_on_a_healthy_shop_and_never_a_diagnosis():
    healthy = "Everything is operating normally: no errors, and database latencies are around 1 ms."
    assert scoring.classify_statement(healthy) == "healthy"
    ok = scoring.score_run("healthy", "none", abstained=False)
    assert ok["correct"] and not ok["false_diagnosis"] and ok["declared_healthy"]
    missed = scoring.score_run("healthy", "db_slowdown", abstained=False)       # claiming health during a fault is a miss, not a diagnosis
    assert not missed["correct"] and not missed["false_diagnosis"] and missed["declared_healthy"]


def test_a_real_fault_statement_is_not_mistaken_for_healthy():
    assert scoring.classify_statement("There is no deployment change, but a step change in database latency started at 10:42 and slow queries followed.") == "db_slowdown"
    assert scoring.classify_statement("Requests to /orders are operating normally except that they fail with timeouts calling the payment-service.") == "dependency_failure"


# ------------------------------------------------------------------ API key rotation (owner's own keys, same provider)
def test_keyring_uses_distinct_nonempty_keys_in_order_and_never_exposes_values():
    import run_matrix
    ring = run_matrix.KeyRing({"GEMINI_API_KEY": "key-one", "GEMINI_API_KEY_2": "key-two", "GEMINI_API_KEY_3": "key-one"})   # 3rd is a duplicate
    assert ring.names == ["GEMINI_API_KEY", "GEMINI_API_KEY_2"]
    env = ring.environ
    assert ring.rotate() == "GEMINI_API_KEY_2" and env["GEMINI_API_KEY"] == "key-two"
    assert ring.rotate() is None                                                     # nothing left
    assert run_matrix.KeyRing({"GEMINI_API_KEY": "a"}).names == ["GEMINI_API_KEY"]
    assert run_matrix.KeyRing({}).names == []


def test_matrix_switches_key_when_three_runs_come_back_empty_and_redoes_them(monkeypatch, tmp_path):
    import json as _json
    import run_matrix

    monkeypatch.setenv("NEXUS_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "exhausted-key")
    monkeypatch.setenv("GEMINI_API_KEY_2", "fresh-key")
    starts = []

    class FakeStack:
        def start(self, env): starts.append(os.environ["GEMINI_API_KEY"])
        def stop(self): pass

    def fake_run(arm, sid, rep):
        key = os.environ["GEMINI_API_KEY"]
        empty = key == "exhausted-key"
        return {"arm": arm.name, "scenario_id": sid, "repeat": rep, "ground_truth_root_cause": "db_slowdown",
                "predicted_root_cause": "unknown" if empty else "db_slowdown", "correct": not empty, "false_diagnosis": False,
                "abstained": empty, "latency_seconds": 1.0, "agent_errors": 0,
                "token_cost": scoring.TOKEN_COST_UNAVAILABLE if empty else {"llm_calls": 5, "prompt_tokens": 90, "completion_tokens": 10, "total_tokens": 100}}

    monkeypatch.setattr(run_matrix, "safe_run", fake_run)
    monkeypatch.setattr(run_matrix, "AgentStack", FakeStack)
    monkeypatch.setattr(run_matrix, "deepseek_balance", lambda: None)
    monkeypatch.setattr(run_matrix, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(run_matrix.time, "sleep", lambda s: None)
    scen = "FI-db-slowdown,FI-bad-deployment,FI-config-error,FI-dependency-failure"
    run_matrix.main(["--arms", "hub_default", "--scenarios", scen, "--repeats", "1", "--retries", "0"])
    out = sorted(tmp_path.glob("matrix-*.jsonl"))[-1]
    recs = [_json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert starts == ["exhausted-key", "fresh-key"]                       # agents were restarted on the second key
    assert len(recs) == 4 and all(not r["invalid"] for r in recs)          # the 3 empty runs were redone, not recorded as invalid
    assert {r["scenario_id"] for r in recs} == set(scen.split(","))
