"""Blackboard topology end to end (0 tokens): REAL backend process + REAL A2A servers + the REAL controller code
(`orchestrator/blackboard.py`). Only the agents' reasoning is faked (canned results), so what is proven is the
data flow: agents READ their input from the shared board and WRITE their output to it; the A2A message is a pointer.

Run with .venv-agents (the backend is started from the root .venv as its own process).
"""
import asyncio
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest
import uvicorn

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "agents" / "common", ROOT / "orchestrator"):
    sys.path.insert(0, str(p))


def _find_venv():
    for parent in [ROOT, *ROOT.parents]:
        cand = parent / ".venv" / "Scripts" / "python.exe"
        if cand.exists():
            return cand
    return None


VENV = _find_venv()
pytestmark = pytest.mark.skipif(VENV is None, reason="root .venv (backend) not found")

BACKEND_PORT, BASE = 8148, 8150  # agents on 8150..8152
os.environ["NEXUS_BACKEND_URL"] = f"http://127.0.0.1:{BACKEND_PORT}"

import event_bridge  # noqa: E402
import ports  # noqa: E402
import blackboard  # noqa: E402
from a2a_server import build_a2a_app  # noqa: E402
from google.adk.agents import Agent  # noqa: E402
from google.adk.models.base_llm import BaseLlm  # noqa: E402
from google.adk.models.llm_response import LlmResponse  # noqa: E402
from google.genai import types  # noqa: E402

event_bridge.BACKEND_URL = os.environ["NEXUS_BACKEND_URL"]
SEEN_QUESTIONS: dict[str, str] = {}


class Quiet(BaseLlm):
    model: str = "quiet"

    async def generate_content_async(self, llm_request, stream=False):
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text="ok")]))


class FakeAgent:
    """Records the question it was given (rebuilt from the board) and returns a canned, role-shaped result."""

    default_question = "x"

    def __init__(self, name):
        self.agent_name = name

    def build_adk_agent(self):
        return Agent(name=self.agent_name, model=Quiet(), instruction="x")

    async def investigate(self, question):
        SEEN_QUESTIONS[self.agent_name] = question
        usage = {"llm_calls": 1, "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        if self.agent_name == "metrics_agent":
            return {"finding_id": "find-m", "agent": "metrics_agent", "confidence": 0.8, "interpretation": "slow",
                    "evidence": [{"evidence_id": "ev-m1", "tool": "get_metrics", "arguments": {}, "result": {"ok": True}}],
                    "usage": usage, "monitoring": {"agent": "metrics_agent", "errors": 0}}
        if self.agent_name == "evidence_agent":
            return {"hypotheses": [{"hypothesis_id": "H1", "statement": "slow db", "confidence": 0.7,
                                    "supporting_evidence_ids": ["ev-m1"]}], "usage": usage}
        return {"critique_id": "crit-1", "verdict": "SUPPORTED", "rationale": "ok", "usage": usage}


def _wait_port(port, tries=80):
    for _ in range(tries):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
            return
        except OSError:
            time.sleep(0.25)
    pytest.fail(f"port {port} never opened")


@pytest.fixture(scope="module")
def stack():
    env = {**os.environ, "NEXUS_DB_PATH": ":memory:"}
    backend = subprocess.Popen(
        [str(VENV), "-m", "uvicorn", "app.main:app", "--app-dir", str(ROOT / "backend"), "--port", str(BACKEND_PORT)],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=str(ROOT))
    servers = []
    for i, name in enumerate(["metrics_agent", "evidence_agent", "root_cause_critic"]):
        ports.A2A_PORTS[name] = BASE + i
        app = build_a2a_app(FakeAgent(name), "127.0.0.1", BASE + i)
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=BASE + i, log_level="error"))
        threading.Thread(target=server.run, daemon=True).start()
        servers.append(server)
    try:
        _wait_port(BACKEND_PORT)
        for i in range(3):
            _wait_port(BASE + i)
        yield
    finally:
        backend.kill()
        for s in servers:
            s.should_exit = True


def _board(iid):
    return json.loads(urllib.request.urlopen(f"{event_bridge.BACKEND_URL}/incidents/{iid}/blackboard", timeout=10).read())["entries"]


def test_agents_read_inputs_from_and_write_outputs_to_the_shared_board(stack):
    iid = event_bridge.create_incident("orders are slow")

    # 1. specialists: controller posts the task; the agent reads it from the board and posts its finding
    result = asyncio.run(blackboard.board_investigate(iid, "orders are slow", ["metrics_agent"], {"metrics_agent": "m"}))
    assert result["agents_responded"] == ["metrics_agent"] and result["findings"]["metrics_agent"]["finding_id"] == "find-m"
    assert result["findings"]["metrics_agent"]["usage"]["total_tokens"] == 15       # bookkeeping still reaches the budget
    assert SEEN_QUESTIONS["metrics_agent"] == "orders are slow"                    # rebuilt from the board entry

    # 2. evidence agent: its input is whatever the specialists wrote on the board, not a message body
    call = asyncio.run(blackboard.board_synthesize(iid, "evidence_agent", "e"))
    assert call["response"]["hypotheses"][0]["statement"] == "slow db" and call["task_id"]
    assert list(json.loads(SEEN_QUESTIONS["evidence_agent"])) == ["metrics_agent"]

    # 3. critic: reads the requested hypothesis AND the evidence pool from the board
    call = asyncio.run(blackboard.board_review(iid, "root_cause_critic", "c", {"hypothesis_id": "H1", "statement": "slow db"}))
    assert call["response"]["verdict"] == "SUPPORTED"
    seen = json.loads(SEEN_QUESTIONS["root_cause_critic"])
    assert seen["hypothesis"]["statement"] == "slow db" and [e["evidence_id"] for e in seen["evidence_pool"]] == ["ev-m1"]

    # the board is the audit trail: who wrote what, in order
    entries = _board(iid)
    assert [(e["type"], e["author"]) for e in entries] == [
        ("description", "incident_manager"), ("request", "incident_manager"), ("finding", "metrics_agent"),
        ("hypotheses", "evidence_agent"), ("review_request", "incident_manager"), ("critique", "root_cause_critic")]
    assert all("usage" not in e["content"] and "monitoring" not in e["content"] for e in entries)  # bookkeeping stays off the board


def test_a_non_board_message_still_works_the_old_way(stack):
    from remote_call import call_remote_agent
    out = asyncio.run(call_remote_agent("metrics_agent", "m", "plain question"))
    assert out["response"]["finding_id"] == "find-m" and SEEN_QUESTIONS["metrics_agent"] == "plain question"
