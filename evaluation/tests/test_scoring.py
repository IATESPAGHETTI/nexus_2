"""Fast, pure unit tests for evaluation/scoring.py and
evaluation/baselines.build_result -- no network, no LLM.

Run: .venv-orchestrator/Scripts/python -m pytest evaluation/tests/test_scoring.py -q
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import baselines  # noqa: E402
import pytest  # noqa: E402
import runtime_config  # noqa: E402
import scoring  # noqa: E402


def test_classify_statement_matches_known_keywords():
    assert scoring.classify_statement("A recent bad deployment broke order totals") == "bad_deployment"
    assert scoring.classify_statement("The database query latency spiked") == "db_slowdown"
    assert scoring.classify_statement("Configuration setting DB_POOL_SIZE is invalid") == "config_error"
    assert scoring.classify_statement("payment-service dependency timeout") == "dependency_failure"
    assert scoring.classify_statement("Resource exhaustion, memory limit exceeded") == "resource_exhaustion"


def test_classify_statement_unknown_when_no_keyword_matches():
    assert scoring.classify_statement("Everything looks fine") == "unknown"
    assert scoring.classify_statement(None) == "unknown"


def test_score_run_correct_diagnosis():
    result = scoring.score_run("bad_deployment", "bad_deployment", abstained=False)
    assert result["correct"] is True
    assert result["false_diagnosis"] is False
    assert result["made_a_diagnosis"] is True


def test_score_run_false_diagnosis():
    result = scoring.score_run("db_slowdown", "bad_deployment", abstained=False)
    assert result["correct"] is False
    assert result["false_diagnosis"] is True


def test_score_run_abstention_is_neither_correct_nor_false():
    result = scoring.score_run("unknown", "bad_deployment", abstained=True)
    assert result["correct"] is False
    assert result["false_diagnosis"] is False
    assert result["made_a_diagnosis"] is False


def test_score_run_unknown_prediction_without_abstention_is_neutral_not_false():
    result = scoring.score_run("unknown", "bad_deployment", abstained=False)
    assert result["made_a_diagnosis"] is False
    assert result["false_diagnosis"] is False


def test_aggregate_computes_rates_across_runs():
    records = [
        scoring.score_run("bad_deployment", "bad_deployment", abstained=False),
        scoring.score_run("db_slowdown", "bad_deployment", abstained=False),
        scoring.score_run("unknown", "bad_deployment", abstained=True),
        scoring.score_run("bad_deployment", "bad_deployment", abstained=False),
    ]
    agg = scoring.aggregate(records)
    assert agg["total_runs"] == 4
    assert agg["root_cause_accuracy"] == 0.5
    assert agg["false_diagnosis_rate"] == 0.25
    assert agg["abstention_rate"] == 0.25


def test_aggregate_empty_is_safe():
    assert scoring.aggregate([]) == {"total_runs": 0}


# --- baselines.build_result (structural enforcement, no LLM) --------------


def test_build_result_rejects_out_of_catalog_root_cause():
    result = baselines.build_result({"root_cause": "aliens", "confidence": 0.9, "rationale": "x"}, 1.0)
    assert result["root_cause"] == "unknown"


def test_build_result_clamps_confidence():
    result = baselines.build_result({"root_cause": "db_slowdown", "confidence": 5.0, "rationale": "x"}, 1.0)
    assert result["confidence"] == 1.0


def test_build_result_handles_unparseable_output_without_crashing():
    result = baselines.build_result(None, 1.0)
    assert result["root_cause"] == "unknown"
    assert result["arm"] == "single_agent_baseline"


# --- runtime provider selection (pure, no API call) ----------------------


def test_deepseek_is_the_default_official_provider():
    assert runtime_config.resolve_runtime_config("deepseek", "deepseek-chat") == (
        "deepseek",
        "deepseek-chat",
    )
    assert runtime_config.litellm_model_name("deepseek", "deepseek-chat") == "deepseek/deepseek-chat"
    assert runtime_config.is_official_benchmark_config("deepseek", "deepseek-chat") is True


def test_default_without_env_override_resolves_to_deepseek(monkeypatch):
    monkeypatch.delenv("NEXUS_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("NEXUS_LLM_MODEL", raising=False)
    assert runtime_config.resolve_runtime_config() == ("deepseek", "deepseek-chat")
    assert runtime_config.litellm_model_name() == "deepseek/deepseek-chat"


def test_groq_configuration_still_valid_but_not_the_default_benchmark():
    assert runtime_config.resolve_runtime_config("groq", "openai/gpt-oss-120b") == (
        "groq",
        "openai/gpt-oss-120b",
    )
    assert runtime_config.litellm_model_name("groq", "openai/gpt-oss-120b") == "groq/openai/gpt-oss-120b"
    assert runtime_config.is_official_benchmark_config("groq", "openai/gpt-oss-120b") is False


def test_gemini_configuration_is_valid_but_not_an_official_benchmark():
    assert runtime_config.litellm_model_name("gemini", "gemini-2.5-flash") == "gemini/gemini-2.5-flash"
    assert runtime_config.is_official_benchmark_config("gemini", "gemini-2.5-flash") is False


def test_unknown_runtime_provider_is_rejected():
    with pytest.raises(ValueError, match="NEXUS_LLM_PROVIDER"):
        runtime_config.resolve_runtime_config("unsupported-provider", "model")


# --- measured token cost (incident.token_usage -> benchmark records) ---------


def test_token_cost_is_measured_when_the_incident_recorded_usage():
    incident = {"token_usage": {"total": {"llm_calls": 12, "total_tokens": 32000}, "unmeasured_tasks": 1}}
    assert scoring.token_cost(incident) == {"llm_calls": 12, "total_tokens": 32000, "unmeasured_tasks": 1}


@pytest.mark.parametrize("incident", [None, {}, {"token_usage": {}}, {"token_usage": {"total": {"llm_calls": 0}}}])
def test_token_cost_stays_unavailable_when_nothing_was_recorded(incident):
    assert scoring.token_cost(incident) == "Unavailable from provider"


def test_aggregate_averages_token_cost_only_over_runs_that_have_it():
    base = {"made_a_diagnosis": True, "abstained": False, "correct": True, "false_diagnosis": False, "latency_seconds": 1.0}
    records = [
        dict(base, token_cost={"llm_calls": 10, "total_tokens": 20000, "unmeasured_tasks": 0}),
        dict(base, token_cost={"llm_calls": 20, "total_tokens": 40000, "unmeasured_tasks": 0}),
        dict(base, token_cost="Unavailable from provider"),
    ]
    summary = scoring.aggregate(records)
    assert summary["runs_with_token_data"] == 2
    assert summary["avg_llm_calls"] == 15.0
    assert summary["avg_total_tokens"] == 30000
    assert "avg_total_tokens" not in scoring.aggregate([dict(base, token_cost="Unavailable from provider")])


@pytest.mark.parametrize("text", [
    "No root cause for a database slowdown is supported: all evidence shows a healthy system",
    "Insufficient evidence to pin the failure on the deployment",
])
def test_negated_statements_are_not_credited_as_a_diagnosis(text):
    assert scoring.classify_statement(text) == "unknown"


def test_affirmative_statement_still_classified():
    assert scoring.classify_statement("A bad deployment introduced the order total bug") == "bad_deployment"
