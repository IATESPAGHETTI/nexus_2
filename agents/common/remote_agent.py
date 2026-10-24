"""Builds ADK `RemoteA2aAgent` proxies for the 4 diagnostic A2A services.

A `RemoteA2aAgent` is ADK's real A2A client wrapper: calling/invoking it performs
an actual HTTP request to the target service's A2A JSON-RPC endpoint (resolved
from its Agent Card) and translates the real task response back into ADK Events.
This is what the Incident Manager uses to reach each diagnostic agent — genuine
network calls to independently running processes, never a direct Python call into
another agent's code.
"""

import ipaddress
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx
from google.adk.agents.remote_a2a_agent import RemoteA2aAgent

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import nexus_trace  # noqa: E402

from ports import agent_card_url


def _is_loopback(host: str | None) -> bool:
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def needs_internal_card(card_url: str) -> bool:
    """True when the ADK client would refuse this card URL (plain http to a non-loopback host) AND the owner has
    declared the network private with NEXUS_ALLOW_INTERNAL_HTTP=1 (set only in docker-compose, where services reach each
    other by name on a private network). Anywhere else the client keeps its strict https-only rule."""
    if os.environ.get("NEXUS_ALLOW_INTERNAL_HTTP") != "1":
        return False
    parsed = urlparse(card_url)
    return parsed.scheme == "http" and not _is_loopback(parsed.hostname)


def fetch_internal_card(card_url: str):
    """Fetch an Agent Card over plain http inside the private network and hand ADK the parsed card OBJECT. The client
    only applies its https rule to card URLs it fetches itself; a card passed in directly is the caller's responsibility,
    which is exactly the trust decision NEXUS_ALLOW_INTERNAL_HTTP records."""
    from google.adk.a2a import _compat

    response = httpx.get(card_url, timeout=5.0)
    response.raise_for_status()
    return _compat.parse_agent_card(response.json())


def build_remote_agent(agent_name: str, description: str) -> RemoteA2aAgent:
    """Client proxy for one agent. When an investigation trace is active, the HTTP client sends a W3C
    `traceparent` header (a fresh child span per call) so the agent's records carry the same trace_id."""
    kwargs = {}
    ctx = nexus_trace.child_context()
    if ctx is not None:
        kwargs["httpx_client"] = httpx.AsyncClient(headers={"traceparent": ctx.traceparent()}, timeout=600.0)
    card_source = agent_card_url(agent_name)
    if needs_internal_card(card_source):
        card_source = fetch_internal_card(card_source)
    remote = RemoteA2aAgent(
        name=agent_name,
        agent_card=card_source,
        description=description,
        **kwargs,
    )
    return remote
