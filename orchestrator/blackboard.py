"""Blackboard topology (course requirement 1): the controller side.

NEXUS_TOPOLOGY=blackboard makes `investigation.py` talk to its agents through the shared board instead of
passing data as A2A message bodies:

  controller  posts `description` / `request` / `review_request` entries to the board (backend incident record)
  agent       receives only a pointer, READS the board itself, writes its `finding` / `hypotheses` / `critique`
  controller  reads the agent's entry back from the board

The two functions below return exactly the shapes of the hub-and-spoke calls they replace
(`incident_manager.investigate_incident` and `remote_call.call_remote_agent`), so the verdict loop, budgets,
guardrails, recovery and reporting in `investigation.py` run unchanged on either topology.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "agents" / "common"))

import event_bridge  # noqa: E402
import nexus_trace  # noqa: E402
from remote_call import call_remote_agent  # noqa: E402

_TIMEOUT = 15.0


TOPOLOGIES = ("hub", "blackboard", "pipeline")
HANDOFF_MAX_CHARS = 900


def topology() -> str:
    name = os.environ.get("NEXUS_TOPOLOGY", "hub").strip().lower()
    return name if name in TOPOLOGIES else "hub"


def enabled() -> bool:
    """True when agents talk through the shared board (the blackboard AND the pipeline use it)."""
    return topology() in ("blackboard", "pipeline")


def pipeline() -> bool:
    return topology() == "pipeline"


def _post(incident_id: str, entry_type: str, author: str, content: dict) -> dict:
    ctx = nexus_trace.current()
    response = httpx.post(
        f"{event_bridge.BACKEND_URL}/incidents/{incident_id}/blackboard",
        json={"type": entry_type, "author": author, "content": content, "trace_id": ctx.trace_id if ctx else None},
        timeout=_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def _board(incident_id: str) -> list[dict]:
    response = httpx.get(f"{event_bridge.BACKEND_URL}/incidents/{incident_id}/blackboard", timeout=_TIMEOUT)
    response.raise_for_status()
    return response.json()["entries"]


def _pointer(incident_id: str, role: str) -> str:
    return json.dumps({"nexus_board": {"incident_id": incident_id, "role": role}})


async def _ask(incident_id: str, name: str, description: str, role: str) -> dict:
    """Sends the pointer, then reads the agent's entry from the board. Returns a call_remote_agent-shaped dict
    whose `response` is the entry content plus the agent's usage/monitoring bookkeeping."""
    call = await call_remote_agent(name, description, _pointer(incident_id, role))
    ack = call.get("response") if isinstance(call.get("response"), dict) else {}
    entry_id = ack.get("board_entry")
    entry = next((e for e in await asyncio.to_thread(_board, incident_id) if e["entry_id"] == entry_id), None)
    if entry is None or entry["author"] != name:
        return {**call, "response": None}
    response = dict(entry["content"])
    response["usage"] = ack.get("usage")
    response["monitoring"] = ack.get("monitoring")
    return {**call, "response": response}


async def board_investigate(incident_id: str, question: str, agent_names: list[str], descriptions: dict[str, str]) -> dict:
    """Specialists: post the task to the board, wake each one, collect what they wrote."""
    if not any(e["type"] == "description" for e in await asyncio.to_thread(_board, incident_id)):
        await asyncio.to_thread(_post, incident_id, "description", "incident_manager", {"text": question})
    await asyncio.to_thread(_post, incident_id, "request", "incident_manager", {"text": question, "targets": agent_names})

    async def one(name: str):
        try:
            return name, await _ask(incident_id, name, descriptions.get(name, name), "diagnose")
        except Exception:  # noqa: BLE001 -- an unreachable agent is reported as "no response", like the hub path
            return name, None

    findings, a2a = {}, {}
    for name, call in await asyncio.gather(*(one(n) for n in agent_names)):
        finding = call["response"] if call else None
        if isinstance(finding, dict) and "finding_id" in finding:
            findings[name] = finding
            a2a[name] = {"task_id": call["task_id"], "context_id": call["context_id"]}
    return {
        "incident_description": question, "findings": findings, "a2a": a2a,
        "agents_dispatched": agent_names, "agents_responded": list(findings),
    }


async def board_synthesize(incident_id: str, name: str, description: str) -> dict:
    """Evidence Agent: it reads every specialist's finding from the board itself."""
    return await _ask(incident_id, name, description, "synthesize")


async def board_review(incident_id: str, name: str, description: str, hypothesis: dict) -> dict:
    """Critic: controller posts which hypothesis to review; the critic reads it and all evidence from the board."""
    await asyncio.to_thread(_post, incident_id, "review_request", "incident_manager", {"hypothesis": hypothesis})
    return await _ask(incident_id, name, description, "review")


# ------------------------------------------------------------------------------------------------ pipeline topology
FIRST_STAGE = "metrics_agent"


def build_handoff(upstream_agent: str, finding: dict) -> str:
    """What the next stage is told about the upstream agent's result: its own written interpretation plus the plain
    summary of which tools it used. This text comes from a MODEL's output, so it is treated as untrusted data on its way to
    the next model: bounded, and screened/redacted with the same guard used for tool output."""
    from nexus_guard import redact_text

    interpretation = str(finding.get("interpretation") or "").strip()
    observation = str(finding.get("observation") or "").strip()
    text = f"{interpretation}\n[{observation}]" if observation else interpretation
    text, _flags = redact_text(text[:HANDOFF_MAX_CHARS])
    return (
        f"\n\nHANDOFF from the {upstream_agent} (the first stage of this investigation). It reported: {text}\n"
        f"Use this to focus where you look: investigate that endpoint, symptom and time window in YOUR area, and say whether your "
        f"evidence agrees or disagrees. Report only what your own tools return."
    )


async def pipeline_investigate(incident_id: str, question: str, agent_names: list[str], descriptions: dict[str, str]) -> dict:
    """Sequential hand-off over the shared board: the Metrics agent finds WHERE and WHEN first; the other selected
    specialists then run in parallel, each told what the Metrics agent found. Same return shape as board_investigate.
    With no Metrics agent in the selection (or only one agent) it degrades to the plain blackboard dispatch."""
    if FIRST_STAGE not in agent_names or len(agent_names) < 2:
        return await board_investigate(incident_id, question, agent_names, descriptions)
    first = await board_investigate(incident_id, question, [FIRST_STAGE], descriptions)
    rest = [n for n in agent_names if n != FIRST_STAGE]
    upstream = first["findings"].get(FIRST_STAGE)
    second_question = question + (build_handoff(FIRST_STAGE, upstream) if upstream else "")
    second = await board_investigate(incident_id, second_question, rest, descriptions)
    return {
        "incident_description": question,
        "findings": {**first["findings"], **second["findings"]},
        "a2a": {**first["a2a"], **second["a2a"]},
        "agents_dispatched": agent_names,
        "agents_responded": [*first["agents_responded"], *second["agents_responded"]],
        "handoff_from": FIRST_STAGE if upstream else None,
    }
