# crewai_critic — Local Instructions

## Purpose
The Root-Cause Critic implemented with **CrewAI** and served over real **A2A**, so NEXUS has an ADK<->CrewAI
boundary (course requirements 6 and 7). Folder is NOT called `crewai/` on purpose: that would shadow the package.

## Owned
- `crewai_common.py` — shared plumbing: provider-aware CrewAI `LLM` (deepseek | gemini | groq), `run_crew` (real CrewAI `Agent` + `Task` +
  `Crew`, with `step_callback`/`task_callback` feeding the same `AgentMonitor` as the ADK agents, and REAL token usage from
  `Crew.token_usage`), `CrewAIExecutor` (a2a-sdk executor; blackboard board mode; failures become failed A2A tasks) and `build_a2a_app`
  (CrewAI ships cards and clients but no server, so the A2A server is a2a-sdk) + trace middleware.
- `a2a_service.py` — Root-Cause Critic in CrewAI (`root_cause_critic`, 8106). Contract in ADK-free `agents/critic/critic_core.py`.
- `evidence_service.py` — Evidence Agent in CrewAI (`evidence_agent`, 8105). Contract in ADK-free `agents/evidence/evidence_core.py`.
  Both add `framework: "crewai"`, `usage` and `monitoring` to their reply; `CRITIC_STUB=1` / `NEXUS_CREWAI_STUB=1` = no model call.
- `SPIKE_RESULT.md` — the compatibility spike (read first).

## Run / select
`NEXUS_CRITIC_FRAMEWORK=crewai` and/or `NEXUS_EVIDENCE_FRAMEWORK=crewai` (owner env vars, read by `backend/app/demo.py`, `evaluation/stack.py`
and the compose file) start that agent from `.venv-crewai` instead of the ADK one, at the same A2A address. Default stays ADK.
Manual: `.venv-crewai/Scripts/python crewai_critic/a2a_service.py` / `evidence_service.py`.

## Dependencies
Own venv `.venv-crewai` (gitignored): `crewai[a2a,google-genai]==1.15.28`, `a2a-sdk[http-server]==0.3.26`, `litellm==1.101.0` (CrewAI falls back to LiteLLM for model names it does not know, e.g. new Gemini models). The ADK venvs keep
`a2a-sdk==1.1.4`; they interoperate over the wire (verified), they never share a venv.

## Tests
- `.venv-crewai/Scripts/python -m pytest crewai_critic/tests -q` (8: both services in stub mode, callbacks, usage, provider key check; 0 tokens)
- `.venv-orchestrator/Scripts/python -m pytest orchestrator/tests/test_crewai_critic_a2a.py -q` (ADK client -> CrewAI service
  over A2A for BOTH CrewAI agents, stub, 0 tokens, with trace-id propagation; skipped if `.venv-crewai` is missing)

## Status
implemented + tested. Verified live (2026-10-18, Gemini free tier, db_slowdown): ADK specialists + CrewAI Evidence + CrewAI Critic -> DIAGNOSED in 20 s,
10 model calls, CrewAI tokens measured (6,007 and 5,721). Limits: `step_callback` fires only on tool steps and these two CrewAI agents use no tools
(thought-only), so only task/model records appear; each CrewAI service handles one request at a time per process.
