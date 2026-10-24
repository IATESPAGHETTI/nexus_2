"""traceparent -> ADK A2A server -> handler, over real HTTP and the real a2a protocol (fake agent, 0 tokens)."""
import asyncio
import json
import socket
import sys
import threading
import time
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agents" / "common"))
import nexus_trace  # noqa: E402
import ports  # noqa: E402
from a2a_server import build_a2a_app  # noqa: E402
from callbacks import AgentMonitor  # noqa: E402
from google.adk.agents import Agent  # noqa: E402
from google.adk.models.base_llm import BaseLlm  # noqa: E402
from google.adk.models.llm_response import LlmResponse  # noqa: E402
from google.adk.runners import InMemoryRunner  # noqa: E402
from google.genai import types  # noqa: E402
from remote_agent import build_remote_agent  # noqa: E402

PORT = 8137


class Quiet(BaseLlm):
    model: str = "quiet"

    async def generate_content_async(self, llm_request, stream=False):
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text="ok")]))


class FakeAgent:
    agent_name = "trace_probe"
    default_question = "x"

    def build_adk_agent(self):
        return Agent(name="trace_probe", model=Quiet(), instruction="x")

    async def investigate(self, question):
        m = AgentMonitor("trace_probe", echo=False)  # reads the ambient trace exactly like the real agents do
        return {"finding_id": "find-probe", "monitoring": m.summary()}


def test_adk_agent_service_sees_the_orchestrators_trace_id():
    app = build_a2a_app(FakeAgent(), "127.0.0.1", PORT)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(60):
        try:
            socket.create_connection(("127.0.0.1", PORT), timeout=0.5).close()
            break
        except OSError:
            time.sleep(0.25)
    ports.A2A_PORTS["trace_probe"] = PORT
    ctx = nexus_trace.start_trace()
    try:
        async def go():
            remote = build_remote_agent("trace_probe", "probe")
            runner = InMemoryRunner(agent=remote, app_name="probe")
            session = await runner.session_service.create_session(app_name="probe", user_id="u")
            text = None
            async for ev in runner.run_async(user_id="u", session_id=session.id,
                                             new_message=types.Content(role="user", parts=[types.Part(text="hi")])):
                for p in (ev.content.parts if ev.content else []) or []:
                    if getattr(p, "text", None):
                        text = p.text
            return json.loads(text)

        result = asyncio.run(go())
    finally:
        nexus_trace.set_current(None)
        server.should_exit = True
    assert result["monitoring"]["trace_id"] == ctx.trace_id
    assert result["monitoring"]["parent_span_id"] not in (None, ctx.span_id)
