"""Bounded HTTP client that actually injects/clears a fault (Phase 9).

Mirrors mcp/production_client.py's/guardrails/production_client.py's pattern
(own module, own venv-independence, fixed timeout, typed error) -- calls only
`production/service.py`'s `/admin/fault/*` endpoints, never anything else.
Diagnostic/evidence/critic/recovery agents never import this module.
"""

from __future__ import annotations

import os

import httpx

PRODUCTION_BASE_URL = os.environ.get("PRODUCTION_BASE_URL", "http://127.0.0.1:8001")  # 127.0.0.1 not "localhost": on Windows "localhost" costs ~2 s per request (IPv6 tried first)
HTTP_TIMEOUT_SECONDS = 5.0


class ProductionUnavailableError(Exception):
    pass


def _post(path: str, json: dict | None = None) -> dict:
    url = f"{PRODUCTION_BASE_URL}{path}"
    try:
        response = httpx.post(url, json=json or {}, timeout=HTTP_TIMEOUT_SECONDS)
    except httpx.RequestError as exc:
        raise ProductionUnavailableError(f"could not reach {path}: {exc}") from exc
    if response.status_code >= 400:
        raise ProductionUnavailableError(f"{path} returned HTTP {response.status_code}: {response.text}")
    return response.json()


def _get(path: str) -> dict:
    url = f"{PRODUCTION_BASE_URL}{path}"
    try:
        response = httpx.get(url, timeout=HTTP_TIMEOUT_SECONDS)
    except httpx.RequestError as exc:
        raise ProductionUnavailableError(f"could not reach {path}: {exc}") from exc
    if response.status_code >= 400:
        raise ProductionUnavailableError(f"{path} returned HTTP {response.status_code}")
    return response.json()


def inject(scenario_id: str) -> dict:
    from scenarios import get_scenario  # local import: keeps this module import-order-safe

    scenario = get_scenario(scenario_id)
    return _post("/admin/fault/inject", json={"fault_type": scenario["fault_type"]})


def clear() -> dict:
    return _post("/admin/fault/clear")


def reset() -> dict:
    """Clears faults and all accumulated evidence (see production /admin/reset)."""
    return _post("/admin/reset")


def current_state() -> dict:
    return _get("/admin/state")
