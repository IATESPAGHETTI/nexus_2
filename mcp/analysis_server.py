"""NEXUS MCP analysis server: a runbook parser, a safe calculator, a statistics tool and an opt-in web search (course requirement 2).

    .venv-mcp/Scripts/python mcp/analysis_server.py

A second, independent MCP server (stdio). Agents connect to it in addition to the diagnostic server when
NEXUS_ENABLE_ANALYSIS_TOOLS=1 (off by default so default behaviour matches the measured baseline).
"""

from mcp.server.mcpserver import MCPServer

import analysis_tools

mcp_server = MCPServer(name="nexus-analysis")

mcp_server.tool(structured_output=True)(analysis_tools.search_runbook)
mcp_server.tool(structured_output=True)(analysis_tools.evaluate_expression)
mcp_server.tool(structured_output=True)(analysis_tools.detect_latency_step)
mcp_server.tool(structured_output=True)(analysis_tools.web_search)    # refuses unless NEXUS_ENABLE_WEB_SEARCH=1


if __name__ == "__main__":
    mcp_server.run(transport="stdio")
