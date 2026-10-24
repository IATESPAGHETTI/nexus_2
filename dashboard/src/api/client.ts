import type { EventsResponse, IncidentState, NexusEvent } from "./types";

// Pure client for backend/'s real HTTP API (docs/API_CONTRACT.md). No business
// logic lives here — this dashboard never fabricates activity. The ONE exception to "never
// replays" is api/recordings.ts: real, saved investigations that are always shown with a
// "Recorded run, not live" banner.
import { getRecording } from "./recordings";
const BASE = "/api";

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) {
    if (res.status === 404) {
      throw new NotFoundError(path);
    }
    throw new Error(`GET ${path} failed: ${res.status}`);
  }
  return (await res.json()) as T;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`POST ${path} failed: ${res.status} ${detail}`);
  }
  return (await res.json()) as T;
}

export class NotFoundError extends Error {
  constructor(path: string) {
    super(`Not found: ${path}`);
    this.name = "NotFoundError";
  }
}

export function getIncident(incidentId: string): Promise<IncidentState> {
  const recorded = getRecording(incidentId);
  if (recorded) return Promise.resolve(recorded.incident);
  return getJson<IncidentState>(`/incidents/${encodeURIComponent(incidentId)}`);
}

export function getIncidentEvents(incidentId: string): Promise<NexusEvent[]> {
  const recorded = getRecording(incidentId);
  if (recorded) return Promise.resolve(recorded.events);
  return getJson<EventsResponse>(
    `/incidents/${encodeURIComponent(incidentId)}/events`,
  ).then((r) => r.events);
}

export function approveRecoveryPlan(
  incidentId: string,
  decision: "APPROVED" | "REJECTED",
  approvedBy: string,
): Promise<IncidentState> {
  return postJson<IncidentState>(`/incidents/${encodeURIComponent(incidentId)}/approve`, {
    decision,
    approved_by: approvedBy,
  });
}

// Phase 10 "Inject Controlled Failure" — real system status + the one real
// trigger action (backend/app/demo.py). Never fabricated: every field here
// is either a live HTTP probe result or the real incident_id/fault_type the
// backend actually created/injected.
export interface DemoStatus {
  production_reachable: boolean;
  agents: Record<string, boolean>;
  agents_reachable_count: number;
  agents_total: number;
}

export function getDemoStatus(): Promise<DemoStatus> {
  return getJson<DemoStatus>("/demo/status");
}

export interface StartAgentsResult {
  started: string[];
  already_running: string[];
  failed: string[];
  note: string;
}

// The ON switch: asks the backend to launch the 7 agent services that are down.
export function startAgents(): Promise<StartAgentsResult> {
  return postJson<StartAgentsResult>("/demo/agents/start", {});
}

export interface StopAgentsResult {
  stopped: string[];
  still_running: string[];
  note: string;
}

// The OFF switch: stops the agent services the dashboard itself started.
export function stopAgents(): Promise<StopAgentsResult> {
  return postJson<StopAgentsResult>("/demo/agents/stop", {});
}

export interface InvestigateResult {
  incident_id: string;
  fault_type: string;
  investigation_triggered: boolean;
  note: string;
}

// Real customer-style traffic against the simulated production service
// (GET /orders, via the dev/preview proxy `/production`). NEXUS's stack has no
// background load, and db_slowdown only slows queries that actually run, so
// without requests there is nothing observable for the agents to find. These
// are genuine HTTP requests handled by production/service.py — the latency
// they record is real, not fabricated.
export async function sendCustomerRequests(count: number): Promise<{ ok: number; failed: number }> {
  const results = await Promise.allSettled(
    Array.from({ length: count }, (_, i) => fetch(i % 3 === 2 ? "/production/orders/1" : "/production/orders").then((r) => r.ok)),
  );
  const ok = results.filter((r) => r.status === "fulfilled" && r.value).length;
  return { ok, failed: count - ok };
}

export function resetShop(): Promise<unknown> {
  return postJson<unknown>("/demo/reset-shop", {});
}

export function injectControlledFailure(
  faultType: string,
  description: string,
): Promise<InvestigateResult> {
  return postJson<InvestigateResult>("/demo/investigate", { fault_type: faultType, description });
}
