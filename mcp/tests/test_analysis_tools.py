"""Unit tests for mcp/analysis_tools.py (no network: the shop is replaced by a fake). Run with .venv-mcp."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import analysis_tools as at  # noqa: E402


# ------------------------------------------------------------ runbook parser
def test_runbook_search_finds_the_relevant_section_and_cites_its_file():
    out = at.search_runbook(query="requests are slow but no errors step change", limit=2)
    assert out["ok"] and out["matches"]
    top = out["matches"][0]
    assert top["source"] == "latency.md" and "slow" in top["heading"].lower() and len(top["text"]) <= at.SNIPPET_CHARS


def test_runbook_search_ranks_config_and_dependency_text_for_error_queries():
    cfg = at.search_runbook(query="every request fails immediately same error invalid setting")["matches"][0]
    dep = at.search_runbook(query="only requests calling another service fail timeout unreachable")["matches"][0]
    assert cfg["source"] == "errors.md" and "same way" in cfg["heading"]
    assert dep["source"] == "errors.md" and "another service" in dep["heading"]


@pytest.mark.parametrize("bad", ["", "   ", "x" * 500, "!!"])
def test_runbook_search_rejects_bad_queries_without_raising(bad):
    out = at.search_runbook(query=bad)
    assert out["ok"] is False and "error" in out


def test_runbook_search_reads_only_the_runbook_folder_and_bounds_limit():
    out = at.search_runbook(query="latency", limit=99)
    assert len(out["matches"]) <= 5
    assert {s["source"] for s in at._sections()} <= {p.name for p in at.RUNBOOK_DIR.glob("*.md")}


# ---------------------------------------------------------------- calculator
@pytest.mark.parametrize("expr,expected", [("260 / 1.2", 216.666667), ("(7 / 17) * 100", 41.176471), ("2 ** 10", 1024), ("-3 + 5 * 2", 7), ("10 % 4", 2), ("7 // 2", 3)])
def test_calculator_computes_arithmetic(expr, expected):
    assert at.evaluate_expression(expression=expr)["result"] == pytest.approx(expected)


@pytest.mark.parametrize("evil", [
    "__import__('os').system('echo hi')", "open('/etc/passwd').read()", "(lambda: 1)()", "[1,2,3]", "a + 1", "2 ** 1000",
    "9999999 ** 9", "1 / 0", "'abc' * 3", "True + 1", "x" * 300, "", "1 +", "exec('1')",
])
def test_calculator_refuses_anything_that_is_not_plain_arithmetic(evil):
    out = at.evaluate_expression(expression=evil)
    assert out["ok"] is False and "error" in out


# ----------------------------------------------------------------- statistics
def test_step_change_is_found_in_a_fast_then_slow_series_and_dated():
    series = [1.0, 0.9, 1.1, 1.0, 1.2, 0.8] + [260.0, 258.0, 262.0, 259.0, 261.0, 263.0, 257.0]
    out = at.find_step_change(series)
    assert out["step_detected"] and out["split_index"] == 6
    assert out["mean_before_ms"] < 2 and out["mean_after_ms"] > 250 and out["ratio_after_to_before"] > 100


def test_no_step_is_reported_for_a_flat_or_noisy_series_or_a_short_one():
    assert at.find_step_change([1.0, 1.1, 0.9, 1.0, 1.2, 1.0, 0.9, 1.1])["step_detected"] is False
    assert at.find_step_change([5, 80, 4, 90, 6, 70, 5, 85])["step_detected"] is False      # noisy, no lasting step
    assert at.find_step_change([1, 2, 3])["step_detected"] is False


def test_percentiles_and_summary():
    vals = list(range(1, 101))
    assert at.percentile(vals, 0.5) == pytest.approx(50.5) and at.percentile(vals, 0.99) == pytest.approx(99.01)
    s = at.summarize([1.0, 2.0, 3.0])
    assert s["count"] == 3 and s["median_ms"] == 2.0 and s["max_ms"] == 3.0


class _FakeShop:
    def __init__(self, rows):
        self.rows = rows

    def get(self, path, params=None):
        assert path == "/traces" and params["limit"] <= 200
        return {"traces": self.rows}


def _rows(durations, path="/orders"):
    return [{"trace_id": f"t{i}", "timestamp": f"2026-10-18T10:00:{i:02d}Z", "method": "GET", "path": path, "status_code": 200, "duration_ms": d}
            for i, d in enumerate(durations)]


def test_detect_latency_step_reads_the_shop_and_reports_onset(monkeypatch):
    rows = _rows([1.0, 0.9, 1.1, 1.0, 1.0, 1.2] + [260.0, 258.0, 262.0, 259.0, 261.0, 263.0]) + _rows([0.8] * 10, path="/health")
    monkeypatch.setattr(at.production_client, "get", _FakeShop(list(reversed(rows))).get)     # the shop returns newest first
    out = at.detect_latency_step(path="/orders", limit=50)
    assert out["ok"] and out["requests_used"] == 12 and out["step"]["step_detected"]
    assert out["step"]["onset_timestamp"] == "2026-10-18T10:00:06Z" and out["stats"]["p99_ms"] > 250


def test_detect_latency_step_handles_missing_data_and_bad_input(monkeypatch):
    monkeypatch.setattr(at.production_client, "get", _FakeShop(_rows([1.0])).get)
    assert "not enough" in at.detect_latency_step(path="/orders")["note"]
    assert at.detect_latency_step(path="orders")["ok"] is False
    assert at.detect_latency_step(path="/" + "a" * 100)["ok"] is False

    def down(path, params=None):
        raise at.production_client.ProductionUnavailableError("shop is down")
    monkeypatch.setattr(at.production_client, "get", down)
    assert at.detect_latency_step(path="/orders") == {"ok": False, "error": "shop is down"}
