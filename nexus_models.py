"""Pydantic models for the NEXUS data contracts (docs/API_CONTRACT.md).

One shared module at the repo root (like runtime_config.py). The agent builders
(`agents/common/finding.py`, `agents/evidence`, `agents/critic`, `agents/recovery`)
validate what they produce against these models, so a malformed object fails at
the agent boundary instead of travelling through A2A. The orchestrator builds
the final `IncidentReport` from the stored incident and can render it as JSON or
Markdown.

Models allow extra fields on purpose: the pipeline adds bookkeeping keys later
(`usage`, `revision`, `previous_confidence`, ...) and those must not break validation.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Verdict = Literal["SUPPORTED", "CONTRADICTED", "INSUFFICIENT_EVIDENCE", "REQUEST_MORE_EVIDENCE", "ABSTAIN"]
HypothesisStatus = Literal[
    "PROPOSED", "UNDER_REVIEW", "CHALLENGED", "NEEDS_EVIDENCE", "SUPPORTED", "REJECTED", "ABSTAINED"
]
RiskLevel = Literal["LOW", "MEDIUM", "HIGH"]


class _Base(BaseModel):
    model_config = ConfigDict(extra="allow")


class EvidenceItem(_Base):
    evidence_id: str
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: Any = None
    timestamp: str


class TimeWindow(_Base):
    start: str
    end: str


class Finding(_Base):
    finding_id: str
    agent: str
    observation: str
    source: str
    window: TimeWindow
    evidence: list[EvidenceItem] = Field(default_factory=list)
    interpretation: str
    confidence: float = Field(ge=0.0, le=1.0)
    limitations: str


class Hypothesis(_Base):
    hypothesis_id: str
    statement: str = Field(min_length=1)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    missing_evidence: list[str] = Field(default_factory=list)
    requested_next_investigation: Optional[str] = None
    status: HypothesisStatus = "PROPOSED"
    revision: int = 1
    created_at: str


class Critique(_Base):
    critique_id: str
    hypothesis_id: Optional[str] = None
    verdict: Verdict
    contradictions: list[str] = Field(default_factory=list)
    unsupported_assumptions: list[str] = Field(default_factory=list)
    alternative_explanations: list[str] = Field(default_factory=list)
    requested_evidence: list[str] = Field(default_factory=list)
    rationale: str
    evidence_pool_size: int = 0
    timestamp: str


class RecoveryAction(_Base):
    action: str
    params: dict[str, Any] = Field(default_factory=dict)
    rationale: str


class RecoveryPlan(_Base):
    plan_id: str
    hypothesis_id: Optional[str] = None
    actions: list[RecoveryAction] = Field(default_factory=list)
    risk_level: RiskLevel
    blast_radius: str
    rollback_plan: str
    status: str = "PROPOSED"
    dropped_invalid_actions: int = 0
    created_at: str


def validated(model: type[BaseModel], data: dict) -> dict:
    """Validate `data` against `model` and return it as a plain dict (extras kept).
    Raises pydantic.ValidationError when the contract is broken."""
    return model.model_validate(data).model_dump()


# --------------------------------------------------------------------- report


class EvidenceRef(_Base):
    evidence_id: str
    tool: str
    agent: str


class HypothesisRow(_Base):
    hypothesis_id: str
    status: str
    confidence: float = Field(ge=0.0, le=1.0)
    statement: str
    supporting: int = 0
    contradicting: int = 0


class AgentRow(_Base):
    agent: str
    model_calls: int = 0
    tool_calls: int = 0
    tokens: int = 0


def _md_cell(value: Any) -> str:
    """One Markdown table cell: no pipes or newlines, bounded length."""
    text = str(value if value is not None else "").replace("|", "/").replace("\n", " ").strip()
    return text if len(text) <= 160 else text[:157] + "..."


class IncidentReport(_Base):
    """Final structured output of an investigation (course requirement 3)."""

    incident_id: str
    description: str
    outcome: str  # DIAGNOSED | ABSTAINED | RESOLVED | ...
    reason: str = ""
    root_cause: Optional[str] = None
    root_cause_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    supporting_evidence: list[EvidenceRef] = Field(default_factory=list)
    critic_verdict: Optional[Verdict] = None
    critic_rationale: Optional[str] = None
    rejected_hypotheses: list[str] = Field(default_factory=list)
    recovery_actions: list[str] = Field(default_factory=list)
    approval: Optional[str] = None
    loops_used: int = 0
    run_config: dict[str, Any] = Field(default_factory=dict)
    total_tokens: Optional[int] = None
    llm_calls: Optional[int] = None
    trace_id: Optional[str] = None
    duration_seconds: Optional[float] = None
    hypotheses: list[HypothesisRow] = Field(default_factory=list)
    agents: list[AgentRow] = Field(default_factory=list)
    summary_rows: list[list[str]] = Field(default_factory=list)  # [label, value] pairs: the report's summary TABLE

    def to_markdown(self) -> str:
        lines = [
            f"# Incident report {self.incident_id}",
            "",
            f"**Outcome:** {self.outcome}  ",
            f"**Reason:** {self.reason or 'n/a'}  ",
            f"**Re-evaluation loops used:** {self.loops_used}",
            "",
        ]
        if self.summary_rows:
            lines += ["## Summary", "", "| Field | Value |", "|---|---|"]
            lines += [f"| {_md_cell(k)} | {_md_cell(v)} |" for k, v in self.summary_rows]
            lines.append("")
        if self.hypotheses:
            lines += ["## Hypotheses", "", "| ID | Status | Confidence | Evidence for / against | Statement |", "|---|---|---|---|---|"]
            lines += [
                f"| {h.hypothesis_id} | {h.status} | {h.confidence:.0%} | {h.supporting} / {h.contradicting} | {_md_cell(h.statement)} |"
                for h in self.hypotheses
            ]
            lines.append("")
        if self.agents:
            lines += ["## Agents", "", "| Agent | Model calls | Tool calls | Tokens |", "|---|---|---|---|"]
            lines += [f"| {a.agent} | {a.model_calls} | {a.tool_calls} | {a.tokens} |" for a in self.agents]
            lines.append("")
        lines += ["## Root cause", ""]
        if self.root_cause:
            conf = f" (confidence {self.root_cause_confidence:.0%})" if self.root_cause_confidence is not None else ""
            lines.append(f"{self.root_cause}{conf}")
        else:
            lines.append("No root cause was supported; the system abstained.")
        lines += ["", "## Critic", ""]
        if self.critic_verdict:
            lines.append(f"Verdict: **{self.critic_verdict}**. {self.critic_rationale or ''}".rstrip())
        else:
            lines.append("No critic review was recorded.")
        if self.rejected_hypotheses:
            lines += ["", "Rejected hypotheses:"] + [f"- {h}" for h in self.rejected_hypotheses]
        lines += ["", "## Supporting evidence", ""]
        if self.supporting_evidence:
            lines += ["| Evidence | Tool | Agent |", "|---|---|---|"]
            lines += [f"| {e.evidence_id} | {e.tool} | {e.agent} |" for e in self.supporting_evidence]
        else:
            lines.append("None cited.")
        lines += ["", "## Recovery", ""]
        if self.recovery_actions:
            lines += [f"- {a}" for a in self.recovery_actions]
            lines.append(f"\nApproval: {self.approval or 'n/a'}")
        else:
            lines.append("No recovery plan was proposed.")
        if self.run_config:
            lines += ["", "## Run configuration", ""] + [f"- {k}: {v}" for k, v in self.run_config.items()]
        lines += ["", "## Cost", ""]
        if self.total_tokens is None:
            lines.append("Token usage not recorded.")
        else:
            lines.append(f"{self.llm_calls} model calls, {self.total_tokens} tokens.")
        return "\n".join(lines) + "\n"


def build_incident_report(incident: dict) -> IncidentReport:
    """Build the final report from a stored incident dict (pure, no I/O)."""
    decision = incident.get("decision") or {}
    hypotheses = incident.get("hypotheses") or []
    critiques = incident.get("critic_results") or []
    plan = incident.get("recovery_plan") or {}
    usage = (incident.get("token_usage") or {}).get("total") or {}

    winner = next((h for h in hypotheses if h.get("status") == "SUPPORTED"), None)
    pool: dict[str, tuple[str, str]] = {}
    for agent, finding in (incident.get("agent_findings") or {}).items():
        for ev in (finding or {}).get("evidence", []) or []:
            pool[ev.get("evidence_id")] = (ev.get("tool", "?"), agent)
    refs = []
    if winner:
        for eid in winner.get("supporting_evidence_ids", []):
            tool, agent = pool.get(eid, ("unknown", "unknown"))
            refs.append(EvidenceRef(evidence_id=eid, tool=tool, agent=agent))
    last = critiques[-1] if critiques else {}
    findings = incident.get("agent_findings") or {}
    by_agent = (incident.get("token_usage") or {}).get("by_agent") or {}
    names = sorted(set(findings) | set(by_agent))
    agent_rows = [
        AgentRow(
            agent=n,
            model_calls=int((by_agent.get(n) or {}).get("llm_calls", 0) or 0),
            tool_calls=len((findings.get(n) or {}).get("evidence", []) or []),
            tokens=int((by_agent.get(n) or {}).get("total_tokens", 0) or 0),
        )
        for n in names
    ]
    hyp_rows = [
        HypothesisRow(
            hypothesis_id=str(h.get("hypothesis_id", "?")), status=str(h.get("status", "?")),
            confidence=float(h.get("confidence", 0.0) or 0.0), statement=str(h.get("statement", "")),
            supporting=len(h.get("supporting_evidence_ids") or []), contradicting=len(h.get("contradicting_evidence_ids") or []),
        )
        for h in hypotheses
    ]
    duration = None
    try:
        from datetime import datetime
        a = datetime.fromisoformat(str(incident.get("created_at")).replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(incident.get("updated_at")).replace("Z", "+00:00"))
        duration = round((b - a).total_seconds(), 1)
    except (TypeError, ValueError):
        pass
    cfg = incident.get("run_config") or {}
    outcome = incident.get("status") or decision.get("outcome", "UNKNOWN")
    summary = [
        ["Incident", incident.get("incident_id", "unknown")],
        ["Symptom", incident.get("description", "")],
        ["Outcome", outcome],
        ["Root cause", winner.get("statement") if winner else "none supported (abstained)"],
        ["Confidence", f"{winner.get('confidence', 0):.0%}" if winner else "n/a"],
        ["Critic verdict", last.get("verdict", "n/a")],
        ["Re-evaluation loops", f"{decision.get('loops_used', 0)} of {decision.get('max_loops', '?')}"],
        ["Agents used", ", ".join(names) or "none"],
        ["Evidence items", sum(len((f or {}).get("evidence", []) or []) for f in findings.values())],
        ["Model calls / tokens", f"{usage.get('llm_calls', 'n/a')} / {usage.get('total_tokens', 'n/a')}"],
        ["Duration", f"{duration} s" if duration is not None else "n/a"],
        ["Topology / prompt / critic", f"{cfg.get('topology', 'hub')} / {cfg.get('prompt_variant', 'default')} / {cfg.get('critic_framework', 'adk')}"],
        ["Recovery", ", ".join(a.get("action", "") for a in plan.get("actions", [])) or "none proposed"],
        ["Approval", (incident.get("approval_state") or {}).get("decision") or "n/a"],
    ]
    return IncidentReport(
        trace_id=incident.get("trace_id"), duration_seconds=duration, hypotheses=hyp_rows, agents=agent_rows,
        summary_rows=[[str(k), str(v)] for k, v in summary],
        incident_id=incident.get("incident_id", "unknown"),
        description=incident.get("description", ""),
        outcome=incident.get("status") or decision.get("outcome", "UNKNOWN"),
        reason=decision.get("reason", ""),
        root_cause=winner.get("statement") if winner else None,
        root_cause_confidence=winner.get("confidence") if winner else None,
        supporting_evidence=refs,
        critic_verdict=last.get("verdict"),
        critic_rationale=last.get("rationale"),
        rejected_hypotheses=[h.get("statement", "") for h in hypotheses if h.get("status") == "REJECTED"],
        recovery_actions=[a.get("action", "") for a in plan.get("actions", [])],
        approval=(incident.get("approval_state") or {}).get("decision"),
        loops_used=decision.get("loops_used", 0),
        run_config=incident.get("run_config") or {},
        total_tokens=usage.get("total_tokens"),
        llm_calls=usage.get("llm_calls"),
    )
