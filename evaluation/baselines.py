"""Single-agent baseline (docs/EVALUATION.md comparison arm 1).

ONE Groq/GPT-OSS-120B completion call, given ONE flat evidence snapshot
(evaluation/production_reader.py) -- no tools, no multi-agent coordination,
no critic, no re-evaluation loop. This is deliberately the simplest thing
that could plausibly diagnose an incident, to give the full NEXUS system
(orchestrator/investigation.py) and its critic-ablation variant something
real to be compared against (root CLAUDE.md section 21).

Uses `litellm.completion` directly rather than ADK's `LiteLlm`/`Agent`
machinery -- there is no agent loop here, just one request/response, so the
full ADK dependency isn't needed for this one call. Reuses the Groq/GPT-OSS
gotcha fix from orchestrator/spike/SPIKE_RESULT.md defensively
(`litellm.drop_params = True`) even though the known failure mode is
multi-turn-tool-calling-specific and this is a single turn with no tools.
"""

from __future__ import annotations

import json
import sys
import re
import time
from pathlib import Path

import litellm
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
load_dotenv(REPO_ROOT / ".env")

from runtime_config import litellm_model_name  # noqa: E402
litellm.drop_params = True

VALID_ROOT_CAUSES = (
    "bad_deployment",
    "db_slowdown",
    "config_error",
    "dependency_failure",
    "resource_exhaustion",
    "unknown",
)

_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)


def _extract_json(text: str) -> dict | None:
    if not text:
        return None
    candidates = []
    fenced = _FENCED_JSON_RE.search(text)
    if fenced:
        candidates.append(fenced.group(1))
    stripped = text.strip()
    candidates.append(stripped)
    first, last = stripped.find("{"), stripped.rfind("}")
    if first != -1 and last > first:
        candidates.append(stripped[first : last + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, TypeError):
            continue
    return None


INSTRUCTION = (
    "You are a production on-call engineer. You will be given a JSON snapshot "
    "of real metrics, recent logs, recent deployment/change history, and DB "
    "diagnostics for one incident. Diagnose the single most likely root cause. "
    "Reply with ONLY a single JSON object (no prose, no markdown fences) with "
    "exactly these keys: \"root_cause\" (one of exactly: " + ", ".join(VALID_ROOT_CAUSES) + " "
    "-- use \"unknown\" if the evidence genuinely does not support a specific "
    "diagnosis), \"confidence\" (a number between 0 and 1), and \"rationale\" "
    "(a 1-2 sentence explanation citing the evidence)."
)


def build_result(raw_model_output, latency_seconds: float) -> dict:
    """Structural enforcement mirroring the rest of the system's
    build_finding/build_hypotheses/build_critique/build_recovery_plan
    pattern: an out-of-catalog root_cause is never trusted."""
    parsed = raw_model_output if isinstance(raw_model_output, dict) else {}
    root_cause = parsed.get("root_cause")
    if root_cause not in VALID_ROOT_CAUSES:
        root_cause = "unknown"
    try:
        confidence = max(0.0, min(1.0, float(parsed.get("confidence", 0.3))))
    except (TypeError, ValueError):
        confidence = 0.3
    return {
        "root_cause": root_cause,
        "confidence": confidence,
        "rationale": str(parsed.get("rationale") or "(no rationale provided)"),
        "latency_seconds": round(latency_seconds, 3),
        "arm": "single_agent_baseline",
    }


def single_agent_baseline(incident_description: str) -> dict:
    """Real evidence, real single Groq call, real timing. Never raises for a
    reachable-but-unparseable model reply -- falls back to root_cause=unknown,
    same fail-safe philosophy as every other build_* function in this system."""
    import production_reader

    start = time.perf_counter()
    snapshot = production_reader.snapshot()
    user_message = json.dumps({"incident_description": incident_description, "evidence_snapshot": snapshot})

    response = litellm.completion(
        model=litellm_model_name(),
        messages=[{"role": "system", "content": INSTRUCTION}, {"role": "user", "content": user_message}],
        num_retries=5,
    )
    latency = time.perf_counter() - start
    text = response.choices[0].message.content or ""
    result = build_result(_extract_json(text), latency)
    usage = getattr(response, "usage", None)
    total = getattr(usage, "total_tokens", None) if usage else None
    result["llm_calls"] = 1
    result["total_tokens"] = int(total) if total else None  # None = provider reported nothing
    return result
