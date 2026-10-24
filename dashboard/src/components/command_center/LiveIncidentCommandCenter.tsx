import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useAgentControl } from "../../context/AgentControlContext";
import { useActiveIncident } from "../../api/useActiveIncident";
import { injectControlledFailure, resetShop, sendCustomerRequests, type InvestigateResult } from "../../api/client";
import { countEvents } from "../../lib/presentation";
import { IncidentHumanCard } from "./IncidentHumanCard";
import { SEVEN_QUESTIONS } from "./sevenQuestions";
import styles from "./LiveIncidentCommandCenter.module.css";

import { DEMO_SCENARIOS, scenarioById } from "../../lib/scenarios";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export function LiveIncidentCommandCenter() {
  const { agentsEnabled, backendReachable, demoStatus, setActiveIncidentId, isLoading: probing } = useAgentControl();
  const { live, incident, events, model, incidentMissing, isLoading } = useActiveIncident();
  const [step, setStep] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [scenarioId, setScenarioId] = useState(DEMO_SCENARIOS[0].id);
  const scenario = scenarioById(scenarioId);

  const productionUp = demoStatus?.production_reachable ?? false;
  const agentsOnline = demoStatus?.agents_reachable_count ?? 0;
  const agentsTotal = demoStatus?.agents_total ?? 7;

  const run = useMutation<InvestigateResult>({
    mutationFn: async () => {
      // Each demo starts from a clean shop, so leftovers of an earlier incident are not mistaken for evidence.
      setStep("Resetting the simulated shop to a clean state…");
      await resetShop();
      setStep("Sending normal customer requests to the simulated service…");
      await sendCustomerRequests(6);
      setStep(`Injecting the failure: ${scenario.label.toLowerCase()}…`);
      const res = await injectControlledFailure(scenario.id, scenario.symptom);
      setActiveIncidentId(res.incident_id);
      setStep("Sending customer requests to the degraded service…");
      await sendCustomerRequests(10);
      // Investigation starts immediately in the backend; keep real requests
      // flowing for a few seconds so the evidence the agents read is fresh.
      void (async () => {
        await sleep(2500);
        await sendCustomerRequests(8);
        await sleep(4000);
        await sendCustomerRequests(8);
      })();
      return res;
    },
    onSettled: () => {
      setStep(null);
      setConfirming(false);
    },
  });

  // One investigation at a time: each run makes many paid model calls.
  const inProgress = model?.status === "INVESTIGATING" || model?.recovery?.stage === "AWAITING_APPROVAL";

  const counts = countEvents(events);

  return (
    <section id="command-center" className={styles.section}>
      <div className={styles.container}>
        <div className={styles.header}>
          <div className={styles.headerLeft}>
            <div className={styles.eyebrow}>COMMAND CENTER</div>
            <h2 className={styles.title}>Live Incident Command Center</h2>
            <p className={styles.subtitle}>
              Seven questions a person would ask during an outage — answered from what NEXUS actually observed.
            </p>
          </div>

          <div className={styles.statusPills}>
            <div className={styles.statusPill}>
              <span className={`${styles.statusDot} ${!live ? styles.dotNeutral : productionUp ? styles.dotGreen : styles.dotRed}`} />
              <span className={styles.statusText}>
                Simulated service: {!agentsEnabled ? "not checked" : !backendReachable ? "unknown" : productionUp ? "reachable" : "unreachable"}
              </span>
            </div>
            <div className={styles.statusPill}>
              <span className={`${styles.statusDot} ${!agentsEnabled ? styles.dotNeutral : agentsOnline > 0 ? styles.dotGreen : styles.dotRed}`} />
              <span className={styles.statusText}>
                Agents: {!agentsEnabled ? "offline" : backendReachable ? `${agentsOnline}/${agentsTotal} reachable` : "unknown"}
              </span>
            </div>
            {live && model && (
              <div className={styles.statusPill}>
                <span className={`${styles.statusDot} ${styles.dotGreen}`} />
                <span className={styles.statusText}>
                  System checks run: {counts.mcp} · Agent messages: {counts.a2a}
                </span>
              </div>
            )}
          </div>
        </div>

        {/* ---- State: agents OFF -------------------------------------- */}
        {!agentsEnabled && (
          <>
            <div className={styles.offlineNotice}>
              <div className={styles.noticeContent}>
                <div className={styles.noticeTitle}>AGENTS OFFLINE · ILLUSTRATIVE DEMO</div>
                <div className={styles.noticeBody}>
                  Nothing below is live. This is a static explanation of what each question shows once the agents are
                  running — it contains no incident, no numbers and no evidence. Switch{" "}
                  <strong>NEXUS AGENTS</strong> to <strong>ON</strong> to connect to the real system.
                </div>
              </div>
            </div>
            <div className={styles.walkGrid}>
              {SEVEN_QUESTIONS.map((q) => (
                <div key={q.n} className={styles.walkCard}>
                  <div className={styles.walkNumber}>{q.n}</div>
                  <div className={styles.walkQuestion}>{q.question}</div>
                  <p className={styles.walkBody}>{q.shows}</p>
                </div>
              ))}
            </div>
          </>
        )}

        {/* ---- State: ON, first probe still in flight ------------------ */}
        {agentsEnabled && probing && (
          <div className={styles.offlineNotice}>
            <div className={styles.noticeContent}>
              <div className={styles.noticeTitle}>CONNECTING…</div>
              <div className={styles.noticeBody}>Probing the NEXUS backend. Nothing is shown until it answers.</div>
            </div>
          </div>
        )}

        {/* ---- State: ON but backend unreachable ----------------------- */}
        {agentsEnabled && !probing && !backendReachable && (
          <div className={styles.warningNotice}>
            <div className={styles.noticeContent}>
              <div className={styles.noticeTitle}>BACKEND UNREACHABLE</div>
              <div className={styles.noticeBody}>
                NEXUS could not reach its backend on <code>127.0.0.1:8000</code>. No incident data is shown, because
                nothing real is available to show. Start the backend, then this page reconnects on its own:
                <pre className={styles.codeSnippet}>python -m uvicorn app.main:app --port 8000</pre>
                See <code>docs/DEMO_RUNBOOK.md</code> for the full stack.
              </div>
            </div>
          </div>
        )}

        {/* ---- State: live ------------------------------------------- */}
        {live && (
          <>
            <div className={styles.liveNotice}>
              <div className={styles.noticeContent}>
                <div className={styles.noticeTitle}>LIVE — backend connected</div>
                <div className={styles.noticeBody}>
                  {agentsOnline === 0
                    ? "The backend is up but none of the 7 agent services answered. An injected failure would be recorded, but nothing would investigate it."
                    : agentsOnline < agentsTotal
                    ? `Only ${agentsOnline} of ${agentsTotal} agent services answered; an investigation may be incomplete.`
                    : "All 7 agent services answered."}{" "}
                  The demo failure is a <strong>database slowdown</strong> injected into the simulated order service;
                  real customer-style requests are sent to it so the slowdown is observable.
                </div>
                <div className={styles.scenarioRow} role="radiogroup" aria-label="Failure to inject">
                  {DEMO_SCENARIOS.map((sc) => (
                    <button
                      key={sc.id}
                      type="button"
                      role="radio"
                      aria-checked={sc.id === scenarioId}
                      disabled={run.isPending || inProgress}
                      className={`${styles.scenarioChip} ${sc.id === scenarioId ? styles.scenarioOn : ""}`}
                      onClick={() => setScenarioId(sc.id)}
                    >
                      {sc.label}
                    </button>
                  ))}
                </div>
                <div className={styles.scenarioBlurb}>{scenario.blurb}</div>
                {step && <div className={styles.stepLine}>{step}</div>}
                {run.isError && <div className={styles.errorLine}>Could not start the demo: {String(run.error)}</div>}
                {run.data && !run.data.investigation_triggered && (
                  <div className={styles.errorLine}>{run.data.note}</div>
                )}
              </div>
              <div className={styles.liveActions}>
                {confirming && !run.isPending ? (
                  <div className={styles.confirmBox}>
                    <p>
                      This starts a <b>real investigation</b>. It makes roughly 10 to 30 <b>paid model requests</b> to your LLM
                      provider (more if NEXUS re-investigates). Continue?
                    </p>
                    <div className={styles.confirmBtns}>
                      <button type="button" className={styles.injectBtn} onClick={() => run.mutate()}>
                        Yes, run it
                      </button>
                      <button type="button" className={styles.cancelBtn} onClick={() => setConfirming(false)}>
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <button
                    type="button"
                    className={styles.injectBtn}
                    disabled={run.isPending || !productionUp || inProgress}
                    onClick={() => setConfirming(true)}
                    title={
                      !productionUp
                        ? "The simulated production service is not reachable"
                        : inProgress
                        ? "An investigation is already in progress"
                        : undefined
                    }
                  >
                    {run.isPending ? "Running demo…" : inProgress ? "Investigation in progress" : `Inject: ${scenario.label}`}
                  </button>
                )}
                <a
                  href={import.meta.env.PROD ? "/shop/" : "http://localhost:8001/shop"}
                  target="_blank"
                  rel="noreferrer"
                  className={styles.shopLink}
                >
                  Open the simulated shop ↗
                </a>
              </div>
            </div>

            {model && incident ? (
              <div className={styles.cardWrapper}>
                <IncidentHumanCard model={model} incident={incident} events={events} agentsOnline={agentsOnline} />
              </div>
            ) : (
              <div className={styles.emptyLive}>
                <div className={styles.emptyTitle}>
                  {isLoading ? "Loading incident…" : incidentMissing ? "The backend no longer has that incident" : "No live incident yet"}
                </div>
                <p className={styles.emptyText}>
                  {incidentMissing
                    ? "The backend does not know that incident id (it may belong to a different database). Start a new one above."
                    : "Nothing has been reported. Pick a failure above and inject it to create a real incident, or open one from the Incidents page."}
                </p>
              </div>
            )}
          </>
        )}
      </div>
    </section>
  );
}
