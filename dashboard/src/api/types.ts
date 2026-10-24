// Mirrors docs/API_CONTRACT.md and docs/EVENT_SCHEMA.md exactly.
// This file must never drift from the real backend contract — if a shape
// changes here, it changed in the backend/agents first.

export type IncidentStatus = "INVESTIGATING" | "DIAGNOSED" | "ABSTAINED" | "RESOLVED";

export interface EvidenceItem {
  evidence_id: string;
  tool: string;
  arguments: Record<string, unknown>;
  result: unknown;
  timestamp: string;
}

export interface Finding {
  finding_id: string;
  agent: string;
  observation: string;
  source: string;
  window: { start: string; end: string };
  evidence: EvidenceItem[];
  interpretation: string;
  confidence: number;
  limitations: string;
}

export type HypothesisStatus =
  | "PROPOSED"
  | "UNDER_REVIEW"
  | "CHALLENGED"
  | "NEEDS_EVIDENCE"
  | "SUPPORTED"
  | "REJECTED"
  | "ABSTAINED";

export interface Hypothesis {
  hypothesis_id: string;
  statement: string;
  supporting_evidence_ids: string[];
  contradicting_evidence_ids: string[];
  confidence: number;
  missing_evidence: string[];
  requested_next_investigation: string;
  status: HypothesisStatus;
  revision: number;
  created_at: string;
  dropped_invented_evidence_ids: number;
}

export type CritiqueVerdict =
  | "SUPPORTED"
  | "CONTRADICTED"
  | "INSUFFICIENT_EVIDENCE"
  | "REQUEST_MORE_EVIDENCE"
  | "ABSTAIN";

// agents/critic/agent.py's build_critique() always produces the full shape,
// but orchestrator/investigation.py falls back to a minimal object (verdict +
// rationale only) when the Critic's real A2A response is unparseable — a real
// path hit under Groq rate-limit pressure, not a hypothetical. Every field
// beyond hypothesis_id/verdict/rationale must be treated as possibly absent.
export interface Critique {
  critique_id: string | null;
  hypothesis_id: string;
  verdict: CritiqueVerdict;
  contradictions?: string[];
  unsupported_assumptions?: string[];
  alternative_explanations?: string[];
  requested_evidence?: string[];
  rationale: string;
  evidence_pool_size?: number;
  timestamp?: string;
}

export interface Decision {
  outcome: "DIAGNOSED" | "ABSTAINED";
  reason: string;
  loops_used: number;
  max_loops: number;
}

export interface TimelineEntry {
  event_id: string;
  timestamp: string;
  event_type: string;
  source: string;
  target?: string;
}

export interface AgentMessageRef {
  task_id: string;
  context_id: string;
}

// Phase 8 (docs/API_CONTRACT.md "Recovery flow") — filled in for real by
// orchestrator/recovery.py once an incident reaches DIAGNOSED. All optional
// beyond the fields recovery.py always sets, since a REJECTED-by-safety-
// validation plan never gets a status/rollback_plan filled by an agent that
// only ever proposes, never guarantees, a complete shape.
export interface RecoveryAction {
  action: string;
  params: Record<string, unknown>;
  rationale?: string;
}

export interface RecoveryPlan {
  plan_id: string;
  hypothesis_id: string;
  actions: RecoveryAction[];
  risk_level: "LOW" | "MEDIUM" | "HIGH";
  blast_radius?: string;
  rollback_plan?: string;
  status?: string;
  dropped_invalid_actions?: number;
  created_at?: string;
}

export type ApprovalDecision = "PENDING" | "APPROVED" | "REJECTED" | "EXPIRED" | "NOT_REQUESTED";

export interface ApprovalState {
  decision: ApprovalDecision;
  approved_by?: string;
  decided_at?: string;
  requested_at?: string;
  reason?: string;
}

export interface ActionHistoryEntry {
  action: string;
  params?: Record<string, unknown>;
  status: "EXECUTED" | "FAILED" | "SKIPPED_KILL_SWITCH";
  detail?: string;
  timestamp: string;
}

// orchestrator/budget.py's IncidentBudget.snapshot(): model usage as reported by
// the agents themselves (not provider quota). Empty `{}` until the first agent
// answers, and for incidents created before usage tracking existed.
export interface UsageCounts {
  llm_calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  tasks?: number;
}

export interface TokenUsage {
  measured_by?: string;
  total?: UsageCounts;
  by_agent?: Record<string, UsageCounts>;
  unmeasured_tasks?: number;
  limits?: { max_llm_calls: number; max_total_tokens: number; max_tokens_per_agent: number };
  budget_exceeded?: string | null;
}

export interface IncidentState {
  incident_id: string;
  description: string;
  status: IncidentStatus;
  created_at: string;
  updated_at: string;
  timeline: TimelineEntry[];
  evidence: Record<string, unknown>;
  agent_findings: Record<string, Finding>;
  agent_messages: Record<string, AgentMessageRef>;
  hypotheses: Hypothesis[];
  critic_results: Critique[];
  experiments: unknown[];
  recovery_plan: RecoveryPlan | null;
  approval_state: ApprovalState | null;
  action_history: ActionHistoryEntry[];
  token_usage: TokenUsage;
  decision: Decision | null;
}

// docs/EVENT_SCHEMA.md envelope. Kept as the exact set of event_type strings
// orchestrator/investigation.py and orchestrator/recovery.py actually call
// event_bridge.emit_event() with (verified against source, not the earlier
// EVENT_SCHEMA.md draft names this file previously mirrored — see
// docs/PROJECT_STATE.md Phase 8 "renamed to match root CLAUDE.md exactly").
export type NexusEventType =
  | "INCIDENT_CREATED"
  | "INPUT_REJECTED"
  | "HANDOFF"
  | "AGENT_MONITOR"
  | "BOARD_ENTRY"
  | "EVIDENCE_PARSE_WARNING"
  | "INCIDENT_STATUS_CHANGED"
  | "AGENT_STARTED"
  | "AGENT_COMPLETED"
  | "AGENTS_SELECTED"
  | "A2A_MESSAGE_SENT"
  | "MCP_TOOL_CALL"
  | "MCP_TOOL_RESULT"
  | "EVIDENCE_FOUND"
  | "HYPOTHESIS_CREATED"
  | "HYPOTHESIS_UPDATED"
  | "CRITIC_CHALLENGE"
  | "EVIDENCE_REQUESTED"
  | "RE_EVALUATION_STARTED"
  | "DIAGNOSIS_REACHED"
  | "ABSTENTION"
  | "RECOVERY_PROPOSED"
  | "SAFETY_VALIDATION"
  | "HUMAN_APPROVAL_REQUESTED"
  | "HUMAN_APPROVAL_GRANTED"
  | "HUMAN_APPROVAL_REJECTED"
  | "RECOVERY_EXECUTED"
  | "RECOVERY_VERIFIED"
  | "INCIDENT_RESOLVED";

export interface NexusEvent {
  event_id: string;
  incident_id: string;
  timestamp: string;
  event_type: NexusEventType;
  source: string;
  target?: string;
  status?: string;
  payload?: Record<string, unknown>;
}

export interface EventsResponse {
  events: NexusEvent[];
}

// The 4 independent diagnostic agents this dashboard renders operational
// status for (agents/common/ports.py's diagnostic-agent set).
export const DIAGNOSTIC_AGENTS = [
  "metrics_agent",
  "logs_traces_agent",
  "change_analysis_agent",
  "database_agent",
] as const;

export type DiagnosticAgentName = (typeof DIAGNOSTIC_AGENTS)[number];

export type AgentRuntimeStatus = "IDLE" | "RUNNING" | "WAITING" | "COMPLETED" | "FAILED";
