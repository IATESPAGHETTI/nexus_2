from __future__ import annotations

import hmac
import os
import time
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict

from . import demo, incident_store

app = FastAPI(title="nexus-backend")

# Dashboard dev server (Vite, port 5173) calls this backend directly for the
# Phase 10 live-demo endpoints below via the browser's fetch, not just
# through the /api dev proxy (see dashboard/vite.config.ts) -- CORS must
# allow it. Read-only/local-dev scope: no credentials, no other origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "nexus-backend"}


@app.get("/demo/status")
def demo_status() -> dict:
    """Real system-status check for the Mission Control home page -- every
    field is a live HTTP probe result, never a hardcoded 'online'."""
    return demo.system_status()


@app.post("/demo/agents/start")
def demo_start_agents() -> dict:
    """The dashboard's agent ON switch: launches the 7 fixed agent services that
    are not already running (see demo.start_agents). Takes no input."""
    return demo.start_agents()


@app.post("/demo/agents/stop")
def demo_stop_agents() -> dict:
    """The dashboard's agent OFF switch (see demo.stop_agents). Takes no input."""
    return demo.stop_agents()


@app.post("/demo/reset-shop")
def demo_reset_shop() -> dict:
    """Clean slate for the next demo: clears injected faults and the shop's history of earlier incidents."""
    try:
        return demo.reset_shop()
    except demo.ProductionUnavailableError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


class InjectFailureRequest(BaseModel):
    fault_type: str = "bad_deployment"
    description: str = "orders endpoint intermittently failing"


@app.post("/demo/investigate")
def demo_investigate(body: InjectFailureRequest) -> dict:
    """The 'Inject Controlled Failure' button's one real action: injects a
    real fault into production/, creates a real incident, and -- only if at
    least one real A2A agent service is reachable -- launches the real
    orchestrator investigation against that incident as a detached
    subprocess (see backend/app/demo.py's module docstring for why a
    subprocess, not an in-process call)."""
    try:
        demo.inject_fault(body.fault_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except demo.ProductionUnavailableError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    incident = incident_store.create_incident(body.description)
    incident_id = incident["incident_id"]

    status = demo.system_status()
    investigation_triggered = False
    note = "No A2A agent services are reachable -- start them per docs/DEMO_RUNBOOK.md to run a real investigation."
    if status["agents_reachable_count"] > 0:
        investigation_triggered = demo.spawn_investigation(incident_id, body.description)
        note = (
            "Real orchestrator investigation launched against this incident."
            if investigation_triggered
            else "Orchestrator venv (.venv-orchestrator/) not found -- fault injected and incident created, but the investigation could not be launched."
        )

    return {
        "incident_id": incident_id,
        "fault_type": body.fault_type,
        "investigation_triggered": investigation_triggered,
        "note": note,
    }


class IncidentCreate(BaseModel):
    description: str


class EventCreate(BaseModel):
    event_type: str
    source: str
    target: str | None = None
    status: str | None = None
    payload: dict[str, Any] | None = None


class ApprovalDecision(BaseModel):
    """POST /incidents/{id}/approve body -- a human recording a real decision
    on a proposed recovery plan (root CLAUDE.md section 20). Persistence only:
    this endpoint does not decide anything, it records what a human already
    decided outside this process (via the dashboard or a direct call)."""

    decision: str  # "APPROVED" | "REJECTED"
    approved_by: str


class IncidentStateUpdate(BaseModel):
    """Partial incident-state merge (root CLAUDE.md section 15 fields). Accepts
    any subset of known fields plus forward-compatible extras -- validation of
    field *meaning* is the orchestrator's job, not this persistence layer's
    (backend/CLAUDE.md "no business logic here")."""

    model_config = ConfigDict(extra="allow")


@app.post("/incidents")
def create_incident(body: IncidentCreate) -> dict:
    return incident_store.create_incident(body.description)


@app.get("/incidents/{incident_id}")
def get_incident(incident_id: str) -> dict:
    incident = incident_store.get_incident(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="incident not found")
    return incident


class BoardEntryCreate(BaseModel):
    type: str
    author: str
    content: dict[str, Any]
    trace_id: str | None = None


@app.post("/incidents/{incident_id}/blackboard")
def post_board_entry(incident_id: str, body: BoardEntryCreate) -> dict:
    """Blackboard write (see incident_store.append_board_entry). Only the six known entry types are accepted
    and an author is required, so the board stays a typed, attributable record."""
    if body.type not in incident_store.BOARD_ENTRY_TYPES:
        raise HTTPException(status_code=422, detail=f"unknown blackboard entry type {body.type!r}")
    try:
        entry = incident_store.append_board_entry(incident_id, body.type, body.author, body.content, body.trace_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if entry is None:
        raise HTTPException(status_code=404, detail="incident not found")
    incident_store.append_event(
        incident_id, "BOARD_ENTRY", body.author, None, None,
        {"entry_id": entry["entry_id"], "type": body.type, "trace_id": body.trace_id},
    )
    return entry


@app.get("/incidents/{incident_id}/blackboard")
def read_board(incident_id: str, type: str | None = None) -> dict:
    entries = incident_store.get_board(incident_id, type)
    if entries is None:
        raise HTTPException(status_code=404, detail="incident not found")
    return {"entries": entries}


@app.get("/incidents/{incident_id}/report")
def get_incident_report(incident_id: str, format: str = "json"):
    """The final structured report the orchestrator stored on the incident (nexus_models.IncidentReport).
    `?format=md` returns the Markdown rendering as a download; `?format=json` (default) the structured fields."""
    if format not in ("json", "md"):
        raise HTTPException(status_code=422, detail="format must be 'json' or 'md'")
    incident = incident_store.get_incident(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="incident not found")
    report = incident.get("report")
    if not report:
        raise HTTPException(status_code=404, detail="report not ready yet (it is written when the investigation finishes)")
    if format == "md":
        return PlainTextResponse(
            report.get("markdown", ""),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{incident_id}-report.md"'},
        )
    return {k: v for k, v in report.items() if k != "markdown"}


@app.post("/incidents/{incident_id}/state")
def update_incident_state(incident_id: str, body: IncidentStateUpdate) -> dict:
    incident = incident_store.update_incident(incident_id, body.model_dump(exclude_unset=True))
    if incident is None:
        raise HTTPException(status_code=404, detail="incident not found")
    return incident


def _require_approver_token(supplied: str | None) -> None:
    """Optional gate on the human-approval endpoint. With NEXUS_APPROVER_TOKEN unset (the
    default) nothing changes. When set, only a caller that presents the same token in
    `X-Approver-Token` may approve/reject -- so other processes on the machine cannot
    approve a recovery by calling the backend directly. The dashboard's dev proxy adds it
    server-side (dashboard/vite.config.ts); it is never put in the browser bundle."""
    expected = os.environ.get("NEXUS_APPROVER_TOKEN")
    if expected and not hmac.compare_digest(supplied or "", expected):
        raise HTTPException(status_code=403, detail="approval requires a valid X-Approver-Token")


@app.post("/incidents/{incident_id}/approve")
def approve_recovery_plan(
    incident_id: str, body: ApprovalDecision, x_approver_token: str | None = Header(default=None)
) -> dict:
    """Human approval gate for a proposed recovery plan (root CLAUDE.md
    section 20). `orchestrator/recovery.py` never calls this itself -- it
    only polls for the result. This must be called out-of-band, by a human
    (via the dashboard once built, or directly) while an investigation's
    recovery flow is waiting on `approval_state.decision == "PENDING"`."""
    _require_approver_token(x_approver_token)
    if body.decision not in ("APPROVED", "REJECTED"):
        raise HTTPException(status_code=400, detail="decision must be 'APPROVED' or 'REJECTED'")
    incident = incident_store.get_incident(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="incident not found")

    # Late approval: the window closed (EXPIRED) and the original orchestrator process has
    # exited, so approving would otherwise do nothing. Resume the SAVED plan instead.
    late = (incident.get("approval_state") or {}).get("decision") == "EXPIRED" and body.decision == "APPROVED"
    if late and not demo.can_resume_recovery():
        raise HTTPException(status_code=503, detail="cannot resume: orchestrator environment (.venv-orchestrator) not found")

    approval_state = {
        "decision": body.decision,
        "approved_by": body.approved_by,
        "decided_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if late:
        approval_state["late"] = True
    incident = incident_store.update_incident(incident_id, {"approval_state": approval_state})
    incident_store.append_event(
        incident_id,
        "HUMAN_APPROVAL_GRANTED" if body.decision == "APPROVED" else "HUMAN_APPROVAL_REJECTED",
        source="human",
        target="orchestrator",
        status=body.decision,
        payload={"approved_by": body.approved_by},
    )
    if late:
        demo.spawn_resume_recovery(incident_id)
    return incident


@app.post("/incidents/{incident_id}/events")
def create_event(incident_id: str, body: EventCreate) -> dict:
    event = incident_store.append_event(
        incident_id, body.event_type, body.source, body.target, body.status, body.payload
    )
    if event is None:
        raise HTTPException(status_code=404, detail="incident not found")
    return event


@app.get("/incidents/{incident_id}/events")
def get_events(incident_id: str) -> dict:
    events = incident_store.list_events(incident_id)
    if events is None:
        raise HTTPException(status_code=404, detail="incident not found")
    return {"events": events}
