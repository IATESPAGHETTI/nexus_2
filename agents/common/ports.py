"""Single source of truth for each diagnostic agent's A2A service port.

Each of the 4 diagnostic agents runs as its OWN OS process listening on its own
port — genuinely independently addressable, not shared in-process objects.
"""

import os

# Where a service LISTENS. Containers set NEXUS_BIND_HOST=0.0.0.0.
A2A_HOST = os.environ.get("NEXUS_BIND_HOST", "127.0.0.1")
# The name other services use to reach this one (goes into the Agent Card). Containers set it to the service name.
ADVERTISE_HOST = os.environ.get("NEXUS_ADVERTISE_HOST", A2A_HOST)

A2A_PORTS = {
    "metrics_agent": 8101,
    "logs_traces_agent": 8102,
    "change_analysis_agent": 8103,
    "database_agent": 8104,
    # Phase 6: Evidence Agent + Root-Cause Critic, same real-A2A-service pattern.
    "evidence_agent": 8105,
    "root_cause_critic": 8106,
    # Phase 8: Recovery Agent, same real-A2A-service pattern. Note: this agent
    # has NO MCP tool access (ReasoningAgent-based, like Evidence/Critic) and
    # NO execution capability of its own -- it only proposes a RecoveryPlan;
    # guardrails/ is the only code path that ever executes anything.
    "recovery_agent": 8107,
}


def base_url(agent_name: str) -> str:
    """Address of an agent as seen by its CALLERS. NEXUS_AGENT_URL_<NAME> (e.g. NEXUS_AGENT_URL_METRICS_AGENT=
    http://metrics:8101) overrides the local default, which is how the orchestrator finds containers."""
    override = os.environ.get(f"NEXUS_AGENT_URL_{agent_name.upper()}")
    if override:
        return override.rstrip("/")
    return f"http://127.0.0.1:{A2A_PORTS[agent_name]}"


def agent_card_url(agent_name: str) -> str:
    return f"{base_url(agent_name)}/.well-known/agent-card.json"
