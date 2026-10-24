"""AgentMonitor against the REAL ADK runner using a scripted fake model (no API calls, no tokens)."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))

from callbacks import MAX_RECORDS, AgentMonitor  # noqa: E402
from google.adk.agents import Agent  # noqa: E402
from google.adk.models.base_llm import BaseLlm  # noqa: E402
from google.adk.models.llm_response import LlmResponse  # noqa: E402
from google.adk.runners import InMemoryRunner  # noqa: E402
from google.genai import types  # noqa: E402


class ScriptedLlm(BaseLlm):
    """Turn 1: ask for the tool. Turn 2 (after the tool result): final text."""
    model: str = "scripted"
    tool_name: str = "lookup"

    async def generate_content_async(self, llm_request, stream=False):
        answered = any(
            getattr(p, "function_response", None) for c in llm_request.contents for p in (c.parts or [])
        )
        if answered:
            part = types.Part(text="done")
        else:
            part = types.Part(function_call=types.FunctionCall(name=self.tool_name, args={"q": "secret-ish"}))
        yield LlmResponse(content=types.Content(role="model", parts=[part]))


def lookup(q: str) -> dict:
    """Test tool."""
    if q == "boom":
        raise RuntimeError("tool exploded")
    return {"ok": True, "value": 1}


def _run(monitor, tool=lookup):
    agent = Agent(name="t", model=ScriptedLlm(tool_name=tool.__name__), instruction="x", tools=[tool], **monitor.callbacks())

    async def go():
        runner = InMemoryRunner(agent=agent, app_name="t")
        session = await runner.session_service.create_session(app_name="t", user_id="u")
        async for _ in runner.run_async(
            user_id="u", session_id=session.id, new_message=types.Content(role="user", parts=[types.Part(text="hi")])
        ):
            pass

    asyncio.run(go())


def test_callbacks_fire_in_order_on_a_real_adk_run():
    m = AgentMonitor("t", echo=False)
    _run(m)
    kinds = [r["kind"] for r in m.records]
    assert kinds[0] == "model_call_started"
    assert "tool_call_started" in kinds and "tool_call_finished" in kinds
    assert kinds.count("model_call_finished") == 2  # tool request, then final answer
    assert kinds[-1] == "agent_finished"
    s = m.summary()
    assert s["model_calls"] == 2 and s["tool_calls"] == 1 and s["errors"] == 0
    assert s["records"][0]["seq"] == 1


def test_arguments_are_not_copied_only_keys():
    m = AgentMonitor("t", echo=False)
    _run(m)
    started = next(r for r in m.records if r["kind"] == "tool_call_started")
    assert started["argument_keys"] == ["q"]
    assert "secret-ish" not in str(m.records)


def test_tool_failure_is_recorded_as_error_without_breaking_summary():
    def lookup_boom(q: str) -> dict:
        """Test tool."""
        raise RuntimeError("tool exploded")

    m = AgentMonitor("t", echo=False)
    try:
        _run(m, tool=lookup_boom)
    except Exception:
        pass  # ADK may re-raise; the monitor must still hold the error record
    s = m.summary()
    assert s["errors"] == 1
    assert any(r["kind"] == "tool_error" and r["error_type"] == "RuntimeError" for r in m.records)


def test_record_list_is_bounded():
    m = AgentMonitor("t", echo=False)
    for _ in range(MAX_RECORDS + 50):
        m.after_agent(None)
    assert len(m.records) == MAX_RECORDS and m.summary()["truncated"] is True
