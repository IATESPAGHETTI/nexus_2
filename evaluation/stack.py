"""Starts and stops the 7 agent services with a chosen environment, for the experiment matrix.

The dashboard's ON switch starts agents with the backend's own environment; an experiment needs to start them with
a SPECIFIC prompt variant / critic framework, so it manages the processes itself. Only the fixed allowlist of agent
scripts below is ever launched. Production (8001) and backend (8000) are NOT managed here: they must already be up.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "agents" / "common"))
from ports import A2A_PORTS  # noqa: E402

AGENT_SCRIPTS = {
    "metrics_agent": "agents/metrics/a2a_service.py",
    "logs_traces_agent": "agents/logs_traces/a2a_service.py",
    "change_analysis_agent": "agents/change_analysis/a2a_service.py",
    "database_agent": "agents/database/a2a_service.py",
    "evidence_agent": "agents/evidence/a2a_service.py",
    "root_cause_critic": "agents/critic/a2a_service.py",
    "recovery_agent": "agents/recovery/a2a_service.py",
}
CREWAI_SCRIPTS = {  # agent -> (env var that selects CrewAI, script)
    "root_cause_critic": ("NEXUS_CRITIC_FRAMEWORK", "crewai_critic/a2a_service.py"),
    "evidence_agent": ("NEXUS_EVIDENCE_FRAMEWORK", "crewai_critic/evidence_service.py"),
}


def _venv_python(name: str) -> Path:
    for base in (REPO_ROOT, *REPO_ROOT.parents):
        cand = base / name / "Scripts" / "python.exe"
        if cand.exists():
            return cand
    raise FileNotFoundError(f"{name} not found next to the repository")


def _port_open(port: int) -> bool:
    try:
        socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
        return True
    except OSError:
        return False


def service_up(name: str) -> bool:
    return _port_open(A2A_PORTS[name])


class AgentStack:
    def __init__(self) -> None:
        self.procs: dict[str, subprocess.Popen] = {}
        self.log_dir = REPO_ROOT / "evaluation" / "results" / "agent-logs"

    def start(self, extra_env: dict[str, str], ready_timeout: float = 180.0) -> None:
        """(Re)start all 7 services with `extra_env` added to the environment, and wait until they all answer."""
        self.stop()
        busy = [n for n in A2A_PORTS if n in AGENT_SCRIPTS and service_up(n)]
        if busy:
            raise RuntimeError(f"agent ports already in use by something this run did not start: {busy}")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", **extra_env}
        for name, script in AGENT_SCRIPTS.items():
            python = _venv_python(".venv-agents")
            choice = CREWAI_SCRIPTS.get(name)
            if choice and env.get(choice[0], "adk").lower() == "crewai":
                python, script = _venv_python(".venv-crewai"), choice[1]
            with open(self.log_dir / f"{name}.log", "w", encoding="utf-8") as log:
                self.procs[name] = subprocess.Popen(
                    [str(python), str(REPO_ROOT / script)], cwd=str(REPO_ROOT), env=env,
                    stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                )
        deadline = time.monotonic() + ready_timeout
        while time.monotonic() < deadline:
            dead = [n for n, p in self.procs.items() if p.poll() is not None]
            if dead:
                raise RuntimeError(f"agent service(s) exited at startup: {dead} (see {self.log_dir})")
            if all(service_up(n) for n in AGENT_SCRIPTS):
                return
            time.sleep(1.0)
        raise RuntimeError("agent services did not all come up in time")

    def stop(self) -> None:
        for proc in self.procs.values():
            if proc.poll() is None:
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        self.procs.clear()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and any(service_up(n) for n in AGENT_SCRIPTS):
            time.sleep(0.5)
