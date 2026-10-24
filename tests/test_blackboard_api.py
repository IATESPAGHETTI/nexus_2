"""Blackboard endpoints on the backend (course requirement 1): typed, attributable, append-only, audited."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

from app import incident_store  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)


def setup_function(_fn):
    incident_store.clear()


def _incident():
    return client.post("/incidents", json={"description": "slow orders"}).json()["incident_id"]


def test_entries_are_appended_in_order_with_ids_and_authors():
    iid = _incident()
    a = client.post(f"/incidents/{iid}/blackboard", json={"type": "description", "author": "incident_manager", "content": {"text": "x"}}).json()
    b = client.post(f"/incidents/{iid}/blackboard", json={"type": "finding", "author": "metrics_agent", "content": {"finding_id": "f1"}, "trace_id": "t" * 32}).json()
    assert (a["entry_id"], b["entry_id"]) == ("bb-1", "bb-2")
    entries = client.get(f"/incidents/{iid}/blackboard").json()["entries"]
    assert [e["author"] for e in entries] == ["incident_manager", "metrics_agent"] and entries[1]["trace_id"] == "t" * 32
    only = client.get(f"/incidents/{iid}/blackboard", params={"type": "finding"}).json()["entries"]
    assert [e["entry_id"] for e in only] == ["bb-2"]


def test_unknown_type_and_unknown_incident_are_rejected():
    iid = _incident()
    assert client.post(f"/incidents/{iid}/blackboard", json={"type": "shell", "author": "x", "content": {}}).status_code == 422
    assert client.post("/incidents/INC-nope/blackboard", json={"type": "finding", "author": "x", "content": {}}).status_code == 404
    assert client.get("/incidents/INC-nope/blackboard").status_code == 404


def test_every_write_is_audited_as_a_board_entry_event_and_board_is_bounded():
    iid = _incident()
    client.post(f"/incidents/{iid}/blackboard", json={"type": "finding", "author": "database_agent", "content": {}})
    events = client.get(f"/incidents/{iid}/events").json()["events"]
    assert events[-1]["event_type"] == "BOARD_ENTRY" and events[-1]["source"] == "database_agent"
    for _ in range(incident_store.MAX_BOARD_ENTRIES - 1):
        incident_store.append_board_entry(iid, "finding", "a", {})
    assert client.post(f"/incidents/{iid}/blackboard", json={"type": "finding", "author": "a", "content": {}}).status_code == 409


def test_report_endpoint_serves_markdown_download_and_json():
    iid = _incident()
    assert client.get(f"/incidents/{iid}/report").status_code == 404            # not ready yet
    client.post(f"/incidents/{iid}/state", json={"report": {"incident_id": iid, "outcome": "DIAGNOSED", "markdown": "# Incident report\n\n| a | b |\n|---|---|\n"}})
    md = client.get(f"/incidents/{iid}/report", params={"format": "md"})
    assert md.status_code == 200 and md.text.startswith("# Incident report")
    assert md.headers["content-type"].startswith("text/markdown") and f"{iid}-report.md" in md.headers["content-disposition"]
    js = client.get(f"/incidents/{iid}/report").json()
    assert js["outcome"] == "DIAGNOSED" and "markdown" not in js
    assert client.get(f"/incidents/{iid}/report", params={"format": "pdf"}).status_code == 422
    assert client.get("/incidents/INC-nope/report").status_code == 404
