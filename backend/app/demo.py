"""Phase 10: the "Inject Controlled Failure" live-demo trigger.

This is the ONE piece of business logic backend/ is allowed to own (see
backend/CLAUDE.md "no business logic here" -- the exception is this module,
which exists purely to bridge a dashboard button click to the real,
already-implemented fault-injection and orchestration code; it invents no
new fault types, no new investigation logic, and no new recovery logic).

Real, not simulated:
- Fault injection is a real HTTP call to production/'s own
  `/admin/fault/inject` (fault_injection/injector.py's exact mechanism,
  reused here rather than reimplemented).
- The investigation is the real `orchestrator/investigation.py`
  `run_investigation()` coroutine, launched via `orchestrator/run_demo.py`
  as a detached subprocess in its own venv (`.venv-orchestrator/`) --
  backend/'s own venv deliberately does not have google-adk/litellm/a2a-sdk
  installed (root CLAUDE.md section 23, dependency isolation), so this is
  the smallest safe way to trigger the real orchestrator without collapsing
  that isolation.
- Agent/A2A reachability is a real HTTP check against each service's real
  `.well-known/agent-card.json` -- never a hardcoded "online".

If no A2A agent services are reachable (the common case unless an operator
started them per docs/DEMO_RUNBOOK.md), the fault is still injected for real
and the incident still created for real, but the orchestrator subprocess is
not spawned -- there would be nothing real for it to talk to, and spawning
it anyway would just produce a fast, uninformative connection-error failure.
The response says so explicitly rather than pretending an investigation
started.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

PRODUCTION_URL = os.environ.get("NEXUS_PRODUCTION_URL", "http://127.0.0.1:8001")
_TIMEOUT = 3.0

# Mirrors agents/common/ports.py's A2A_PORTS -- duplicated rather than
# imported so backend/'s venv never needs agents/'s dependencies.
AGENT_PORTS: dict[str, int] = {
    "metrics_agent": 8101,
    "logs_traces_agent": 8102,
    "change_analysis_agent": 8103,
    "database_agent": 8104,
    "evidence_agent": 8105,
    "root_cause_critic": 8106,
    "recovery_agent": 8107,
}

# The 5 real fault types production/state.py's FAULT_TYPES actually supports
# (mirrors fault_injection/scenarios.py's ground-truth catalog).
FAULT_TYPES = {
    "bad_deployment",
    "db_slowdown",
    "config_error",
    "dependency_failure",
    "resource_exhaustion",
}

REPO_ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR_PYTHON = REPO_ROOT / ".venv-orchestrator" / "Scripts" / "python.exe"
RUN_DEMO_SCRIPT = REPO_ROOT / "orchestrator" / "run_demo.py"
DEMO_LOG_DIR = REPO_ROOT / "backend" / ".demo_logs"


def check_production() -> bool:
    try:
        r = httpx.get(f"{PRODUCTION_URL}/health", timeout=_TIMEOUT)
        return r.status_code == 200
    except httpx.RequestError:
        return False


# Platform mode: when the orchestrator runs as its own service (containers / cloud), NEXUS_ORCHESTRATOR_URL is set,
# agents are addressed by NEXUS_AGENT_URL_<NAME>, and nothing here starts or stops processes.
ORCHESTRATOR_URL = os.environ.get("NEXUS_ORCHESTRATOR_URL", "").rstrip("/")
INTERNAL_TOKEN = os.environ.get("NEXUS_INTERNAL_TOKEN", "")


def _agent_url(name: str) -> str:
    return os.environ.get(f"NEXUS_AGENT_URL_{name.upper()}", f"http://127.0.0.1:{AGENT_PORTS[name]}").rstrip("/")


def _agent_up(name: str) -> bool:
    try:
        r = httpx.get(f"{_agent_url(name)}/.well-known/agent-card.json", timeout=_TIMEOUT)
        return r.status_code == 200
    except httpx.RequestError:
        return False


def _orchestrator_post(path: str, body: dict) -> bool:
    headers = {"X-Internal-Token": INTERNAL_TOKEN} if INTERNAL_TOKEN else {}
    try:
        return httpx.post(f"{ORCHESTRATOR_URL}{path}", json=body, headers=headers, timeout=_TIMEOUT).status_code == 202
    except httpx.RequestError:
        return False


def check_agents() -> dict[str, bool]:
    # Probed in parallel: sequential probes took ~3s per down agent (~14s total).
    with ThreadPoolExecutor(max_workers=len(AGENT_PORTS)) as pool:
        results = list(pool.map(_agent_up, AGENT_PORTS))
    return dict(zip(AGENT_PORTS, results))


def system_status() -> dict:
    agents = check_agents()
    return {
        "production_reachable": check_production(),
        "agents": agents,
        "agents_reachable_count": sum(agents.values()),
        "agents_total": len(agents),
    }


class ProductionUnavailableError(Exception):
    pass


def inject_fault(fault_type: str) -> dict:
    if fault_type not in FAULT_TYPES:
        raise ValueError(f"unknown fault_type: {fault_type!r} (expected one of {sorted(FAULT_TYPES)})")
    try:
        r = httpx.post(
            f"{PRODUCTION_URL}/admin/fault/inject", json={"fault_type": fault_type}, timeout=_TIMEOUT
        )
    except httpx.RequestError as exc:
        raise ProductionUnavailableError(f"could not reach production/: {exc}") from exc
    if r.status_code >= 400:
        raise ProductionUnavailableError(f"production/ rejected fault injection: HTTP {r.status_code} {r.text}")
    return r.json()


def reset_shop() -> dict:
    """Return the simulated shop to a clean state (no faults, no history of earlier incidents)."""
    try:
        r = httpx.post(f"{PRODUCTION_URL}/admin/reset", timeout=_TIMEOUT)
    except httpx.RequestError as exc:
        raise ProductionUnavailableError(f"could not reach production/: {exc}") from exc
    if r.status_code >= 400:
        raise ProductionUnavailableError(f"production/ rejected the reset: HTTP {r.status_code} {r.text}")
    return r.json()


def spawn_investigation(incident_id: str, description: str) -> bool:
    """Launches the real orchestrator subprocess against an already-created
    incident. Fire-and-forget: does not block on or wait for the real Groq/
    A2A calls it will make. Returns False (does not spawn) if the
    orchestrator venv/script isn't present, so a broken dev setup fails
    loudly in the response rather than as a silent background crash."""
    if ORCHESTRATOR_URL:
        return _orchestrator_post("/investigate", {"incident_id": incident_id, "description": description})
    if not ORCHESTRATOR_PYTHON.exists() or not RUN_DEMO_SCRIPT.exists():
        return False
    DEMO_LOG_DIR.mkdir(exist_ok=True)
    log_path = DEMO_LOG_DIR / f"{incident_id}.log"
    with open(log_path, "w", encoding="utf-8") as log_file:
        subprocess.Popen(
            [str(ORCHESTRATOR_PYTHON), str(RUN_DEMO_SCRIPT), "--incident-id", incident_id, description],
            cwd=str(REPO_ROOT),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
    return True


# Fixed allowlist: agent name -> its own A2A service script. Nothing here comes
# from a request, so the dashboard can start these 7 scripts and nothing else.
AGENT_SCRIPTS: dict[str, str] = {
    "metrics_agent": "agents/metrics/a2a_service.py",
    "logs_traces_agent": "agents/logs_traces/a2a_service.py",
    "change_analysis_agent": "agents/change_analysis/a2a_service.py",
    "database_agent": "agents/database/a2a_service.py",
    "evidence_agent": "agents/evidence/a2a_service.py",
    "root_cause_critic": "agents/critic/a2a_service.py",
    "recovery_agent": "agents/recovery/a2a_service.py",
}
AGENTS_PYTHON = REPO_ROOT / ".venv-agents" / "Scripts" / "python.exe"
CREWAI_PYTHON = REPO_ROOT / ".venv-crewai" / "Scripts" / "python.exe"
# Agents that have a CrewAI implementation: name -> (owner env var, script). Only the OWNER's environment can switch an
# agent to CrewAI (never request input); it is then served from the CrewAI venv at the same A2A address.
CREWAI_AGENTS = {
    "root_cause_critic": ("NEXUS_CRITIC_FRAMEWORK", "crewai_critic/a2a_service.py"),
    "evidence_agent": ("NEXUS_EVIDENCE_FRAMEWORK", "crewai_critic/evidence_service.py"),
}


def _launch_spec(name: str, script: str) -> tuple[Path, str]:
    """Which interpreter + script starts this agent."""
    choice = CREWAI_AGENTS.get(name)
    if choice and os.environ.get(choice[0], "adk").lower() == "crewai":
        return CREWAI_PYTHON, choice[1]
    return AGENTS_PYTHON, script
_BOOT_GRACE_SECONDS = 60.0
_spawned_at: dict[str, float] = {}
_spawned_procs: dict[str, subprocess.Popen] = {}


def start_agents() -> dict:
    """Starts every agent service that is not already reachable (the dashboard's
    ON switch). Idempotent: reachable agents are left alone, and one spawned in
    the last minute is not spawned twice while it is still booting. Starting an
    idle agent makes no model calls; cost only happens during an investigation."""
    if ORCHESTRATOR_URL:  # platform mode: the services run continuously; nothing to launch
        up = check_agents()
        return {"started": [], "already_running": [n for n, ok in up.items() if ok], "failed": [n for n, ok in up.items() if not ok],
                "note": "Agents are managed by the platform (always on); this switch only reports their status."}
    if not AGENTS_PYTHON.exists():
        return {"started": [], "already_running": [], "failed": list(AGENT_SCRIPTS),
                "note": f"agents interpreter not found at {AGENTS_PYTHON} (create .venv-agents first)"}
    up = check_agents()
    started, already, failed = [], [], []
    DEMO_LOG_DIR.mkdir(exist_ok=True)
    for name, script in AGENT_SCRIPTS.items():
        if up.get(name):
            already.append(name)
            continue
        previous = _spawned_procs.get(name)
        died = previous is not None and previous.poll() is not None  # exited since we launched it
        if not died and time.monotonic() - _spawned_at.get(name, -1e9) < _BOOT_GRACE_SECONDS:
            started.append(name)  # launched moments ago, still booting
            continue
        python, script = _launch_spec(name, script)
        if not python.exists():
            failed.append(name)
            continue
        try:
            with open(DEMO_LOG_DIR / f"agent-{name}.log", "w", encoding="utf-8") as log_file:
                proc = subprocess.Popen(
                    [str(python), str(REPO_ROOT / script)],
                    cwd=str(REPO_ROOT),
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                )
            _spawned_procs[name] = proc
            _spawned_at[name] = time.monotonic()
            started.append(name)
        except OSError:
            failed.append(name)
    return {"started": started, "already_running": already, "failed": failed,
            "note": "Agents take ~15-20 seconds to boot; watch the status count."}


def _kill_tree(proc: subprocess.Popen) -> None:
    """Stops the process AND its children (the venv launcher starts the real
    interpreter, which in turn starts the MCP server)."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, check=False)
    else:
        proc.kill()


def stop_agents() -> dict:
    """The dashboard's agent OFF switch: stops only the agent services THIS backend
    started. Agents someone started by hand are left alone and reported."""
    if ORCHESTRATOR_URL:
        return {'stopped': [], 'still_running': [n for n, ok in check_agents().items() if ok],
                'note': 'Agents are managed by the platform and keep running.'}
    stopped = []
    for name, proc in list(_spawned_procs.items()):
        if proc.poll() is None:
            _kill_tree(proc)
            stopped.append(name)
        _spawned_procs.pop(name, None)
        _spawned_at.pop(name, None)
    still_up = [name for name, up in check_agents().items() if up]
    return {
        "stopped": stopped,
        "still_running": still_up,
        "note": "Agents not started from the dashboard are left running." if still_up else "All agents are stopped.",
    }


def can_resume_recovery() -> bool:
    if ORCHESTRATOR_URL:
        return True
    return ORCHESTRATOR_PYTHON.exists() and RUN_DEMO_SCRIPT.exists()


def spawn_resume_recovery(incident_id: str) -> bool:
    """Late approval: runs `run_demo.py --resume-recovery <id>` as a detached orchestrator
    process (the original one exited when the approval window closed)."""
    if not can_resume_recovery():
        return False
    if ORCHESTRATOR_URL:
        return _orchestrator_post("/resume-recovery", {"incident_id": incident_id})
    DEMO_LOG_DIR.mkdir(exist_ok=True)
    with open(DEMO_LOG_DIR / f"{incident_id}-resume.log", "w", encoding="utf-8") as log_file:
        subprocess.Popen(
            [str(ORCHESTRATOR_PYTHON), str(RUN_DEMO_SCRIPT), "--resume-recovery", incident_id],
            cwd=str(REPO_ROOT),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
    return True
