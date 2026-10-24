"""Plain-http A2A inside a private network (docker compose): opt-in, strict everywhere else."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import remote_agent as ra  # noqa: E402

CARD = {"capabilities": {"streaming": False}, "defaultInputModes": ["text"], "defaultOutputModes": ["text"],
        "description": "d", "name": "metrics_agent", "preferredTransport": "JSONRPC", "protocolVersion": "0.3.0",
        "skills": [{"description": "s", "id": "s", "name": "s", "tags": ["t"]}], "url": "http://metrics:8101/", "version": "1"}


def test_internal_card_is_opt_in_and_only_for_non_loopback_http(monkeypatch):
    monkeypatch.delenv("NEXUS_ALLOW_INTERNAL_HTTP", raising=False)
    assert not ra.needs_internal_card("http://metrics:8101/.well-known/agent-card.json")   # default stays strict
    monkeypatch.setenv("NEXUS_ALLOW_INTERNAL_HTTP", "1")
    assert ra.needs_internal_card("http://metrics:8101/.well-known/agent-card.json")
    assert not ra.needs_internal_card("http://127.0.0.1:8101/.well-known/agent-card.json")   # ADK already allows loopback
    assert not ra.needs_internal_card("http://localhost:8101/x")
    assert not ra.needs_internal_card("https://agents.example.com/.well-known/agent-card.json")  # https never needs it


def test_remote_agent_is_built_from_a_fetched_card_object_for_internal_hosts(monkeypatch):
    monkeypatch.setenv("NEXUS_ALLOW_INTERNAL_HTTP", "1")
    monkeypatch.setenv("NEXUS_AGENT_URL_METRICS_AGENT", "http://metrics:8101")

    class R:
        def raise_for_status(self): pass
        def json(self): return CARD
    seen = []
    monkeypatch.setattr(ra.httpx, "get", lambda url, timeout=None: seen.append(url) or R())
    remote = ra.build_remote_agent("metrics_agent", "m")
    assert seen == ["http://metrics:8101/.well-known/agent-card.json"]
    assert remote._agent_card is not None and remote._agent_card.name == "metrics_agent"   # object, so ADK skips its https URL check


def test_without_the_opt_in_a_non_loopback_http_url_is_still_passed_through_to_adk(monkeypatch):
    monkeypatch.delenv("NEXUS_ALLOW_INTERNAL_HTTP", raising=False)
    monkeypatch.setenv("NEXUS_AGENT_URL_METRICS_AGENT", "http://metrics:8101")
    remote = ra.build_remote_agent("metrics_agent", "m")
    assert remote._agent_card is None   # unresolved URL string: ADK will refuse it at call time, as before
