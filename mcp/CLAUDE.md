# MCP Local Instructions

## Purpose
Real MCP diagnostic tools exposing controlled, bounded, auditable access to the
Phase 2 simulated production environment (and, for `get_git_diff`, this repo's own
git history). Mukund's primary responsibility on paper (implemented by Deepu — see
root CLAUDE.md "Development Ownership").

## Owned
- `config.py` — no secrets; `PRODUCTION_BASE_URL`, timeouts, `get_git_diff` path
  allowlist, `run_diagnostic` name allowlist.
- `production_client.py` — bounded (5s timeout) HTTP client to `production/`;
  raises typed errors instead of leaking raw exceptions.
- `git_diff_tool.py` — bounded, allowlisted `git log -p`/`git diff` against this
  repo only, restricted to `production/`, `backend/`, `mcp/`, `docs/`. No arbitrary
  path or shell access.
- `audit.py` — local in-process audit log of every tool call (name, args, duration,
  ok/error). Not the full NEXUS event bus — that's Phase 6 ("Event Bridge +
  Backend"); this is the Phase-3-local auditability the original contract asked for.
- `tools.py` — the 7 tool implementations, each returning `{"ok": bool, ...}` and
  never raising to the caller.
- `server.py` — registers the 7 tools on a real `mcp.server.mcpserver.MCPServer`
  (stdio transport). This is genuine MCP protocol, not a labeled wrapper.

## The 7 tools
```text
get_metrics()                                  -> production /metrics
query_logs(level?, limit?)                     -> production /logs (+ level filter)
get_trace(trace_id?, limit?)                   -> production /traces[/{id}]
get_recent_deployments(limit?)                 -> production /changes
get_git_diff(paths?, max_commits?)             -> real git log -p, allowlisted paths
get_database_stats()                           -> production /db/diagnostics
run_diagnostic(name)                           -> named, pre-approved composite check
                                                   (connectivity_check / error_rate_check
                                                   / order_status_check) over the above
```
`run_diagnostic` never accepts arbitrary code/SQL/shell — only one of the 3 fixed
names in `config.DIAGNOSTIC_NAMES`.

## Second MCP server: analysis tools (2026-10-18)
`analysis_server.py` + `analysis_tools.py` + `runbooks/*.md`: three more tools from a SEPARATE MCP server (own process), so agents talk to two independent tool servers.
- `search_runbook(query, limit)` — file parser: splits the Markdown runbooks into sections and returns best matches (reference material, flagged "not evidence").
- `evaluate_expression(expression)` — calculator: arithmetic only via the AST (no names/calls/attributes, bounded powers).
- `detect_latency_step(path, limit)` — statistics: percentiles and a step-change test over recent shop traces, with the onset time.
Off by default; `NEXUS_ENABLE_ANALYSIS_TOOLS=1` gives `metrics_agent` the last two and `logs_traces_agent` the first
(`agents/common/mcp_connection.py::ANALYSIS_TOOLS_BY_AGENT`). Tests: `tests/test_analysis_tools.py` (32 unit), `tests/test_analysis_protocol.py` (2, real MCP over stdio).

## Web search (2026-10-19)
`web_search(query, limit)` on the analysis server: public search through DuckDuckGo's plain-HTML page (no API key). OFF unless `NEXUS_ENABLE_WEB_SEARCH=1`
(separate from the analysis switch, because the query leaves the machine). Queries that look like secrets, URLs, IP addresses or internal host names are refused before anything is sent; at most 5 results with short snippets; output is flagged `untrusted_external_content`
and the agents' after-tool guard screens it. Given to `logs_traces_agent` and `change_analysis_agent`. Tests: `tests/test_web_search.py` (local fake search page, no network).

## Dependency isolation
Own venv: `.venv-mcp/` at repo root (gitignored), own `requirements.txt`. Never
install into the shared backend/production venv or `.venv-orchestrator/`.

```bash
python -m venv .venv-mcp
.venv-mcp/Scripts/python -m pip install -r mcp/requirements.txt
```

## Contract
Input schemas are plain Python type hints on each tool function; the MCP SDK derives
JSON schema from them. Return type must be `dict[str, Any]` (not bare `dict`) and
tools are registered with `structured_output=True` in `server.py`, or the SDK
refuses structured output (`InvalidSignature`) — verified during Phase 3
implementation. No arbitrary filesystem/system access; no secrets in any
response (these tools never touch `GROQ_API_KEY`).

## get_git_diff is disabled by default (2026-10-12)
The repo's own history contains the simulator's fault-injection code and docs, so exposing it to agents leaks the
answer. The tool still exists (tool list/protocol unchanged) but returns `ok: false` unless `NEXUS_ENABLE_GIT_DIFF=1`.
The Change Analysis Agent no longer lists it.

## Rules
Tools only ever touch the controlled `production/` HTTP API or this repo's own git
history (never a real system, never files outside the allowlisted paths). Full
`MCP_TOOL_CALL`/`MCP_TOOL_RESULT` events into the NEXUS event bus are Phase 6 work
(`audit.py` covers local auditability until then — do not build the full event
bridge here). Do not label this "MCP" if it stops being a real protocol server —
`tests/test_server_protocol.py` exists specifically to keep that honest.

## Status
Phase 3: **implemented + tested**. All 7 tools work over the real MCP wire protocol
against the real (Docker and non-Docker) Phase 2 production service.

## Test
```bash
# start production first (either):
docker compose up -d production
# or: cd production && ../.venv/Scripts/python -m uvicorn service:app --port 8001

.venv-mcp/Scripts/python -m pytest mcp/tests -q
```
22 tests: 16 unit (`test_tools.py`, direct function calls), 5 real-protocol
(`test_server_protocol.py`, subprocess + `mcp.ClientSession` over stdio), 1 audit
log (`test_audit.py`).

## Usually inspect
`tools.py`, `server.py`, `docs/API_CONTRACT.md`, `docs/PROJECT_STATE.md`

## Usually don't touch
`backend/`, `production/`, `orchestrator/` (separate verified components, separate
venvs)
