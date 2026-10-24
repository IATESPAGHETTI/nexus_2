"""Shared runner for the 4 independent NEXUS diagnostic agents (Phase 4).

Each concrete agent (agents/metrics, agents/logs_traces, agents/change_analysis,
agents/database) is a thin config (name, instruction, allowed MCP tool names) built
on top of this. This module owns:

  - building a real ADK LlmAgent, connected to the real Phase 3 MCP server via
    McpToolset (never importing mcp/tools.py directly, never calling production/
    HTTP endpoints itself — root CLAUDE.md 2.1 / agents/CLAUDE.md "do not bypass MCP")
  - using GPT-OSS 120B via Groq with `include_reasoning=False`, the fix verified in
    the Phase 2.5 spike (orchestrator/spike/SPIKE_RESULT.md) — required or
    multi-turn tool-calling breaks on Groq's GPT-OSS models
  - collecting the real tool call/response pairs from the ADK event stream as
    evidence, and handing them to agents.common.finding.build_finding so the
    observation/interpretation split is enforced structurally, not just by prompt
"""

from __future__ import annotations

import sys
from pathlib import Path

import litellm
from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import InMemoryRunner
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from google.genai import types

from callbacks import AgentMonitor
from guard_callbacks import AgentGuard, guardrails_enabled, merge_callbacks
from prompt_variants import apply_variant
from finding import build_finding, make_evidence_item, now_iso
from mcp_connection import (
    ANALYSIS_INSTRUCTION,
    WEB_SEARCH_INSTRUCTION,
    analysis_server_connection_params,
    analysis_tools_for,
    mcp_server_connection_params,
)
from usage_tally import UsageTally

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
load_dotenv(REPO_ROOT / ".env")

from runtime_config import litellm_model_name, resolve_runtime_config  # noqa: E402

# Groq's free-tier TPM limit (8000 tokens/min, shared across all agents) is
# routinely tripped when the Incident Manager dispatches to multiple diagnostic
# agents in parallel (observed directly during Phase 5 implementation). LiteLLM's
# built-in retry-with-backoff absorbs transient 429s instead of failing the whole
# parallel dispatch. See docs/PROJECT_STATE.md "Known Issues".
litellm.num_retries = 5

DEFAULT_INSTRUCTION_SUFFIX = (
    "\n\nYou MUST call at least one of your tools to gather real evidence before "
    "answering — never guess or answer from general knowledge. After the tool "
    "result(s) come back, write a short (1-3 sentence) interpretation grounded "
    "only in what the tool(s) actually returned. End your entire reply with a "
    "final line formatted EXACTLY as: CONFIDENCE: <a number between 0 and 1> "
    "reflecting how confident you are in your interpretation given the evidence."
)


class DiagnosticAgent:
    def __init__(
        self,
        agent_name: str,
        instruction: str,
        allowed_tools: list[str],
        default_question: str = "Investigate using your available tools and report findings.",
        description: str = "",
    ):
        self.agent_name = agent_name
        self.instruction = apply_variant(instruction + DEFAULT_INSTRUCTION_SUFFIX, agent_name)
        self.allowed_tools = allowed_tools
        self.default_question = default_question
        self.description = description

    @staticmethod
    def _callbacks(monitor: AgentMonitor | None) -> dict:
        """Monitor first (observe-only), then the security guard (may modify/block)."""
        if monitor is None:
            return {}
        parts = [monitor.callbacks()]
        if guardrails_enabled():
            guard = AgentGuard(monitor, check_abuse=True)
            monitor.guard = guard
            parts.append(guard.callbacks())
        return merge_callbacks(*parts)

    def _tool_names(self) -> list[str]:
        return [*self.allowed_tools, *analysis_tools_for(self.agent_name)]

    def build_adk_agent(self, monitor: AgentMonitor | None = None) -> Agent:
        toolsets = [
            McpToolset(
                connection_params=mcp_server_connection_params(),
                tool_filter=self.allowed_tools,
            )
        ]
        extra = analysis_tools_for(self.agent_name)
        if extra:  # NEXUS_ENABLE_ANALYSIS_TOOLS=1: a second, independent MCP server
            toolsets.append(McpToolset(connection_params=analysis_server_connection_params(), tool_filter=extra))
        provider, _ = resolve_runtime_config()
        model_kwargs = {"include_reasoning": False} if provider == "groq" else {}
        return Agent(
            name=self.agent_name,
            description=self.description,
            model=LiteLlm(model=litellm_model_name(), **model_kwargs),
            instruction=self.instruction + self._extra_tool_instruction(extra),
            tools=toolsets,
            **self._callbacks(monitor),
        )

    @staticmethod
    def _extra_tool_instruction(extra: list[str]) -> str:
        """Describe only the extra tools this agent actually has (the two switches are independent)."""
        if not extra:
            return ""
        if any(tool != "web_search" for tool in extra):
            text = ANALYSIS_INSTRUCTION
        else:
            text = "\n\nEXTRA TOOLS from a second tool server (use them only when they help):"
        return text + (WEB_SEARCH_INSTRUCTION if "web_search" in extra else "")

    async def investigate(self, question: str) -> dict:
        monitor = AgentMonitor(self.agent_name)
        agent = self.build_adk_agent(monitor)
        runner = InMemoryRunner(agent=agent, app_name=f"nexus_{self.agent_name}")
        session = await runner.session_service.create_session(
            app_name=f"nexus_{self.agent_name}", user_id="nexus"
        )

        pending_calls: dict[str, dict] = {}
        evidence: list[dict] = []
        final_text = ""
        window_start = now_iso()
        usage = UsageTally()

        user_message = types.Content(role="user", parts=[types.Part(text=question)])

        try:
            async for event in runner.run_async(
                user_id="nexus",
                session_id=session.id,
                new_message=user_message,
            ):
                usage.add_event(event)
                if not (event.content and event.content.parts):
                    continue
                for part in event.content.parts:
                    call = getattr(part, "function_call", None)
                    if call and call.name in self._tool_names():
                        key = call.id or call.name
                        pending_calls[key] = {"tool": call.name, "arguments": dict(call.args or {})}

                    response = getattr(part, "function_response", None)
                    if response and response.name in self._tool_names():
                        key = response.id or response.name
                        call_info = pending_calls.pop(key, {"tool": response.name, "arguments": {}})
                        raw = response.response
                        # McpToolset returns the full MCP CallToolResult envelope
                        # ({"content", "structuredContent", "isError"}); unwrap to the
                        # tool's own structured dict (mcp/tools.py's real return value)
                        # when present — still the real, unmodified tool output.
                        if isinstance(raw, dict) and "structuredContent" in raw:
                            result = raw["structuredContent"]
                        else:
                            result = raw
                        evidence.append(
                            make_evidence_item(
                                tool=call_info["tool"],
                                arguments=call_info["arguments"],
                                result=result,
                            )
                        )

                    text = getattr(part, "text", None)
                    if text:
                        final_text += text
        finally:
            # Each task spawns its own MCP server process (stdio). Without this the
            # process outlived the task: ~1 leaked process per agent per round.
            for tool in agent.tools:
                close = getattr(tool, "close", None)
                if close is not None:
                    try:
                        await close()
                    except Exception:  # never let cleanup mask the real result/error
                        pass

        finding = build_finding(
            agent_name=self.agent_name,
            evidence=evidence,
            model_text=final_text,
            window_start=window_start,
        )
        # Real model usage for this task; the orchestrator pops it off before the
        # Finding is stored or shown to other agents (orchestrator/budget.py).
        finding["usage"] = usage.as_dict()
        # Callback trace; the orchestrator pops it and stores it as an AGENT_MONITOR event.
        finding["monitoring"] = monitor.summary()
        return finding
