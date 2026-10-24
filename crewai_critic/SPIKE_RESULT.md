# CrewAI + A2A spike (2026-10-15) — PASSED (protocol + one real model call)

Goal (course requirements 6 and 7): prove an ADK client can call a CrewAI agent over real A2A.

## Versions (isolated `.venv-crewai`, repo root, gitignored)
`crewai==1.15.28`, `a2a-sdk==0.3.26` (+`[http-server]`: fastapi 0.143.2, sse-starlette 3.5.0), Python 3.10.11.
The ADK side keeps `a2a-sdk==1.1.4` in `.venv-agents` / `.venv-orchestrator`; the two never share a venv.

## Findings
1. **CrewAI ships no A2A server.** `crewai.a2a` has `A2AServerConfig` and `Agent.to_agent_card(url)` (card generation) and
   a client-side delegation wrapper (`A2AClientConfig`), but no HTTP server. So the server is built with a2a-sdk (the protocol
   library) and its `AgentExecutor` runs a real CrewAI `Agent` (`crewai_critic/spike_service.py`).
2. **Cross-version interop works.** The ADK `RemoteA2aAgent` client (a2a-sdk 1.1.4, the orchestrator's `call_remote_agent`)
   completed a task against the a2a-sdk 0.3.26 server (card `protocolVersion 0.3.0`): real task_id/context_id returned.
   Verified first in stub mode (0 tokens), then with the real model.
3. **Real model call works.** CrewAI `Agent` + `LLM(model="deepseek/deepseek-chat")` answered through the A2A task
   (`INSUFFICIENT_EVIDENCE`, "ev-1 lacks content proving DB slowness"). One call, `max_tokens=120`, input truncated to 500
   chars, i.e. well under 1k tokens (exact usage was not captured in the spike).
4. **Windows nuisance:** CrewAI's console event bus prints emoji and raises `charmap` codec errors (harmless to results) and
   prints an "Execution Traces" banner. For the real service set `PYTHONIOENCODING=utf-8`, `CREWAI_DISABLE_TELEMETRY=true`,
   `CREWAI_TRACING_ENABLED=false`, and `verbose=False`.

## Not proven yet (next step)
- The real Critic: reuse the Critic instruction + `build_critique` contract (needs the ADK-free parts of `agents/critic/agent.py`
  split into a module importable from `.venv-crewai`), Pydantic validation, usage/monitoring reporting (CrewAI `token_usage`
  and CrewAI event listeners instead of ADK callbacks), a unit test, and an orchestrator switch to call it on a new port.
- Streaming and push notifications are off (`capabilities.streaming=false`), same as the current services.
