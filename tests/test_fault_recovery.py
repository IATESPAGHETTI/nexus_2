"""production/state.py and its admin endpoints (Phase 8/9).

Same pattern as tests/test_observability.py: real TestClient against the real
FastAPI app, no mocking -- a fault flag genuinely changes real HTTP responses.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "production"))

from fastapi.testclient import TestClient  # noqa: E402

import state  # noqa: E402
from service import app  # noqa: E402

client = TestClient(app)


def setup_function(_fn):
    state.clear_all()


def test_admin_state_starts_clean():
    response = client.get("/admin/state")
    assert response.status_code == 200
    body = response.json()
    assert body["bad_deployment"] is False
    assert body["db_slowdown"] is False
    assert body["config_error"] is False
    assert body["dependency_failure"] is False
    assert body["resource_exhaustion"] is False


def test_inject_unknown_fault_type_is_400():
    response = client.post("/admin/fault/inject", json={"fault_type": "not_a_real_fault"})
    assert response.status_code == 400


def test_config_error_makes_orders_deterministically_fail():
    client.post("/admin/fault/inject", json={"fault_type": "config_error"})
    response = client.get("/orders")
    assert response.status_code == 500
    assert "ConfigError" in response.json()["detail"]

    # And it's still 500 on a second call -- deterministic, not flaky.
    response2 = client.get("/orders")
    assert response2.status_code == 500


def test_bad_deployment_injection_appends_a_change_history_entry():
    before = client.get("/changes").json()["changes"]
    client.post("/admin/fault/inject", json={"fault_type": "bad_deployment"})
    after = client.get("/changes").json()["changes"]
    assert len(after) == len(before) + 1
    assert after[0]["type"] == "deployment"
    # The record must look like an ordinary deployment: no hint that a fault was injected.
    assert "fault" not in (after[0]["author"] + after[0]["description"]).lower()


def test_admin_control_plane_calls_leave_no_trace_in_observability():
    """Regression: POST /admin/fault/inject used to appear in /logs, /traces and /metrics,
    so diagnostic agents could read the test harness as evidence."""
    client.post("/admin/reset")
    client.post("/admin/fault/inject", json={"fault_type": "db_slowdown"})
    client.get("/admin/state")
    client.post("/admin/recovery/restart_service")
    assert not any("/admin" in str(e) for e in client.get("/logs").json()["entries"])
    assert not any("/admin" in str(t) for t in client.get("/traces").json()["traces"])
    assert not any("/admin" in ep for ep in client.get("/metrics").json()["by_endpoint"])


def test_db_slowdown_adds_real_latency_to_orders():
    import time

    client.post("/admin/fault/inject", json={"fault_type": "db_slowdown"})
    start = time.perf_counter()
    client.get("/orders")
    elapsed = time.perf_counter() - start
    assert elapsed >= 0.2  # real sleep, not a fabricated number


def test_fault_clear_resets_all_flags():
    client.post("/admin/fault/inject", json={"fault_type": "config_error"})
    assert client.get("/admin/state").json()["config_error"] is True
    client.post("/admin/fault/clear")
    assert client.get("/admin/state").json()["config_error"] is False


def test_restart_service_clears_resource_and_dependency_faults_only():
    client.post("/admin/fault/inject", json={"fault_type": "resource_exhaustion"})
    client.post("/admin/fault/inject", json={"fault_type": "bad_deployment"})
    client.post("/admin/recovery/restart_service")
    snap = client.get("/admin/state").json()
    assert snap["resource_exhaustion"] is False
    assert snap["bad_deployment"] is True  # restart does NOT fix a bad deployment


def test_rollback_deployment_clears_bad_deployment_and_records_change():
    client.post("/admin/fault/inject", json={"fault_type": "bad_deployment"})
    before = len(client.get("/changes").json()["changes"])

    response = client.post("/admin/recovery/rollback_deployment", json={"target_version": "1.0.0"})
    assert response.status_code == 200
    snap = client.get("/admin/state").json()
    assert snap["bad_deployment"] is False
    assert snap["deployed_version"] == "1.0.0"

    after = client.get("/changes").json()["changes"]
    assert len(after) == before + 1
    assert after[0]["author"] == "guardrails"


def test_reset_config_clears_config_error():
    client.post("/admin/fault/inject", json={"fault_type": "config_error"})
    client.post("/admin/recovery/reset_config")
    assert client.get("/admin/state").json()["config_error"] is False
    assert client.get("/orders").status_code == 200


def test_scale_resources_clears_capacity_faults():
    client.post("/admin/fault/inject", json={"fault_type": "resource_exhaustion"})
    client.post("/admin/fault/inject", json={"fault_type": "db_slowdown"})
    client.post("/admin/recovery/scale_resources")
    snapshot = client.get("/admin/state").json()
    assert snapshot["resource_exhaustion"] is False
    assert snapshot["db_slowdown"] is False


def test_rollback_deployment_requires_target_version():
    response = client.post("/admin/recovery/rollback_deployment", json={})
    assert response.status_code == 422  # pydantic: missing required field


def test_admin_reset_wipes_fault_residue_between_scenarios():
    """Regression: the '1.2.0-bad' change record and old errors from a bad_deployment
    run used to survive a fault clear and contaminate the next benchmark scenario."""
    client.post("/admin/fault/inject", json={"fault_type": "bad_deployment"})
    for _ in range(5):
        client.get("/orders")
    assert any(c["version"] == "1.2.0-bad" for c in client.get("/changes").json()["changes"])
    assert client.get("/metrics").json()["request_count"] >= 5

    assert client.post("/admin/reset").json()["bad_deployment"] is False
    assert not any(c["version"] == "1.2.0-bad" for c in client.get("/changes").json()["changes"])
    assert len(client.get("/changes").json()["changes"]) == 3
    assert not any("orders" in ep for ep in client.get("/metrics").json()["by_endpoint"])
    assert not any("orders" in str(entry) for entry in client.get("/logs").json()["entries"])
