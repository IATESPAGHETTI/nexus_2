"""Builds NEXUS Agent Finding objects (docs/API_CONTRACT.md "Agent finding schema").

The split between `observation` and `interpretation` is enforced structurally, not
just by prompt instruction: `observation` is assembled here in Python, purely from
the raw MCP tool call results the agent actually made — never from the model's own
words. `interpretation` is the model's text, verbatim (minus the trailing
CONFIDENCE marker). This makes it structurally impossible for a guess to get
silently recorded as a fact (root CLAUDE.md 2.1 / agents/CLAUDE.md contract).
"""

from __future__ import annotations

import re
import time
import uuid
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from nexus_models import Finding, validated  # noqa: E402

# Tolerates markdown emphasis around the marker (observed in real model output,
# e.g. "**CONFIDENCE:** 0.68") in addition to the plain "CONFIDENCE: 0.68" form.
_CONFIDENCE_RE = re.compile(
    r"\**\s*CONFIDENCE\s*:?\**\s*([01](?:\.\d+)?)\s*\**\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def new_evidence_id() -> str:
    return f"ev-{uuid.uuid4().hex[:8]}"


def new_finding_id() -> str:
    return f"find-{uuid.uuid4().hex[:8]}"


def make_evidence_item(tool: str, arguments: dict, result: Any) -> dict:
    return {
        "evidence_id": new_evidence_id(),
        "tool": tool,
        "arguments": arguments,
        "result": result,
        "timestamp": now_iso(),
    }


def _summarize_evidence(evidence: list[dict]) -> str:
    if not evidence:
        return "No MCP tool call succeeded; no evidence was gathered."
    parts = []
    for item in evidence:
        result = item["result"]
        ok = result.get("ok") if isinstance(result, dict) else None
        field_names = (
            [k for k in result.keys() if k != "ok"] if isinstance(result, dict) else []
        )
        parts.append(
            f"{item['tool']}({item['arguments']}) -> ok={ok}, fields={field_names}"
        )
    return "; ".join(parts)


def _split_confidence(model_text: str) -> tuple[str, float | None]:
    match = _CONFIDENCE_RE.search(model_text.strip())
    if not match:
        return model_text.strip(), None
    confidence = float(match.group(1))
    interpretation = _CONFIDENCE_RE.sub("", model_text).strip()
    return interpretation, confidence


def build_finding(
    agent_name: str,
    evidence: list[dict],
    model_text: str,
    window_start: str | None = None,
) -> dict:
    interpretation, parsed_confidence = _split_confidence(model_text)
    limitations = []
    if parsed_confidence is None:
        confidence = 0.3
        limitations.append(
            "model did not report a parseable CONFIDENCE value; a conservative "
            "default (0.3) was applied instead of trusting an unstated confidence"
        )
    else:
        confidence = max(0.0, min(1.0, parsed_confidence))
    if not evidence:
        limitations.append("no MCP tool evidence was successfully gathered")
    if any(isinstance(e["result"], dict) and e["result"].get("ok") is False for e in evidence):
        limitations.append("at least one MCP tool call returned ok=False")

    finding = {
        "finding_id": new_finding_id(),
        "agent": agent_name,
        "observation": _summarize_evidence(evidence),
        "source": agent_name,
        "window": {"start": window_start or now_iso(), "end": now_iso()},
        "evidence": evidence,
        "interpretation": interpretation or "(model returned no interpretation text)",
        "confidence": confidence,
        "limitations": "; ".join(limitations) if limitations else "none noted",
    }
    return validated(Finding, finding)  # Pydantic contract check (nexus_models.py)
