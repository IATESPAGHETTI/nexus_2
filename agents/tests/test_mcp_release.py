"""Regression: each investigation used to leak one MCP stdio server process.

Spawns the REAL MCP server through the same McpToolset the agents use, releases it
with DiagnosticAgent._release, and asserts the server process is gone. No LLM call.
"""

import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agents" / "common"))

from diagnostic_agent import DiagnosticAgent  # noqa: E402
from mcp_connection import MCP_SERVER_PYTHON  # noqa: E402

pytestmark = pytest.mark.skipif(not MCP_SERVER_PYTHON.exists(), reason=".venv-mcp not installed")


def _mcp_server_pids() -> set[str]:
    if sys.platform == "win32":
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -like '*mcp*server.py*' } | ForEach-Object { $_.ProcessId }"],
            capture_output=True, text=True,
        ).stdout
    else:
        out = subprocess.run(["pgrep", "-f", "mcp/server.py"], capture_output=True, text=True).stdout
    return set(out.split())


def test_release_kills_mcp_server_process():
    from google.adk.runners import InMemoryRunner

    agent = DiagnosticAgent("leak_probe", "probe", ["get_metrics"]).build_adk_agent()
    runner = InMemoryRunner(agent=agent, app_name="leak_probe")
    before = _mcp_server_pids()

    async def run():
        tools = await agent.tools[0].get_tools()  # forces the stdio server to spawn
        assert tools
        assert len(_mcp_server_pids() - before) >= 1, "server did not start"
        await DiagnosticAgent._release(agent, runner)
        # Checked while the event loop is still alive, like the long-running A2A
        # service: closing the loop would reap the process and hide the leak.
        await asyncio.sleep(1.0)
        assert _mcp_server_pids() - before == set(), "MCP server process leaked after release"

    asyncio.run(run())
