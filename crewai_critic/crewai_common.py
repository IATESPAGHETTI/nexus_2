"""Shared CrewAI plumbing for NEXUS's CrewAI agents (course requirements 5, 6, 7).

  * `run_crew`          one CrewAI `Agent` + `Task` + `Crew` run with step and task callbacks that feed the same
                        `AgentMonitor` the ADK agents use, and REAL token usage from `Crew.token_usage`.
  * `provider_llm`      CrewAI `LLM` for whichever provider NEXUS_LLM_PROVIDER selects (deepseek | gemini | groq).
  * `CrewAIExecutor`    an a2a-sdk `AgentExecutor` that runs a sync handler in a thread, supports the blackboard
                        board mode, and reports failures as failed A2A tasks (never a hung one).
  * `build_a2a_app`     the A2A server (CrewAI itself ships cards and clients but no server) + trace middleware.

CRITIC_STUB=1 (or NEXUS_CREWAI_STUB=1) skips the model entirely, for protocol tests.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Callable

os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # CrewAI prints emoji; Windows consoles are cp1252
    except Exception:  # noqa: BLE001
        pass

REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (REPO_ROOT, REPO_ROOT / "agents" / "common"):
    sys.path.insert(0, str(_p))

from a2a.server.agent_execution import AgentExecutor, RequestContext  # noqa: E402
from a2a.server.apps import A2AStarletteApplication  # noqa: E402
from a2a.server.events import EventQueue  # noqa: E402
from a2a.server.request_handlers import DefaultRequestHandler  # noqa: E402
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater  # noqa: E402
from a2a.types import AgentCapabilities, AgentCard, AgentSkill, Part, TaskState, TextPart  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from board_io import parse_board_message, run_on_board  # noqa: E402
from callbacks import AgentMonitor  # noqa: E402
from nexus_trace import TraceContextMiddleware  # noqa: E402
from runtime_config import resolve_runtime_config  # noqa: E402

for _parent in Path(__file__).resolve().parents:  # a git worktree has no .env of its own
    if (_parent / ".env").exists():
        load_dotenv(_parent / ".env")
        break

HOST = os.environ.get("NEXUS_BIND_HOST", "127.0.0.1")
ADVERTISE = os.environ.get("NEXUS_ADVERTISE_HOST", HOST)
_KEY_ENV = {"deepseek": "DEEPSEEK_API_KEY", "gemini": "GEMINI_API_KEY", "groq": "GROQ_API_KEY"}


def stub_mode() -> bool:
    return os.environ.get("CRITIC_STUB") == "1" or os.environ.get("NEXUS_CREWAI_STUB") == "1"


def provider_llm():
    """CrewAI LLM for the provider NEXUS is configured with (same choice as every ADK agent)."""
    provider, model = resolve_runtime_config()
    override = os.environ.get("NEXUS_CREWAI_MODEL")
    model_string = override or f"{provider}/{model}"
    key = os.environ.get(_KEY_ENV[provider])
    if not key:  # checked BEFORE importing crewai, which itself loads .env
        raise RuntimeError(f"{_KEY_ENV[provider]} is not set for provider {provider!r}")
    from crewai import LLM

    return LLM(model=model_string, api_key=key, temperature=0, max_tokens=4000)


def usage_from_crew(output) -> dict:
    """NEXUS budget shape from CrewAI's own measured usage (Crew.token_usage)."""
    metrics = getattr(output, "token_usage", None)
    return {
        "llm_calls": int(getattr(metrics, "successful_requests", 0) or 0),
        "prompt_tokens": int(getattr(metrics, "prompt_tokens", 0) or 0),
        "completion_tokens": int(getattr(metrics, "completion_tokens", 0) or 0),
        "total_tokens": int(getattr(metrics, "total_tokens", 0) or 0),
    }


def run_crew(role: str, goal: str, backstory: str, description: str, expected_output: str, monitor: AgentMonitor):
    """One CrewAI run. Returns (raw model text, usage dict). Step and task callbacks record into `monitor`."""
    from crewai import Agent, Crew, Process, Task

    agent = Agent(
        role=role, goal=goal, backstory=backstory, llm=provider_llm(), allow_delegation=False, verbose=False,
        step_callback=monitor.crewai_step,
    )
    task = Task(description=description, expected_output=expected_output, agent=agent, callback=monitor.crewai_task)
    crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=False)
    monitor.before_model(None, type("Req", (), {"contents": [description]})())
    try:
        output = crew.kickoff()
    except Exception as exc:  # noqa: BLE001
        monitor.on_model_error(None, None, exc)
        raise
    usage = usage_from_crew(output)
    monitor.after_model(
        None,
        type("Resp", (), {
            "usage_metadata": type("U", (), {"prompt_token_count": usage["prompt_tokens"], "candidates_token_count": usage["completion_tokens"]})(),
            "content": None, "error_code": None,
        })(),
    )
    return output.raw, usage


class CrewAIExecutor(AgentExecutor):
    """Runs `handler(question) -> dict` for each A2A task. In blackboard mode the question is rebuilt from the board and
    the result is written back to it (see agents/common/board_io.py)."""

    def __init__(self, handler: Callable[[str], dict], author: str):
        self.handler, self.author = handler, author

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.submit()
        await updater.start_work()
        try:
            text = context.get_user_input() or ""
            board = parse_board_message(text)
            if board:
                result = await run_on_board(lambda q: asyncio.to_thread(self.handler, q), board, self.author)
            else:
                result = await asyncio.to_thread(self.handler, text)
            await updater.complete(updater.new_agent_message([Part(root=TextPart(text=json.dumps(result)))]))
        except Exception as exc:  # noqa: BLE001
            await updater.failed(updater.new_agent_message([Part(root=TextPart(text=f"{type(exc).__name__}: {str(exc)[:200]}"))]))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        await TaskUpdater(event_queue, context.task_id, context.context_id).update_status(TaskState.canceled)


def build_a2a_app(name: str, description: str, port: int, skill_id: str, skill_description: str, tags: list[str], executor: AgentExecutor):
    card = AgentCard(
        name=name, description=description + " (CrewAI implementation)", url=f"http://{ADVERTISE}:{port}/", version="1.1.0",
        default_input_modes=["text"], default_output_modes=["text"], capabilities=AgentCapabilities(streaming=False),
        skills=[AgentSkill(id=skill_id, name=skill_id, description=skill_description, tags=[*tags, "crewai"])],
    )
    handler = DefaultRequestHandler(agent_executor=executor, task_store=InMemoryTaskStore())
    app = A2AStarletteApplication(agent_card=card, http_handler=handler).build()
    app.add_middleware(TraceContextMiddleware)
    return app
