"""orchestrator/service.py: HTTP trigger with the real run functions replaced by stubs (no network, no tokens)."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from starlette.testclient import TestClient  # noqa: E402

import service  # noqa: E402


def _client(monkeypatch, token=None):
    calls = []
    release = asyncio.Event()

    async def fake_run(kind, incident_id, description=""):
        calls.append((kind, incident_id, description))
        service._running.discard(incident_id)

    monkeypatch.setattr(service, "_run", fake_run)
    if token:
        monkeypatch.setenv("NEXUS_INTERNAL_TOKEN", token)
    else:
        monkeypatch.delenv("NEXUS_INTERNAL_TOKEN", raising=False)
    service._running.clear()
    return TestClient(service.app), calls


def test_investigate_accepts_valid_request(monkeypatch):
    c, calls = _client(monkeypatch)
    r = c.post("/investigate", json={"incident_id": "INC-0a1b2c3d", "description": "orders are slow"})
    assert r.status_code == 202 and r.json()["incident_id"] == "INC-0a1b2c3d"
    assert calls == [("investigate", "INC-0a1b2c3d", "orders are slow")]


def test_rejects_bad_ids_and_missing_description(monkeypatch):
    c, calls = _client(monkeypatch)
    assert c.post("/investigate", json={"incident_id": "../etc", "description": "x"}).status_code == 422
    assert c.post("/investigate", json={"incident_id": "INC-0a1b2c3d", "description": "  "}).status_code == 422
    assert c.post("/investigate", content=b"not json").status_code == 422
    assert calls == []


def test_token_is_enforced_when_configured(monkeypatch):
    c, calls = _client(monkeypatch, token="s3cret")
    body = {"incident_id": "INC-0a1b2c3d", "description": "x"}
    assert c.post("/investigate", json=body).status_code == 403
    assert c.post("/investigate", json=body, headers={"X-Internal-Token": "wrong"}).status_code == 403
    assert c.post("/investigate", json=body, headers={"X-Internal-Token": "s3cret"}).status_code == 202


def test_only_one_investigation_at_a_time(monkeypatch):
    c, calls = _client(monkeypatch)
    service._running.add("INC-aaaa1111")
    r = c.post("/investigate", json={"incident_id": "INC-bbbb2222", "description": "x"})
    assert r.status_code == 429 and calls == []


def test_resume_and_health(monkeypatch):
    c, calls = _client(monkeypatch)
    assert c.post("/resume-recovery", json={"incident_id": "INC-0a1b2c3d"}).status_code == 202
    assert calls[0][0] == "resume"
    assert c.get("/health").json()["status"] == "ok"
