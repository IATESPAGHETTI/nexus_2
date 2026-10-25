"""Backend incident state + event store tests (Phase 6).

Pure TestClient tests (no live server, no network) -- same pattern as
tests/test_health.py. Covers backend/app/incident_store.py and the
/incidents* endpoints in backend/app/main.py that
orchestrator/event_bridge.py relies on for real HTTP calls during a live
investigation.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

from app import incident_store  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)


def setup_function(_fn):
    incident_store.clear()


def test_create_incident_returns_full_initial_state():
    response = client.post("/incidents", json={"description": "checkout latency spike"})
    assert response.status_code == 200
    body = response.json()
    assert body["incident_id"].startswith("INC-")
    assert body["status"] == "INVESTIGATING"
    assert body["description"] == "checkout latency spike"
    assert body["hypotheses"] == []
    assert body["timeline"] == []


def test_get_unknown_incident_is_404():
    response = client.get("/incidents/INC-doesnotexist")
    assert response.status_code == 404


def test_event_lifecycle_updates_timeline_and_is_listable():
    incident_id = client.post("/incidents", json={"description": "db slowdown"}).json()["incident_id"]

    event_resp = client.post(
        f"/incidents/{incident_id}/events",
        json={
            "event_type": "HYPOTHESIS_CREATED",
            "source": "evidence_agent",
            "target": None,
            "status": None,
            "payload": {"hypothesis_id": "H1"},
        },
    )
    assert event_resp.status_code == 200
    event = event_resp.json()
    assert event["event_id"]
    assert event["incident_id"] == incident_id
    assert event["event_type"] == "HYPOTHESIS_CREATED"
    assert event["payload"] == {"hypothesis_id": "H1"}

    events = client.get(f"/incidents/{incident_id}/events").json()["events"]
    assert len(events) == 1
    assert events[0]["event_id"] == event["event_id"]

    incident = client.get(f"/incidents/{incident_id}").json()
    assert len(incident["timeline"]) == 1
    assert incident["timeline"][0]["event_type"] == "HYPOTHESIS_CREATED"


def test_event_on_unknown_incident_is_404():
    response = client.post(
        "/incidents/INC-doesnotexist/events",
        json={"event_type": "AGENT_STARTED", "source": "metrics_agent"},
    )
    assert response.status_code == 404


def test_state_update_merges_fields_without_clobbering_others():
    incident_id = client.post("/incidents", json={"description": "config error"}).json()["incident_id"]

    client.post(f"/incidents/{incident_id}/state", json={"hypotheses": [{"hypothesis_id": "H1"}]})
    incident = client.post(f"/incidents/{incident_id}/state", json={"status": "DIAGNOSED"}).json()

    assert incident["status"] == "DIAGNOSED"
    assert incident["hypotheses"] == [{"hypothesis_id": "H1"}]
    assert incident["description"] == "config error"  # untouched field preserved


def test_state_update_on_unknown_incident_is_404():
    response = client.post("/incidents/INC-doesnotexist/state", json={"status": "DIAGNOSED"})
    assert response.status_code == 404


def test_approve_recovery_plan_records_decision_and_emits_event():
    incident_id = client.post("/incidents", json={"description": "bad deployment"}).json()["incident_id"]

    response = client.post(
        f"/incidents/{incident_id}/approve", json={"decision": "APPROVED", "approved_by": "deepu"}
    )
    assert response.status_code == 200
    incident = response.json()
    assert incident["approval_state"]["decision"] == "APPROVED"
    assert incident["approval_state"]["approved_by"] == "deepu"
    assert incident["approval_state"]["decided_at"]

    events = client.get(f"/incidents/{incident_id}/events").json()["events"]
    assert events[-1]["event_type"] == "HUMAN_APPROVAL_GRANTED"
    assert events[-1]["status"] == "APPROVED"


def test_reject_recovery_plan_emits_rejected_event():
    incident_id = client.post("/incidents", json={"description": "bad deployment"}).json()["incident_id"]

    response = client.post(
        f"/incidents/{incident_id}/approve", json={"decision": "REJECTED", "approved_by": "deepu"}
    )
    assert response.status_code == 200
    assert response.json()["approval_state"]["decision"] == "REJECTED"

    events = client.get(f"/incidents/{incident_id}/events").json()["events"]
    assert events[-1]["event_type"] == "HUMAN_APPROVAL_REJECTED"


def test_approve_rejects_invalid_decision_value():
    incident_id = client.post("/incidents", json={"description": "bad deployment"}).json()["incident_id"]
    response = client.post(
        f"/incidents/{incident_id}/approve", json={"decision": "MAYBE", "approved_by": "deepu"}
    )
    assert response.status_code == 400


def test_approve_on_unknown_incident_is_404():
    response = client.post(
        "/incidents/INC-doesnotexist/approve", json={"decision": "APPROVED", "approved_by": "deepu"}
    )
    assert response.status_code == 404


def test_approving_after_the_window_expired_resumes_the_saved_plan(monkeypatch):
    from app import demo

    spawned = []
    monkeypatch.setattr(demo, "can_resume_recovery", lambda: True)
    monkeypatch.setattr(demo, "spawn_resume_recovery", lambda incident_id: spawned.append(incident_id) or True)
    incident_id = client.post("/incidents", json={"description": "late"}).json()["incident_id"]
    client.post(f"/incidents/{incident_id}/state", json={"approval_state": {"decision": "EXPIRED"}})

    body = client.post(f"/incidents/{incident_id}/approve", json={"decision": "APPROVED", "approved_by": "me"}).json()

    assert spawned == [incident_id]
    assert body["approval_state"]["decision"] == "APPROVED" and body["approval_state"]["late"] is True


def test_normal_approval_does_not_spawn_a_resume(monkeypatch):
    from app import demo

    spawned = []
    monkeypatch.setattr(demo, "spawn_resume_recovery", lambda incident_id: spawned.append(incident_id) or True)
    incident_id = client.post("/incidents", json={"description": "normal"}).json()["incident_id"]
    client.post(f"/incidents/{incident_id}/state", json={"approval_state": {"decision": "PENDING"}})
    client.post(f"/incidents/{incident_id}/approve", json={"decision": "APPROVED", "approved_by": "me"})
    assert spawned == []


def test_late_approval_is_refused_not_silently_dropped_when_resume_is_impossible(monkeypatch):
    from app import demo

    monkeypatch.setattr(demo, "can_resume_recovery", lambda: False)
    incident_id = client.post("/incidents", json={"description": "late"}).json()["incident_id"]
    client.post(f"/incidents/{incident_id}/state", json={"approval_state": {"decision": "EXPIRED"}})
    assert client.post(f"/incidents/{incident_id}/approve", json={"decision": "APPROVED", "approved_by": "me"}).status_code == 503
    assert client.get(f"/incidents/{incident_id}").json()["approval_state"]["decision"] == "EXPIRED"


def _incident_awaiting_approval():
    incident_id = client.post("/incidents", json={"description": "gate"}).json()["incident_id"]
    client.post(f"/incidents/{incident_id}/state", json={"approval_state": {"decision": "PENDING"}})
    return incident_id


def test_approval_needs_the_token_when_one_is_configured(monkeypatch):
    monkeypatch.setenv("NEXUS_APPROVER_TOKEN", "s3cret")
    incident_id = _incident_awaiting_approval()
    body = {"decision": "APPROVED", "approved_by": "me"}

    assert client.post(f"/incidents/{incident_id}/approve", json=body).status_code == 403
    assert client.post(f"/incidents/{incident_id}/approve", json=body, headers={"X-Approver-Token": "wrong"}).status_code == 403
    assert client.get(f"/incidents/{incident_id}").json()["approval_state"]["decision"] == "PENDING"  # nothing recorded

    ok = client.post(f"/incidents/{incident_id}/approve", json=body, headers={"X-Approver-Token": "s3cret"})
    assert ok.status_code == 200 and ok.json()["approval_state"]["decision"] == "APPROVED"


def test_approval_is_open_when_no_token_is_configured(monkeypatch):
    monkeypatch.delenv("NEXUS_APPROVER_TOKEN", raising=False)
    incident_id = _incident_awaiting_approval()
    assert client.post(f"/incidents/{incident_id}/approve", json={"decision": "REJECTED", "approved_by": "me"}).status_code == 200


def test_state_endpoint_cannot_record_a_human_approval(monkeypatch):
    """The generic state merge must not be a side door around /approve and its token gate."""
    monkeypatch.setenv("NEXUS_APPROVER_TOKEN", "s3cret")
    incident_id = _incident_awaiting_approval()

    for decision in ("APPROVED", "REJECTED"):
        response = client.post(f"/incidents/{incident_id}/state", json={"approval_state": {"decision": decision}})
        assert response.status_code == 403
    assert client.get(f"/incidents/{incident_id}").json()["approval_state"]["decision"] == "PENDING"


def test_state_endpoint_still_accepts_orchestrator_approval_states():
    incident_id = client.post("/incidents", json={"description": "orchestrator"}).json()["incident_id"]
    for decision in ("PENDING", "EXPIRED", "NOT_REQUESTED"):
        response = client.post(f"/incidents/{incident_id}/state", json={"approval_state": {"decision": decision}})
        assert response.status_code == 200 and response.json()["approval_state"]["decision"] == decision
