import type { IncidentState, NexusEvent } from "./types";

/**
 * Recorded runs: REAL investigations copied unchanged from the backend's store after a real
 * benchmark run (see dashboard/src/data/recordings/). They exist so the demo can be shown
 * without spending model credits. They are never presented as live: every page that shows
 * one carries a "Recorded run" banner (components/investigation/RecordedBanner.tsx).
 */
export interface RecordingHeader {
  scenario: string;
  ground_truth: string;
  arm: string;
  model: string;
  source_report: string;
  recorded_at: string | null;
  outcome: string;
  note: string;
}

export interface Recording {
  recording: RecordingHeader;
  incident: IncidentState;
  events: NexusEvent[];
}

const modules = import.meta.glob("../data/recordings/*.json", { eager: true, import: "default" }) as Record<
  string,
  Recording
>;

const byId = new Map<string, Recording>(Object.values(modules).map((r) => [r.incident.incident_id, r]));

export function getRecording(incidentId: string | undefined): Recording | undefined {
  return incidentId ? byId.get(incidentId) : undefined;
}

export function listRecordings(): Recording[] {
  return [...byId.values()].sort((a, b) => a.recording.scenario.localeCompare(b.recording.scenario));
}
