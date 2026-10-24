"""ADK callbacks that monitor every agent run from the inside (course requirement 5).

`AgentMonitor` is attached to an ADK `Agent` through its real callback hooks
(before/after model, before/after tool, tool error, model error, after agent).
It only OBSERVES -- every callback returns None, so it can never change what the
model or a tool returns. For each run it records, in order:

  - every model call (start, duration, token counts, whether it asked for tools)
  - every tool call (name, argument keys, duration, ok/error, result size)
  - every error (model or tool) with the exception type and a short message

`summary()` is the compact, bounded view that travels back with the agent's
reply under a `monitoring` key; the orchestrator pops it off (like `usage`) and
stores it as an `AGENT_MONITOR` event, so it never reaches other agents.
Arguments and results are NOT copied here (the evidence already holds them);
only keys and sizes, so no secret or large payload is duplicated.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
import nexus_trace  # noqa: E402

MAX_RECORDS = 200  # a runaway agent must not grow the trace without bound
_MAX_MSG = 200


def _variant() -> str:
    try:
        from prompt_variants import current_variant

        return current_variant()[0]
    except Exception:  # noqa: BLE001
        return "unknown"


def _size(value: Any) -> int:
    try:
        return len(json.dumps(value, default=str))
    except (TypeError, ValueError):
        return -1


class AgentMonitor:
    def __init__(self, agent_name: str, echo: bool = True) -> None:
        self.agent_name = agent_name
        self.echo = echo
        self.records: list[dict] = []
        self._model_started: float | None = None
        self._tool_started: dict[str, float] = {}
        self._run_started = time.perf_counter()
        self.started_unix = time.time()   # real wall-clock start, so the trace places this agent correctly even in a pipeline
        self.guard = None  # set by build_adk_agent when guardrails are on
        incoming = nexus_trace.current()  # the orchestrator's traceparent, read by TraceContextMiddleware
        self.trace_id = incoming.trace_id if incoming else None
        self.parent_span_id = incoming.span_id if incoming else None
        self.span_id = nexus_trace.new_span_id()

    # ------------------------------------------------------------ plumbing
    def _add(self, kind: str, **fields: Any) -> None:
        if len(self.records) >= MAX_RECORDS:
            return
        record = {"seq": len(self.records) + 1, "kind": kind, "agent": self.agent_name,
                  "span_id": nexus_trace.new_span_id(), **fields}
        self.records.append(record)
        if self.echo:
            print("[nexus-monitor] " + json.dumps(record, default=str), file=sys.stderr, flush=True)

    # ----------------------------------------------------------- callbacks
    def before_model(self, callback_context: Any, llm_request: Any) -> None:
        self._model_started = time.perf_counter()
        contents = getattr(llm_request, "contents", None) or []
        self._add("model_call_started", messages_in_context=len(contents))
        return None

    def after_model(self, callback_context: Any, llm_response: Any) -> None:
        started, self._model_started = self._model_started, None
        usage = getattr(llm_response, "usage_metadata", None)
        parts = getattr(getattr(llm_response, "content", None), "parts", None) or []
        self._add(
            "model_call_finished",
            duration_ms=round((time.perf_counter() - started) * 1000) if started else None,
            prompt_tokens=getattr(usage, "prompt_token_count", None),
            completion_tokens=getattr(usage, "candidates_token_count", None),
            requested_tool_calls=sum(1 for p in parts if getattr(p, "function_call", None)),
            error=getattr(llm_response, "error_code", None),
        )
        return None

    def on_model_error(self, callback_context: Any, llm_request: Any, error: Exception) -> None:
        self._add("model_error", error_type=type(error).__name__, message=str(error)[:_MAX_MSG])
        return None

    def before_tool(self, tool: Any, args: dict, tool_context: Any) -> None:
        key = getattr(tool_context, "function_call_id", None) or getattr(tool, "name", "?")
        self._tool_started[key] = time.perf_counter()
        self._add("tool_call_started", tool=getattr(tool, "name", "?"), argument_keys=sorted(args or {}))
        return None

    def after_tool(self, tool: Any, args: dict, tool_context: Any, tool_response: Any) -> None:
        key = getattr(tool_context, "function_call_id", None) or getattr(tool, "name", "?")
        started = self._tool_started.pop(key, None)
        payload = tool_response.get("structuredContent", tool_response) if isinstance(tool_response, dict) else None
        ok = payload.get("ok") if isinstance(payload, dict) else None
        is_error = bool(tool_response.get("isError")) if isinstance(tool_response, dict) else False
        self._add(
            "tool_call_finished",
            tool=getattr(tool, "name", "?"),
            duration_ms=round((time.perf_counter() - started) * 1000) if started else None,
            ok=ok if ok is not None else (not is_error),
            result_bytes=_size(tool_response),
        )
        return None

    def on_tool_error(self, tool: Any, args: dict, tool_context: Any, error: Exception) -> None:
        self._add(
            "tool_error", tool=getattr(tool, "name", "?"), error_type=type(error).__name__, message=str(error)[:_MAX_MSG]
        )
        return None

    # ---- CrewAI hooks (Agent(step_callback=...), Task(callback=...)): same record format as the ADK callbacks
    def crewai_step(self, step: Any) -> None:
        """Called by CrewAI after each agent step. Records what kind of step it was (tool call or final answer) and
        which tool, never the tool's arguments or output."""
        self._add(
            "crewai_step",
            step_type=type(step).__name__,
            tool=getattr(step, "tool", None) if isinstance(getattr(step, "tool", None), str) else None,
        )

    def crewai_task(self, output: Any) -> None:
        """Called by CrewAI when a Task finishes."""
        raw = getattr(output, "raw", None)
        self._add("crewai_task_finished", output_chars=len(raw) if isinstance(raw, str) else None)

    def after_agent(self, callback_context: Any) -> None:
        self._add("agent_finished", total_ms=round((time.perf_counter() - self._run_started) * 1000))
        return None

    # -------------------------------------------------------------- output
    def callbacks(self) -> dict:
        """Keyword arguments for `google.adk.agents.Agent(...)`."""
        return {
            "before_model_callback": self.before_model,
            "after_model_callback": self.after_model,
            "on_model_error_callback": self.on_model_error,
            "before_tool_callback": self.before_tool,
            "after_tool_callback": self.after_tool,
            "on_tool_error_callback": self.on_tool_error,
            "after_agent_callback": self.after_agent,
        }

    def summary(self) -> dict:
        errors = [r for r in self.records if r["kind"] in ("model_error", "tool_error")]
        tool_done = [r for r in self.records if r["kind"] == "tool_call_finished"]
        return {
            "agent": self.agent_name,
            "trace_id": self.trace_id,
            "started_unix": self.started_unix,
            "finished_unix": time.time(),
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "prompt_variant": _variant(),
            "model_calls": sum(1 for r in self.records if r["kind"] == "model_call_finished"),
            "tool_calls": len(tool_done),
            "tool_calls_not_ok": sum(1 for r in tool_done if r.get("ok") is False),
            "errors": len(errors),
            "truncated": len(self.records) >= MAX_RECORDS,
            "guardrails": {
                "enabled": self.guard is not None,
                "inputs_blocked": len(self.guard.blocked) if self.guard else 0,
                "tool_outputs_flagged": len(self.guard.tool_flags) if self.guard else 0,
            },
            "records": self.records,
        }
