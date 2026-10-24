"""ADK security callbacks (course requirement 8), built on the framework-free `nexus_guard`.

  before_model: the FIRST user message of a run (the question/task text) is screened for abuse and prompt
                injection. If it fails, the model is never called: a refusal reply is returned instead.
  after_tool:   every MCP tool result is type-checked, size-bounded and stripped of instruction-like text
                before the model sees it (and before it is stored as evidence).

`merge_callbacks` chains these after the observe-only `AgentMonitor` (ADK stops a chain at the first callback
that returns something, so the monitor must come first). Set NEXUS_GUARDRAILS=0 to disable (for A/B runs only).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from google.adk.models.llm_response import LlmResponse  # noqa: E402
from google.genai import types  # noqa: E402

from nexus_guard import guard_tool_result, screen_user_text  # noqa: E402


def guardrails_enabled() -> bool:
    return os.environ.get("NEXUS_GUARDRAILS", "1") != "0"


class AgentGuard:
    def __init__(self, monitor: Any = None, check_abuse: bool = True) -> None:
        self.monitor = monitor
        self.check_abuse = check_abuse
        self.screened = False
        self.blocked: list[dict] = []
        self.tool_flags: list[dict] = []

    def _note(self, kind: str, **fields: Any) -> None:
        if self.monitor is not None:
            self.monitor._add(kind, **fields)

    def before_model(self, callback_context: Any, llm_request: Any) -> LlmResponse | None:
        if self.screened:
            return None
        self.screened = True
        text = ""
        for content in getattr(llm_request, "contents", None) or []:
            if getattr(content, "role", None) == "user":
                text = " ".join(getattr(p, "text", "") or "" for p in (content.parts or []))
                break
        result = screen_user_text(text, max_chars=200000, check_abuse=self.check_abuse)  # reasoning agents receive large evidence JSON
        if result.allowed:
            return None
        self.blocked.append(result.as_dict())
        self._note("input_blocked", flags=result.flags)
        return LlmResponse(
            content=types.Content(
                role="model",
                parts=[types.Part(text="Request refused by the NEXUS input guardrail (" + ", ".join(result.flags) + ").")],
            )
        )

    def after_tool(self, tool: Any, args: dict, tool_context: Any, tool_response: Any) -> dict | None:
        if not isinstance(tool_response, dict):
            return None
        envelope = "structuredContent" in tool_response or "content" in tool_response
        payload = tool_response.get("structuredContent") if envelope else tool_response
        safe, flags = guard_tool_result(payload)
        if not flags:
            return None
        self.tool_flags.append({"tool": getattr(tool, "name", "?"), "flags": flags})
        self._note("tool_output_guarded", tool=getattr(tool, "name", "?"), flags=flags)
        if not envelope:
            return safe
        out = dict(tool_response)
        out["structuredContent"] = safe
        out["content"] = [{"type": "text", "text": json.dumps(safe, default=str)}]
        return out

    def callbacks(self) -> dict:
        return {"before_model_callback": self.before_model, "after_tool_callback": self.after_tool}


def merge_callbacks(*parts: dict) -> dict:
    """Combine callback dicts; same hook from several sources becomes a list in the given order."""
    merged: dict[str, list] = {}
    for part in parts:
        for hook, fn in part.items():
            merged.setdefault(hook, []).append(fn)
    return {hook: fns[0] if len(fns) == 1 else fns for hook, fns in merged.items()}
