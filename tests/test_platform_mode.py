"""Backend demo helpers in platform mode (orchestrator/agents are separate services reached by URL)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import httpx  # noqa: E402

from app import demo  # noqa: E402


class _Resp:
    def __init__(self, code):
        self.status_code = code


def test_investigation_is_triggered_over_http_with_the_internal_token(monkeypatch):
    seen = {}
    monkeypatch.setattr(demo, "ORCHESTRATOR_URL", "http://orchestrator:8200")
    monkeypatch.setattr(demo, "INTERNAL_TOKEN", "tok")
    monkeypatch.setattr(httpx, "post", lambda url, json=None, headers=None, timeout=None: seen.update(url=url, json=json, headers=headers) or _Resp(202))
    assert demo.spawn_investigation("INC-0a1b2c3d", "orders slow") is True
    assert seen["url"] == "http://orchestrator:8200/investigate" and seen["json"]["incident_id"] == "INC-0a1b2c3d"
    assert seen["headers"] == {"X-Internal-Token": "tok"}


def test_unreachable_or_refusing_orchestrator_reports_false(monkeypatch):
    monkeypatch.setattr(demo, "ORCHESTRATOR_URL", "http://orchestrator:8200")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp(429))
    assert demo.spawn_investigation("INC-0a1b2c3d", "x") is False

    def boom(*a, **k):
        raise httpx.ConnectError("down")
    monkeypatch.setattr(httpx, "post", boom)
    assert demo.spawn_investigation("INC-0a1b2c3d", "x") is False


def test_platform_mode_never_launches_or_kills_local_processes(monkeypatch):
    monkeypatch.setattr(demo, "ORCHESTRATOR_URL", "http://orchestrator:8200")
    monkeypatch.setattr(demo, "check_agents", lambda: {"metrics_agent": True, "database_agent": False})

    def no_popen(*a, **k):
        raise AssertionError("a process was launched in platform mode")
    monkeypatch.setattr(demo.subprocess, "Popen", no_popen)
    started = demo.start_agents()
    assert started["started"] == [] and started["already_running"] == ["metrics_agent"] and started["failed"] == ["database_agent"]
    assert demo.stop_agents()["stopped"] == [] and demo.can_resume_recovery() is True


def test_agents_are_probed_at_their_configured_urls(monkeypatch):
    urls = []
    monkeypatch.setenv("NEXUS_AGENT_URL_METRICS_AGENT", "http://metrics:8101/")
    monkeypatch.setattr(httpx, "get", lambda url, timeout=None: urls.append(url) or _Resp(200))
    assert demo._agent_up("metrics_agent") is True
    assert urls == ["http://metrics:8101/.well-known/agent-card.json"]
    assert demo._agent_url("database_agent") == "http://127.0.0.1:8104"
