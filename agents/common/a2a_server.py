"""Turns a Phase 4 DiagnosticAgent into a real, independent A2A service (Phase 5).

Uses the official `a2a-sdk` + `google.adk.a2a.utils.agent_to_a2a.to_a2a()` — the
real Agent2Agent protocol (JSON-RPC/HTTP task lifecycle, Agent Card at
`/.well-known/agent-card.json`), not a hand-rolled imitation.

`DiagnosticAgentExecutor` is a custom `a2a.server.agent_execution.AgentExecutor`
that, for every real incoming A2A task, runs the SAME `DiagnosticAgent.investigate()`
used in Phase 4 (real MCP tool calls, real Groq/GPT-OSS-120B reasoning, real
Python-built observation/evidence — see agents/common/finding.py) and returns the
resulting structured Finding, JSON-encoded, as the task's final agent message.
The A2A boundary does not weaken the evidence-first guarantees from Phase 4 — it
relocates where investigate() runs (inside the serving process, triggered by a
real network request) without changing what it does.
"""

from __future__ import annotations

import json

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types.a2a_pb2 import Part, Task, TaskState, TaskStatus
from google.adk.a2a.utils.agent_to_a2a import to_a2a
from starlette.applications import Starlette

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from nexus_trace import TraceContextMiddleware  # noqa: E402
from board_io import parse_board_message, run_on_board  # noqa: E402
from legacy_card import LegacyCardMiddleware  # noqa: E402


class DiagnosticAgentExecutor(AgentExecutor):
    def __init__(self, diagnostic_agent):
        self.diagnostic_agent = diagnostic_agent

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        # The a2a-sdk server requires the task to be established (a Task event)
        # before any TaskStatusUpdateEvent can be published for it.
        await event_queue.enqueue_event(
            Task(
                id=context.task_id,
                context_id=context.context_id,
                status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED),
            )
        )
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.start_work()

        text = context.get_user_input() or ""
        board = parse_board_message(text)
        if board:
            # Blackboard topology: read the shared board, write the result back, reply with a small ack.
            finding = await run_on_board(self.diagnostic_agent.investigate, board, self.diagnostic_agent.agent_name)
        else:
            question = text or self.diagnostic_agent.default_question
            finding = await self.diagnostic_agent.investigate(question)

        message = updater.new_agent_message([Part(text=json.dumps(finding))])
        await updater.complete(message)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.update_status(TaskState.TASK_STATE_CANCELED)


def build_a2a_app(diagnostic_agent, host: str, port: int) -> Starlette:
    adk_agent = diagnostic_agent.build_adk_agent()
    import os

    app = to_a2a(
        adk_agent,
        host=os.environ.get("NEXUS_ADVERTISE_HOST", host),
        port=port,
        agent_executor_factory=lambda runner: DiagnosticAgentExecutor(diagnostic_agent),
    )
    app.add_middleware(LegacyCardMiddleware)  # a card that an A2A 0.3 client (CrewAI) can also read
    app.add_middleware(TraceContextMiddleware)  # reads the orchestrator's W3C traceparent header
    return app
