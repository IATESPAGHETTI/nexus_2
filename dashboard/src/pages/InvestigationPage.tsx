import { useEffect } from "react";
import { Link, useParams } from "react-router-dom";
import { useIncidentEventsQuery, useIncidentQuery, deriveAgentStates } from "../api/useIncident";
import { TopBar } from "../components/investigation/TopBar";
import { InvestigationCanvas } from "../components/investigation/InvestigationCanvas";
import { A2AStreamPanel } from "../components/investigation/A2AStreamPanel";
import { MCPActivityPanel } from "../components/investigation/MCPActivityPanel";
import { HypothesisPanel } from "../components/investigation/HypothesisPanel";
import { CriticChallengePanel } from "../components/investigation/CriticChallengePanel";
import { ReEvaluationLoopIndicator } from "../components/investigation/ReEvaluationLoopIndicator";
import { DecisionPanel } from "../components/investigation/DecisionPanel";
import { UsagePanel } from "../components/investigation/UsagePanel";
import { RecoveryPanel } from "../components/investigation/RecoveryPanel";
import { IncidentHumanCard } from "../components/command_center/IncidentHumanCard";
import { buildCommandCenterModel } from "../lib/presentation";
import { a2aRows, buildEvidenceLookup, derivePhaseIndex, mcpRows } from "../lib/derive";
import { rememberIncident } from "../lib/recentIncidents";
import { getRecording } from "../api/recordings";
import { incidentAt, useReplay } from "../lib/replay";
import { RecordedBanner } from "../components/investigation/RecordedBanner";
import styles from "./InvestigationPage.module.css";

export function InvestigationPage() {
  const { incidentId } = useParams<{ incidentId: string }>();
  const incidentQuery = useIncidentQuery(incidentId);
  const eventsQuery = useIncidentEventsQuery(incidentId);
  const recording = getRecording(incidentId);
  const replay = useReplay(recording ? recording.events.length : 0);

  useEffect(() => {
    // Recorded runs are not this viewer's own incidents; keep them out of the recent list.
    if (incidentQuery.data && !recording) rememberIncident(incidentQuery.data);
  }, [incidentQuery.data]);

  if (incidentQuery.isLoading) {
    return (
      <div className={styles.state}>
        <div className={styles.loadingSpinner} />
        <div className={styles.stateTitle}>Loading incident telemetry…</div>
        <div className={styles.stateDetail}>Connecting to NEXUS orchestrator query bus.</div>
      </div>
    );
  }

  // Backend down or unknown incident id: say so plainly. No substitute data.
  if (incidentQuery.error) {
    return (
      <div className={styles.page}>
        <div className={styles.offlineNotice}>
          <div className={styles.noticeContent}>
            <div className={styles.noticeTitle}>BACKEND UNREACHABLE OR INCIDENT NOT FOUND</div>
            <div className={styles.noticeBody}>
              The FastAPI backend on <code>http://127.0.0.1:8000</code> is offline, or it has no incident{" "}
              <code>{incidentId}</code> (incident state is held in memory and is lost when the backend restarts).
              Nothing is shown in its place.
            </div>
          </div>
          <Link to="/" className={styles.backBtn}>
            &larr; Back to Mission Control
          </Link>
        </div>
      </div>
    );
  }

  const events = recording ? (eventsQuery.data ?? []).slice(0, replay.count) : (eventsQuery.data ?? []);
  const incident = recording ? incidentAt(incidentQuery.data!, events) : incidentQuery.data!;
  const agentStates = deriveAgentStates(incident, events);
  const evidenceLookup = buildEvidenceLookup(incident);
  const phaseIndex = derivePhaseIndex(events);
  const leadingHypothesis = incident.hypotheses[0] ?? null;
  const humanModel = buildCommandCenterModel(incident, events);

  return (
    <div className={styles.page}>
      {recording && (
        <RecordedBanner
          header={recording.recording}
          shown={replay.count}
          total={recording.events.length}
          playing={replay.playing}
          onTogglePlay={replay.togglePlay}
          onRestart={replay.restart}
          onShowAll={replay.showAll}
        />
      )}
      <TopBar
        incidentId={incident.incident_id}
        description={incident.description}
        phaseIndex={phaseIndex}
      />

      {/* Human-readable 7-question executive overview at the top */}
      <div className={styles.humanCardContainer}>
        <IncidentHumanCard model={humanModel} incident={incident} events={events} />
      </div>

      {/* Technical Deep Dive (Investigation Canvas, Panels, Rail) */}
      <div className={styles.technicalDivider}>
        <span className={styles.dividerLine} />
        <span className={styles.dividerText}>DEEP TELEMETRY &amp; MULTI-AGENT REASONING</span>
        <span className={styles.dividerLine} />
      </div>

      <div className={styles.body}>
        <div className={styles.main}>
          <InvestigationCanvas agentStates={agentStates} leadingHypothesis={leadingHypothesis} />

          <HypothesisPanel
            hypotheses={incident.hypotheses}
            critiques={incident.critic_results}
            evidenceLookup={evidenceLookup}
          />

          <ReEvaluationLoopIndicator events={events} />
          <CriticChallengePanel critiques={incident.critic_results} />

          {incident.decision && (
            <DecisionPanel decision={incident.decision} hypotheses={incident.hypotheses} />
          )}

          <RecoveryPanel incident={incident} events={events} />
        </div>

        <div className={styles.rail}>
          <A2AStreamPanel rows={a2aRows(events)} />
          <MCPActivityPanel rows={mcpRows(events, evidenceLookup)} />
          <UsagePanel usage={incident.token_usage} />
        </div>
      </div>
    </div>
  );
}
