import { useCallback, useEffect, useState } from "react";
import type { IncidentState, NexusEvent } from "../api/types";

const STEP_MS = 450;

/** Reveals a recorded run's real events one at a time. `count` is how many are visible. */
export function useReplay(total: number) {
  const [count, setCount] = useState(0);
  const [playing, setPlaying] = useState(true);

  useEffect(() => {
    if (!playing || count >= total) return;
    const t = window.setTimeout(() => setCount((c) => Math.min(c + 1, total)), STEP_MS);
    return () => window.clearTimeout(t);
  }, [playing, count, total]);

  useEffect(() => {
    if (count >= total && total > 0) setPlaying(false);
  }, [count, total]);

  const restart = useCallback(() => {
    setCount(0);
    setPlaying(true);
  }, []);
  const showAll = useCallback(() => {
    setCount(total);
    setPlaying(false);
  }, [total]);
  const togglePlay = useCallback(() => setPlaying((p) => !p), []);

  return { count, playing, done: count >= total, restart, showAll, togglePlay };
}

/**
 * The recorded incident as it stood once only `seen` events had happened. Everything here is
 * derived from the real events: hypotheses appear when the real HYPOTHESIS_CREATED event is
 * reached, critic verdicts as each real CRITIC_CHALLENGE is reached, the decision when the real
 * DIAGNOSIS_REACHED / ABSTENTION event is reached. Nothing is invented.
 */
export function incidentAt(incident: IncidentState, seen: NexusEvent[]): IncidentState {
  const has = (...types: string[]) => seen.some((e) => types.includes(e.event_type));
  const decided = has("DIAGNOSIS_REACHED", "ABSTENTION");
  const critiquesSeen = seen.filter((e) => e.event_type === "CRITIC_CHALLENGE").length;
  return {
    ...incident,
    hypotheses: has("HYPOTHESIS_CREATED") ? incident.hypotheses : [],
    critic_results: incident.critic_results.slice(0, critiquesSeen),
    decision: decided ? incident.decision : null,
    status: decided ? incident.status : "INVESTIGATING",
    // Token totals are only known once the run has finished.
    token_usage: decided ? incident.token_usage : ({} as IncidentState["token_usage"]),
  };
}
