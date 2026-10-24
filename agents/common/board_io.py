"""Agent-side blackboard access (course requirement 1). ADK-free, so ADK and CrewAI agents share it.

In blackboard mode the controller sends an agent only a POINTER ({"nexus_board": {"incident_id", "role"}}).
The AGENT then reads the shared board itself, does its work, and WRITES its result back to the board; its A2A
reply is a small acknowledgement. Roles:

  diagnose    read the incident description (and any request addressed to me)      -> post `finding`
  synthesize  read the latest `finding` of every specialist                        -> post `hypotheses`
  review      read the `review_request` + every specialist's evidence              -> post `critique`

Security: the backend address comes from NEXUS_BACKEND_URL, never from the message (no SSRF through a
crafted A2A message); incident ids must look like INC-<hex>.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
import nexus_trace  # noqa: E402

ROLES = ("diagnose", "synthesize", "review")
_INCIDENT_RE = re.compile(r"^INC-[0-9a-f]{4,32}$")
_TIMEOUT = 15.0


def backend_url() -> str:
    return os.environ.get("NEXUS_BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")


def parse_board_message(text: str) -> dict | None:
    """Returns {"incident_id", "role"} when `text` is a valid board pointer, else None (normal message)."""
    if not text or '"nexus_board"' not in text:
        return None
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    board = data.get("nexus_board") if isinstance(data, dict) else None
    if not isinstance(board, dict):
        return None
    incident_id, role = board.get("incident_id"), board.get("role")
    if not (isinstance(incident_id, str) and _INCIDENT_RE.match(incident_id)) or role not in ROLES:
        return None
    return {"incident_id": incident_id, "role": role}


def _headers() -> dict:
    ctx = nexus_trace.current()
    return {"traceparent": ctx.traceparent()} if ctx else {}


async def read_board(incident_id: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_headers()) as client:
        response = await client.get(f"{backend_url()}/incidents/{incident_id}/blackboard")
        response.raise_for_status()
        return response.json()["entries"]


async def post_entry(incident_id: str, entry_type: str, author: str, content: dict) -> dict:
    ctx = nexus_trace.current()
    body = {"type": entry_type, "author": author, "content": content, "trace_id": ctx.trace_id if ctx else None}
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_headers()) as client:
        response = await client.post(f"{backend_url()}/incidents/{incident_id}/blackboard", json=body)
        response.raise_for_status()
        return response.json()


def _latest(entries: list[dict], entry_type: str) -> dict | None:
    for entry in reversed(entries):
        if entry["type"] == entry_type:
            return entry
    return None


def latest_findings(entries: list[dict]) -> dict[str, dict]:
    """Latest finding per author (a later round supersedes an earlier one), exactly like the hub path."""
    found: dict[str, dict] = {}
    for entry in entries:
        if entry["type"] == "finding":
            found[entry["author"]] = entry["content"]
    return found


def build_question(role: str, entries: list[dict], author: str) -> str:
    """The text the agent would have received as its A2A message in the hub topology, rebuilt from the board."""
    if role == "diagnose":
        for entry in reversed(entries):
            if entry["type"] == "request" and author in (entry["content"].get("targets") or []):
                return str(entry["content"].get("text", ""))
        description = _latest(entries, "description")
        return str(description["content"].get("text", "")) if description else ""
    if role == "synthesize":
        return json.dumps(latest_findings(entries))
    if role == "review":
        request = _latest(entries, "review_request")
        hypothesis = request["content"].get("hypothesis", {}) if request else {}
        pool = [item for f in latest_findings(entries).values() for item in (f.get("evidence") or [])]
        return json.dumps({"hypothesis": hypothesis, "evidence_pool": pool})
    return ""


_ENTRY_FOR_ROLE = {"diagnose": "finding", "synthesize": "hypotheses", "review": "critique"}


async def run_on_board(
    investigate: Callable[[str], Awaitable[dict]], board: dict, author: str
) -> dict:
    """Read the board -> do the work -> write the result to the board. Returns the small A2A acknowledgement.
    `usage`/`monitoring` are bookkeeping for the controller's budget and audit log, so they ride in the ack,
    not on the board."""
    entries = await read_board(board["incident_id"])
    question = build_question(board["role"], entries, author)
    result = await investigate(question)
    result = dict(result) if isinstance(result, dict) else {}
    usage, monitoring = result.pop("usage", None), result.pop("monitoring", None)
    entry = await post_entry(board["incident_id"], _ENTRY_FOR_ROLE[board["role"]], author, result)
    return {"board_entry": entry["entry_id"], "role": board["role"], "usage": usage, "monitoring": monitoring}
