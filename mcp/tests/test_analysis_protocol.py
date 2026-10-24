"""Real MCP protocol test for the SECOND server (mcp/analysis_server.py): a subprocess over stdio and an actual
mcp.ClientSession, i.e. genuine JSON-RPC over the Model Context Protocol. No shop needed for these three calls.

    .venv-mcp/Scripts/python -m pytest mcp/tests/test_analysis_protocol.py -q
"""

import sys
from pathlib import Path

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

MCP_DIR = Path(__file__).resolve().parents[1]


def _params() -> StdioServerParameters:
    return StdioServerParameters(command=sys.executable, args=[str(MCP_DIR / "analysis_server.py")], cwd=str(MCP_DIR))


@pytest.mark.asyncio
async def test_second_server_lists_exactly_its_three_tools():
    async with stdio_client(_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
    assert {t.name for t in tools.tools} == {"search_runbook", "evaluate_expression", "detect_latency_step", "web_search"}
    for tool in tools.tools:
        assert tool.input_schema.get("properties"), tool.name          # schemas derived from the type hints


@pytest.mark.asyncio
async def test_calculator_and_runbook_work_over_the_wire_and_refuse_bad_input():
    async with stdio_client(_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            calc = await session.call_tool("evaluate_expression", {"expression": "(7 / 17) * 100"})
            evil = await session.call_tool("evaluate_expression", {"expression": "__import__('os')"})
            book = await session.call_tool("search_runbook", {"query": "slow responses with no errors", "limit": 1})
    assert calc.structured_content["ok"] is True and calc.structured_content["result"] == pytest.approx(41.176471)
    assert evil.structured_content["ok"] is False
    assert book.structured_content["ok"] is True and book.structured_content["matches"][0]["source"] == "latency.md"
