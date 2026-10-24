"""The orchestrator as a service (platform mode): lets the backend start an investigation over HTTP instead of
spawning `run_demo.py` as a local subprocess, which a container cannot do.

    .venv-orchestrator/Scripts/python orchestrator/service.py          # listens on NEXUS_ORCHESTRATOR_PORT (8200)

  POST /investigate       {"incident_id", "description"}   -> 202, runs `run_investigation` in the background
  POST /resume-recovery   {"incident_id"}                  -> 202, runs `resume_approved_recovery`
  GET  /health            {"status", "running"}

Security: if NEXUS_INTERNAL_TOKEN is set, every POST must carry the same value in `X-Internal-Token`. Inputs are
only an incident id (INC-<hex>) and the description text, which `run_investigation` screens with the input
guardrail. At most NEXUS_MAX_CONCURRENT_INVESTIGATIONS (default 1) run at once: the simulated shop has ONE fault
state, so overlapping investigations would corrupt each other's evidence. Extra requests get 429, not a queue.
"""

from __future__ import annotations

import asyncio
import hmac
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import uvicorn  # noqa: E402
from starlette.applications import Starlette  # noqa: E402
from starlette.requests import Request  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402
from starlette.routing import Route  # noqa: E402

_INCIDENT_RE = re.compile(r"^INC-[0-9a-f]{4,32}$")
_MAX = max(1, int(os.environ.get("NEXUS_MAX_CONCURRENT_INVESTIGATIONS", "1")))
_running: set[str] = set()
_tasks: set[asyncio.Task] = set()  # keep references so background tasks are not garbage collected


def _authorised(request: Request) -> bool:
    expected = os.environ.get("NEXUS_INTERNAL_TOKEN", "")
    return not expected or hmac.compare_digest(request.headers.get("x-internal-token", ""), expected)


async def _body(request: Request) -> dict:
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


async def _run(kind: str, incident_id: str, description: str = "") -> None:
    try:
        if kind == "investigate":
            from investigation import run_investigation

            await run_investigation(description, incident_id=incident_id)
        else:
            from recovery import resume_approved_recovery

            await resume_approved_recovery(incident_id)
    except Exception as exc:  # noqa: BLE001 -- one failed run must not take the service down
        print(f"[orchestrator-service] {kind} {incident_id} failed: {type(exc).__name__}: {str(exc)[:200]}", file=sys.stderr, flush=True)
    finally:
        _running.discard(incident_id)


def _start(kind: str, incident_id: str, description: str = "") -> JSONResponse:
    if not _INCIDENT_RE.match(incident_id or ""):
        return JSONResponse({"error": "invalid incident_id"}, status_code=422)
    if incident_id in _running:
        return JSONResponse({"error": "already running for this incident"}, status_code=409)
    if len(_running) >= _MAX:
        return JSONResponse({"error": "an investigation is already running; try again when it finishes"}, status_code=429)
    _running.add(incident_id)
    task = asyncio.get_running_loop().create_task(_run(kind, incident_id, description))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return JSONResponse({"accepted": True, "incident_id": incident_id, "kind": kind}, status_code=202)


async def investigate(request: Request) -> JSONResponse:
    if not _authorised(request):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    body = await _body(request)
    description = body.get("description")
    if not isinstance(description, str) or not description.strip():
        return JSONResponse({"error": "description is required"}, status_code=422)
    return _start("investigate", str(body.get("incident_id", "")), description)


async def resume(request: Request) -> JSONResponse:
    if not _authorised(request):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    body = await _body(request)
    return _start("resume", str(body.get("incident_id", "")))


async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "nexus-orchestrator", "running": sorted(_running)})


app = Starlette(routes=[
    Route("/investigate", investigate, methods=["POST"]),
    Route("/resume-recovery", resume, methods=["POST"]),
    Route("/health", health, methods=["GET"]),
])

if __name__ == "__main__":
    uvicorn.run(app, host=os.environ.get("NEXUS_BIND_HOST", "127.0.0.1"), port=int(os.environ.get("NEXUS_ORCHESTRATOR_PORT", "8200")))
