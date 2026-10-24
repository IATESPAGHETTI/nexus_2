"""Static simulated deployment/change history for the production service.

Consumed by the Change Analysis Agent (Phase 4) via the MCP change-history tool
(Phase 3). Phase 9 fault injection (`fault_injection/`, via `service.py`'s
`/admin/fault/inject`) and Phase 8 recovery (`guardrails/`, via
`/admin/recovery/rollback_deployment`) both append real entries here through
`append()` below -- a "bad deployment" fault and its rollback are genuinely
visible in the same change-history timeline the Change Analysis Agent already
queries, not a separately-faked signal.
"""

import time
from threading import Lock

_lock = Lock()

CHANGE_HISTORY = [
    {
        "change_id": "chg-001",
        "type": "deployment",
        "version": "1.0.0",
        "deployed_at": "2026-09-10T09:00:00Z",
        "description": "Initial release of nexus-production simulated service.",
        "author": "deepu",
    },
    {
        "change_id": "chg-002",
        "type": "config",
        "version": "1.0.1",
        "deployed_at": "2026-09-14T14:30:00Z",
        "description": "Increased DB connection pool size placeholder for future load.",
        "author": "deepu",
    },
    {
        "change_id": "chg-003",
        "type": "deployment",
        "version": "1.1.0",
        "deployed_at": "2026-09-18T10:00:00Z",
        "description": "Added observability endpoints (metrics/logs/traces/changes/db).",
        "author": "deepu",
    },
]


def reset() -> None:
    """Test/demo reset: drops every change appended after startup (fault injection,
    recovery actions), keeping the three seeded history entries."""
    with _lock:
        del CHANGE_HISTORY[3:]


def recent(limit: int = 20) -> list:
    # Tie-break equal-second `deployed_at` timestamps by insertion order
    # (index) so two changes injected within the same second -- a real
    # scenario once fault_injection/ and guardrails/ can both append within
    # one live investigation -- still come back newest-first, not reordered
    # by sort-stability quirks.
    with _lock:
        ordered = sorted(enumerate(CHANGE_HISTORY), key=lambda pair: (pair[1]["deployed_at"], pair[0]), reverse=True)
        return [entry for _, entry in ordered[:limit]]


def append(change_type: str, version: str, description: str, author: str = "nexus") -> dict:
    entry = {
        "change_id": f"chg-{len(CHANGE_HISTORY) + 1:03d}",
        "type": change_type,
        "version": version,
        "deployed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "description": description,
        "author": author,
    }
    with _lock:
        CHANGE_HISTORY.append(entry)
    return entry


def reset() -> None:
    """Back to the three seed entries (demo/test reset): drops changes added by earlier faults and recoveries."""
    with _lock:
        del CHANGE_HISTORY[3:]
