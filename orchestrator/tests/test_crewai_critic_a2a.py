"""ADK client (a2a-sdk 1.x) -> CrewAI Critic (a2a-sdk 0.3.x) over real A2A, stub mode (0 tokens).
Starts the CrewAI service as its own process from .venv-crewai; skipped when that venv is absent."""
import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VENV_PY = ROOT / ".venv-crewai" / "Scripts" / "python.exe"
if not VENV_PY.exists():  # worktrees share the main checkout's venvs
    for parent in ROOT.parents:
        if (parent / ".venv-crewai" / "Scripts" / "python.exe").exists():
            VENV_PY = parent / ".venv-crewai" / "Scripts" / "python.exe"
            break
pytestmark = pytest.mark.skipif(not VENV_PY.exists(), reason=".venv-crewai not created")

sys.path.insert(0, str(ROOT / "orchestrator"))
sys.path.insert(0, str(ROOT / "agents" / "common"))
PORT = 8126


@pytest.fixture(scope="module")
def service():
    env = {**os.environ, "CRITIC_STUB": "1", "CRITIC_PORT": str(PORT)}
    proc = subprocess.Popen([str(VENV_PY), str(ROOT / "crewai_critic" / "a2a_service.py")], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                socket.create_connection(("127.0.0.1", PORT), timeout=0.5).close()
                break
            except OSError:
                time.sleep(0.5)
        else:
            pytest.fail("CrewAI critic service did not start")
        yield proc
    finally:
        proc.kill()


def test_adk_client_gets_a_crewai_critique_over_a2a(service, monkeypatch):
    import ports
    monkeypatch.setitem(ports.A2A_PORTS, "root_cause_critic", PORT)
    from remote_call import call_remote_agent
    msg = json.dumps({"hypothesis": {"hypothesis_id": "H1", "statement": "x"}, "evidence_pool": []})
    out = asyncio.run(call_remote_agent("root_cause_critic", "crewai critic", msg))
    assert out["task_id"] and out["context_id"]  # a real A2A task happened
    assert out["response"]["framework"] == "crewai"
    assert out["response"]["hypothesis_id"] == "H1"
    assert out["response"]["verdict"] == "INSUFFICIENT_EVIDENCE"


def test_trace_id_travels_over_a2a_to_the_crewai_agent(service, monkeypatch):
    import ports
    import nexus_trace
    monkeypatch.setitem(ports.A2A_PORTS, "root_cause_critic", PORT)
    from remote_call import call_remote_agent
    ctx = nexus_trace.start_trace()
    try:
        out = asyncio.run(call_remote_agent("root_cause_critic", "crewai critic", json.dumps({"hypothesis": {}, "evidence_pool": []})))
    finally:
        nexus_trace.set_current(None)
    mon = out["response"]["monitoring"]
    assert mon["trace_id"] == ctx.trace_id          # the id the orchestrator generated arrived in the CrewAI process
    assert mon["parent_span_id"] and mon["parent_span_id"] != ctx.span_id  # a child span of the root, one per call


@pytest.fixture(scope="module")
def evidence_service():
    port = 8127
    env = {**os.environ, "CRITIC_STUB": "1", "EVIDENCE_PORT": str(port)}
    proc = subprocess.Popen([str(VENV_PY), str(ROOT / "crewai_critic" / "evidence_service.py")], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
                break
            except OSError:
                time.sleep(0.5)
        else:
            pytest.fail("CrewAI evidence service did not start")
        yield port
    finally:
        proc.kill()


def test_adk_client_gets_hypotheses_from_the_crewai_evidence_agent_over_a2a(evidence_service, monkeypatch):
    import ports
    import nexus_trace
    monkeypatch.setitem(ports.A2A_PORTS, "evidence_agent", evidence_service)
    from remote_call import call_remote_agent
    ctx = nexus_trace.start_trace()
    try:
        findings = {"metrics_agent": {"finding_id": "f1", "evidence": [{"evidence_id": "ev-1"}]}}
        out = asyncio.run(call_remote_agent("evidence_agent", "crewai evidence", json.dumps(findings)))
    finally:
        nexus_trace.set_current(None)
    r = out["response"]
    assert out["task_id"] and r["framework"] == "crewai"
    assert r["hypotheses"][0]["hypothesis_id"] == "H1" and r["monitoring"]["trace_id"] == ctx.trace_id
