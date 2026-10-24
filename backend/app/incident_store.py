"""Durable incident state + event store (Phase 6; SQLite-backed since the
persistence pass).

This IS the NEXUS event bus contract from `docs/EVENT_SCHEMA.md` and the
incident-state field set from root CLAUDE.md section 15 ("Incident state must
be explicit and persistent"). Incidents and events are kept in a SQLite file so
they survive a backend restart. No business logic lives here (backend/CLAUDE.md
"no business logic here beyond persistence/serving"): callers (orchestrator/)
decide what to persist and when; this module only stores and returns it
exactly as given.

Where the data lives -- `NEXUS_DB_PATH`:
  - unset            -> `backend/.data/nexus.db` (gitignored)
  - a file path      -> that file (docker-compose points it at a named volume)
  - `:memory:`       -> in-process only, used by the test suite
The public functions are unchanged from the earlier in-memory version, so
`app/main.py` did not need to change.

An incident is stored as one JSON document (same shape as before); events are
rows ordered by an auto-increment sequence, which also provides the global
`evt-N` ids the dashboard sorts by.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from threading import Lock
from typing import Any

_DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / ".data" / "nexus.db"

_lock = Lock()
_conn: sqlite3.Connection | None = None


def _db_path() -> str:
    return os.environ.get("NEXUS_DB_PATH") or str(_DEFAULT_DB_PATH)


def _connection() -> sqlite3.Connection:
    """Lazily opens the database; callers must already hold `_lock`."""
    global _conn
    if _conn is None:
        path = _db_path()
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS incidents (incident_id TEXT PRIMARY KEY, data TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS events ("
            "seq INTEGER PRIMARY KEY AUTOINCREMENT, incident_id TEXT NOT NULL, data TEXT NOT NULL)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_incident ON events (incident_id, seq)")
        conn.commit()
        _conn = conn
    return _conn


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _load(conn: sqlite3.Connection, incident_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT data FROM incidents WHERE incident_id = ?", (incident_id,)).fetchone()
    return json.loads(row[0]) if row else None


def _save(conn: sqlite3.Connection, incident: dict[str, Any]) -> None:
    conn.execute(
        "UPDATE incidents SET data = ? WHERE incident_id = ?",
        (json.dumps(incident), incident["incident_id"]),
    )


def create_incident(description: str) -> dict:
    incident_id = f"INC-{uuid.uuid4().hex[:8]}"
    incident: dict[str, Any] = {
        "incident_id": incident_id,
        "description": description,
        "status": "INVESTIGATING",
        "created_at": _now(),
        "updated_at": _now(),
        "timeline": [],
        "evidence": {},
        "agent_findings": {},
        "agent_messages": {},
        "hypotheses": [],
        "critic_results": [],
        "experiments": [],
        "recovery_plan": None,
        "approval_state": None,
        "action_history": [],
        "token_usage": {},
        "decision": None,
    }
    with _lock:
        conn = _connection()
        conn.execute(
            "INSERT INTO incidents (incident_id, data) VALUES (?, ?)", (incident_id, json.dumps(incident))
        )
        conn.commit()
    return incident


def get_incident(incident_id: str) -> dict | None:
    with _lock:
        return _load(_connection(), incident_id)


def update_incident(incident_id: str, fields: dict) -> dict | None:
    with _lock:
        conn = _connection()
        incident = _load(conn, incident_id)
        if incident is None:
            return None
        incident.update(fields)
        incident["updated_at"] = _now()
        _save(conn, incident)
        conn.commit()
        return incident


BOARD_ENTRY_TYPES = ("description", "request", "finding", "hypotheses", "review_request", "critique")
MAX_BOARD_ENTRIES = 200


def append_board_entry(incident_id: str, entry_type: str, author: str, content: dict, trace_id: str | None = None) -> dict | None:
    """Shared blackboard (course requirement 1): an append-only list on the incident, written by the
    controller AND by the agents themselves. Atomic under the store lock; ids are bb-1, bb-2, ..."""
    with _lock:
        conn = _connection()
        incident = _load(conn, incident_id)
        if incident is None:
            return None
        board = incident.setdefault("blackboard", [])
        if len(board) >= MAX_BOARD_ENTRIES:
            raise ValueError("blackboard is full")
        entry = {
            "entry_id": f"bb-{len(board) + 1}",
            "type": entry_type,
            "author": author,
            "timestamp": _now(),
            "trace_id": trace_id,
            "content": content,
        }
        board.append(entry)
        incident["updated_at"] = _now()
        _save(conn, incident)
        conn.commit()
        return entry


def get_board(incident_id: str, entry_type: str | None = None) -> list[dict] | None:
    with _lock:
        incident = _load(_connection(), incident_id)
        if incident is None:
            return None
        board = incident.get("blackboard", [])
        return [e for e in board if entry_type is None or e["type"] == entry_type]


def append_event(
    incident_id: str,
    event_type: str,
    source: str,
    target: str | None,
    status: str | None,
    payload: dict | None,
) -> dict | None:
    with _lock:
        conn = _connection()
        incident = _load(conn, incident_id)
        if incident is None:
            return None
        # The row's auto-increment sequence is the event's global ordering and
        # its `evt-N` id, so reserve the row first and fill in its data.
        cursor = conn.execute("INSERT INTO events (incident_id, data) VALUES (?, '')", (incident_id,))
        event = {
            "event_id": f"evt-{cursor.lastrowid}",
            "incident_id": incident_id,
            "timestamp": _now(),
            "event_type": event_type,
            "source": source,
            "target": target,
            "status": status,
            "payload": payload or {},
        }
        conn.execute("UPDATE events SET data = ? WHERE seq = ?", (json.dumps(event), cursor.lastrowid))
        incident["timeline"].append(
            {
                "event_id": event["event_id"],
                "timestamp": event["timestamp"],
                "event_type": event_type,
                "source": source,
                "target": target,
            }
        )
        incident["updated_at"] = event["timestamp"]
        _save(conn, incident)
        conn.commit()
        return event


def list_events(incident_id: str) -> list[dict] | None:
    with _lock:
        conn = _connection()
        if _load(conn, incident_id) is None:
            return None
        rows = conn.execute("SELECT data FROM events WHERE incident_id = ? ORDER BY seq", (incident_id,)).fetchall()
        return [json.loads(row[0]) for row in rows]


def close() -> None:
    """Closes the connection so the next call reopens `NEXUS_DB_PATH`. Used by
    tests to simulate a backend restart; harmless otherwise."""
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None


def clear() -> None:
    """Test-only reset. Not exposed over HTTP, and refuses to run against a
    file-backed database so a stray test can never wipe real incidents."""
    if _db_path() != ":memory:":
        raise RuntimeError("incident_store.clear() is test-only and only runs with NEXUS_DB_PATH=:memory:")
    with _lock:
        conn = _connection()
        conn.execute("DELETE FROM events")
        conn.execute("DELETE FROM incidents")
        conn.commit()
