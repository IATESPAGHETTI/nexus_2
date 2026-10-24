import { useEffect } from "react";
import { Link } from "react-router-dom";
import { motion } from "motion/react";
import { useHashScroll } from "../lib/useHashScroll";
import { SectionMarker } from "../components/story/StorySections";
import { listRecordings } from "../api/recordings";
import bench from "../data/benchmark.json";
import styles from "./ResearchPage.module.css";

const EASE = [0.16, 1, 0.3, 1] as const;

function Reveal({ children, delay = 0 }: { children: React.ReactNode; delay?: number }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 18 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-40px" }}
      transition={{ duration: 0.55, ease: EASE, delay }}
    >
      {children}
    </motion.div>
  );
}

function Head({ id, label, title, lead }: { id: string; label: string; title: string; lead: string }) {
  return (
    <>
      <SectionMarker label={label} />
      <h2 id={id} className={styles.title}>
        {title} <span>{lead}</span>
      </h2>
    </>
  );
}

/* ---------------- 1. Research question ---------------- */

type Arm = { name: string; agents: string; status: "built" | "proposed"; changes: string; where: string; key?: "single_agent_baseline" | "full_nexus" | "nexus_no_critic" | "nexus_triage" };

// "built" arms exist in evaluation/run_experiment.py today; "proposed" arms do not exist yet.
const ARMS: Arm[] = [
  {
    name: "Single-agent baseline",
    key: "single_agent_baseline",
    agents: "1 model call, no tools",
    status: "built",
    changes: "One flat snapshot of metrics, logs, changes and DB stats; picks a root cause from a closed list.",
    where: "evaluation/baselines.py",
  },
  {
    name: "Full NEXUS",
    key: "full_nexus",
    agents: "6 diagnosis agents",
    status: "built",
    changes: "4 specialists, Evidence Agent and Critic, with the bounded re-evaluation loop. Recovery is switched off.",
    where: "orchestrator/investigation.py",
  },
  {
    name: "NEXUS without the Critic",
    key: "nexus_no_critic",
    agents: "5 diagnosis agents",
    status: "built",
    changes: "The leading hypothesis is accepted without review. Zero A2A calls to the Critic.",
    where: "skip_critic=True",
  },
  {
    name: "Full NEXUS with triage",
    key: "nexus_triage",
    agents: "2 to 4 specialists chosen from the symptom text, + Evidence + Critic",
    status: "built",
    changes: "The Incident Manager calls Metrics plus only the specialists the symptom points at (at least 2). Later rounds re-ask only the ones the Critic points at. This is the working form of \u201cfewer agents\u201d.",
    where: "orchestrator/triage.py",
  },
  {
    name: "Fewer specialists, fixed",
    agents: "e.g. 2 or 3 specialists + Evidence + Critic",
    status: "proposed",
    changes: "Always drop or merge the same specialists (for example Logs & Traces with Metrics). Tests whether four independent evidence sources are needed.",
    where: "not built yet",
  },
  {
    name: "Leave-one-out specialist",
    agents: "full NEXUS minus one specialist",
    status: "proposed",
    changes: "Remove each specialist in turn and see which fault classes get misdiagnosed. Shows which agents carry weight.",
    where: "not built yet",
  },
];

const METRICS: [string, string][] = [
  ["Root-cause accuracy", "Share of runs whose diagnosis matches the injected fault."],
  ["False diagnosis rate", "Confident but wrong. The costly failure."],
  ["Abstention rate", "How often the system declines to name a cause."],
  ["Diagnosis time", "Wall-clock seconds from incident to decision."],
  ["Cost", "Model calls and tool calls per run. Token cost is reported only where the provider returns it."],
];

type ArmKey = "single_agent_baseline" | "full_nexus" | "nexus_no_critic" | "nexus_triage";
interface Agg {
  total: number;
  correct: number;
  false_diagnosis_rate: number;
  abstention_rate: number;
  avg_latency_seconds: number;
  avg_llm_calls: number;
  avg_total_tokens: number;
  per_run_accuracy: number[];
  avg_specialists: number | null;
}
const AGG = bench.aggregates as unknown as Record<ArmKey, Agg>;
const pct = (v: number) => `${Math.round(v * 100)}%`;

function ArmResult({ arm }: { arm: ArmKey }) {
  const a = AGG[arm];
  return (
    <span className={styles.result}>
      <b>
        {a.correct} of {a.total} correct
      </b>
      <span>per run: {a.per_run_accuracy.map(pct).join(", ")}</span>
      <span>
        {pct(a.false_diagnosis_rate)} false · {pct(a.abstention_rate)} abstained
      </span>
      <span>
        {Math.round(a.avg_latency_seconds)}s · {a.avg_llm_calls} calls · {a.avg_total_tokens.toLocaleString()} tokens
        {a.avg_specialists ? ` · ${a.avg_specialists} specialists` : ""}
      </span>
    </span>
  );
}

const OUTCOME_CLASS: Record<string, string> = {
  correct: "chipOn",
  "false diagnosis": "chipBad",
  abstained: "chipOff",
  "no diagnosis": "chipOff",
};

function ResultsByScenario() {
  const arms: [ArmKey, string][] = [
    ["single_agent_baseline", "Single agent"],
    ["full_nexus", "Full NEXUS"],
    ["nexus_no_critic", "No critic"],
    ["nexus_triage", "Triage"],
  ];
  const tv = bench.triage_vs_full;
  return (
    <>
      <h3 className={styles.subhead}>Per-fault outcomes, three runs each</h3>
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Fault</th>
              {arms.map(([, l]) => (
                <th key={l}>{l}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {bench.runs.map((r) => (
              <tr key={r.scenario}>
                <td>
                  <code>{r.scenario}</code>
                </td>
                {arms.map(([k]) => {
                  const x = r[k];
                  const mean = Math.round(x.tokens.reduce((p, c) => p + (c ?? 0), 0) / x.tokens.length);
                  return (
                    <td key={k}>
                      <span className={styles.chips}>
                        {x.outcomes.map((o, i) => (
                          <span key={i} className={`${styles.chip} ${styles[OUTCOME_CLASS[o]]}`}>
                            {o === "correct" ? "ok" : o === "no diagnosis" ? "none" : o === "abstained" ? "abstained" : "wrong"}
                          </span>
                        ))}
                      </span>
                      <span className={styles.where}>{mean.toLocaleString()} tokens on average</span>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className={styles.callout} style={{ marginTop: "1.5rem" }}>
        <span className={styles.calloutTag}>Reading it</span>
        <p>
          Over three runs of five faults (15 fault-runs per arm), every arm was right in 14 or 15 of them: the single
          call 15, full NEXUS 14, no Critic 14, triage 14. Every miss was the same fault, resource exhaustion, and it
          moved between arms from run to run, so it looks like noise and not a real difference. Triage called about{" "}
          {AGG.nexus_triage.avg_specialists} specialists on average instead of 4 and used{" "}
          {Math.round((1 - tv.triage_tokens / tv.full_tokens) * 100)}% fewer tokens in total (
          {tv.triage_tokens.toLocaleString()} against {tv.full_tokens.toLocaleString()}), and was cheaper in{" "}
          {tv.triage_cheaper_in} of {tv.of} fault-runs. So it cut the agents and the cost slightly. An earlier single
          run had suggested it cost more, which the repeats did not bear out. A single model call matched every arm at
          roughly one thirteenth of the tokens. These faults are single-cause and deterministic, so none of this shows
          that fewer agents would hold up on subtler incidents.
        </p>
      </div>
    </>
  );
}

function RecordedRuns() {
  const runs = listRecordings();
  if (runs.length === 0) return null;
  return (
    <>
      <h3 className={styles.subhead}>Watch a recorded run</h3>
      <p className={styles.recordedLead}>
        These are real investigations from the benchmark above, saved unchanged and played back on the live
        investigation page with a &ldquo;Recorded run, not live&rdquo; banner. They show the full flow (agents, tools,
        evidence, hypotheses, Critic, decision) without spending any model credits.
      </p>
      <div className={styles.grid}>
        {runs.map((r) => (
          <article key={r.incident.incident_id} className={styles.card}>
            <span className={`${styles.chip} ${styles.chipOn}`}>Recorded</span>
            <h4 className={styles.cardName}>{r.recording.scenario}</h4>
            <p className={styles.cardText}>
              {r.incident.description}
              <br />
              Result: {r.recording.outcome}. {r.events.length} events.
            </p>
            <Link className={styles.recordedLink} to={`/incidents/${r.incident.incident_id}`}>
              Watch the recorded run &rarr;
            </Link>
          </article>
        ))}
      </div>
    </>
  );
}

function ResearchQuestion() {
  return (
    <section id="rq" className={styles.section}>
      <div className={styles.container}>
        <Head
          id="rq-title"
          label="Research question"
          title="Can NEXUS use fewer agents and still diagnose correctly?"
          lead="Every agent adds paid model calls. The question is how many of them earn their place."
        />
        <Reveal>
          <div className={styles.callout}>
            <span className={styles.calloutTag}>Status</span>
            <p>
              <b>Measured 2026-10-13 and 2026-10-14.</b> Model <code>{bench.model}</code>, 5 faults, run {bench.n_runs}{" "}
              times per arm (15 fault-runs per arm), on the merged code. This is a small sample, and the faults are simple.
              The &ldquo;full&rdquo; and &ldquo;no critic&rdquo; arms called all four specialists; the triage arm let the
              Incident Manager choose. The leave-one-out arm has not been built, so it shows no number. Values come from{" "}
              <code>evaluation/results/</code>.
            </p>
          </div>
        </Reveal>

        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Arm</th>
                <th>Agents</th>
                <th>What changes</th>
                <th>Status</th>
                <th>Result</th>
              </tr>
            </thead>
            <tbody>
              {ARMS.map((a) => (
                <tr key={a.name}>
                  <td>
                    <b>{a.name}</b>
                    <span className={styles.where}>{a.where}</span>
                  </td>
                  <td>{a.agents}</td>
                  <td>{a.changes}</td>
                  <td>
                    <span className={`${styles.chip} ${a.status === "built" ? styles.chipOn : styles.chipOff}`}>
                      {a.status === "built" ? "Implemented" : "Proposed"}
                    </span>
                  </td>
                  <td className={a.key ? undefined : styles.pending}>
                    {a.key ? <ArmResult arm={a.key} /> : "Not yet measured"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <ResultsByScenario />

        <RecordedRuns />

        <h3 className={styles.subhead}>What counts as &ldquo;reduced without loss&rdquo;</h3>
        <div className={styles.grid}>
          {METRICS.map(([n, t], i) => (
            <Reveal key={n} delay={(i % 3) * 0.06}>
              <article className={styles.card}>
                <h4 className={styles.cardName}>{n}</h4>
                <p className={styles.cardText}>{t}</p>
              </article>
            </Reveal>
          ))}
          <Reveal delay={0.12}>
            <article className={`${styles.card} ${styles.cardRule}`}>
              <h4 className={styles.cardName}>Decision rule</h4>
              <p className={styles.cardText}>
                An agent can be removed only if accuracy does not drop and the false diagnosis rate does not rise on
                the same scenarios. A cheaper system that guesses more is not a reduction, it is a regression.
              </p>
            </article>
          </Reveal>
        </div>
      </div>
    </section>
  );
}

/* ---------------- 2. Design sequence ---------------- */

type Step = { n: string; actor: string; text: string; kind?: "branch" | "gate" };

// Order taken from orchestrator/investigation.py and orchestrator/recovery.py.
const SEQUENCE: Step[] = [
  { n: "01", actor: "Fault injector", text: "A controlled fault is injected into the simulated production service. The incident is created and an INCIDENT_CREATED event is written." },
  { n: "02", actor: "Incident Manager", text: "Fans one question out to the four specialists over A2A, in parallel. Each call is its own task." },
  { n: "03", actor: "Specialists", text: "Metrics, Logs & Traces, Change Analysis and Database each call their own MCP tools and return structured findings with evidence IDs." },
  { n: "04", actor: "Evidence Agent", text: "Reads all findings, with no tools, and proposes hypotheses that cite those evidence IDs. IDs that do not exist are dropped and counted." },
  { n: "05", actor: "Root-Cause Critic", text: "Challenges the leading hypothesis and looks for contradictions. Returns SUPPORTED, CONTRADICTED, INSUFFICIENT_EVIDENCE, REQUEST_MORE_EVIDENCE or ABSTAIN.", kind: "branch" },
  { n: "06", actor: "Incident Manager", text: "SUPPORTED ends in a diagnosis. ABSTAIN ends in abstention. Missing evidence sends the question back to step 02, up to MAX_REEVALUATION_LOOPS (default 3). Hitting the cap abstains.", kind: "branch" },
  { n: "07", actor: "Recovery Agent", text: "Only after a diagnosis. An LLM with no tools that can emit a JSON proposal and nothing else." },
  { n: "08", actor: "Guardrails", text: "Plain code re-validates the proposal against the allow-list. Any bad action rejects the whole plan.", kind: "gate" },
  { n: "09", actor: "Human", text: "Approval is requested and waits up to 600 seconds. Reject or timeout stops here; nothing is executed.", kind: "gate" },
  { n: "10", actor: "Executor", text: "Runs the approved actions one at a time, checking the kill switch before each, and stops on the first failure.", kind: "gate" },
  { n: "11", actor: "Verifier", text: "Timed real requests to production decide the outcome. Resolved only if latency and failures are both healthy." },
];

function Sequence() {
  return (
    <section id="sequence" className={`${styles.section} ${styles.alt}`}>
      <div className={styles.container}>
        <Head
          id="seq-title"
          label="Architectural design sequence"
          title="From injected fault to verified recovery, in eleven steps."
          lead="The order is fixed in code. No step can be skipped, including in the demo."
        />
        <ol className={styles.seq}>
          {SEQUENCE.map((s, i) => (
            <motion.li
              key={s.n}
              className={`${styles.step} ${s.kind === "gate" ? styles.stepGate : ""} ${s.kind === "branch" ? styles.stepBranch : ""}`}
              initial={{ opacity: 0, x: -14 }}
              whileInView={{ opacity: 1, x: 0 }}
              viewport={{ once: true, margin: "-30px" }}
              transition={{ duration: 0.45, ease: EASE, delay: (i % 4) * 0.05 }}
            >
              <span className={styles.stepN}>{s.n}</span>
              <div>
                <span className={styles.actor}>{s.actor}</span>
                <p>{s.text}</p>
              </div>
            </motion.li>
          ))}
        </ol>
        <p className={styles.foot}>
          Orange-edged steps are decision points; dark-edged steps are safety gates. Drawn from{" "}
          <code>orchestrator/investigation.py</code> and <code>orchestrator/recovery.py</code>, not from a recorded run.
        </p>
      </div>
    </section>
  );
}

/* ---------------- 3. Safety net ---------------- */

const LAYERS: [string, string, string][] = [
  ["No tools on the Recovery Agent", "The model that proposes fixes cannot execute anything. It can only return a JSON plan.", "agents/recovery/"],
  ["Action allow-list", "Four actions only: restart_service, rollback_deployment, reset_config, scale_resources. Each is bound to exactly one admin endpoint and a closed set of parameters.", "guardrails/config.py"],
  ["Deterministic validation", "At most 3 actions per plan, HIGH risk always rejected, a rollback plan required. One bad action rejects the whole plan.", "guardrails/policy.py"],
  ["Human approval", "Nothing runs until a person approves. If the window closes, the plan is dropped and nothing is executed.", "orchestrator/recovery.py"],
  ["Kill switch", "A file checked live before every single action, so it works mid-execution. Engaging it stops the run.", "guardrails/kill_switch.py"],
  ["Stop on failure", "A failed action halts the plan. It is recorded as it happened and never retried automatically.", "guardrails/executor.py"],
  ["Independent verification", "Resolved only when a live probe shows healthy latency and failure rate. Restarting is not counted as fixing.", "orchestrator/recovery.py"],
  ["Bounded investigation", "A loop cap on re-evaluation, and abstention as a valid result. A garbled critic reply counts as insufficient evidence.", "orchestrator/investigation.py"],
];

const GAPS: string[] = [
  "Recovery (approve, execute, verify) was last checked live before the provider key was revoked. It has not been re-run end to end since.",
  "Token counts are provider-reported per model call. Dollar cost and remaining quota are still not computed; the usage panel says so.",
  "The MCP process leak is fixed for the diagnostic agents and covered by a test. Other long-running processes were not audited.",
];

function SafetyNet() {
  return (
    <section id="safety" className={styles.section}>
      <div className={styles.container}>
        <Head
          id="safety-title"
          label="Safety net"
          title="The model proposes. Plain code and a person decide."
          lead="Eight layers stand between a model's suggestion and a change to production."
        />
        <div className={styles.grid}>
          {LAYERS.map(([n, t, w], i) => (
            <Reveal key={n} delay={(i % 3) * 0.06}>
              <article className={styles.card}>
                <span className={styles.layerN}>Layer {i + 1}</span>
                <h4 className={styles.cardName}>{n}</h4>
                <p className={styles.cardText}>{t}</p>
                <span className={styles.where}>{w}</span>
              </article>
            </Reveal>
          ))}
        </div>
        <h3 className={styles.subhead}>Known gaps</h3>
        <ul className={styles.gaps}>
          {GAPS.map((g) => (
            <li key={g}>{g}</li>
          ))}
        </ul>
      </div>
    </section>
  );
}

/* ---------------- 4. Methodology ---------------- */

const SCENARIOS: [string, string, string][] = [
  ["FI-bad-deployment", "bad_deployment", "Bug in order totals; about 35% of order requests return 500."],
  ["FI-db-slowdown", "db_slowdown", "Added latency on every database query."],
  ["FI-config-error", "config_error", "A bad configuration value."],
  ["FI-dependency-failure", "dependency_failure", "A downstream dependency fails."],
  ["FI-resource-exhaustion", "resource_exhaustion", "The service runs out of a resource."],
];

const DESIGN: [string, string, string][] = [
  ["Design", "Controlled comparison, within scenario", "Every arm is run on every scenario, so scenario difficulty cancels out."],
  ["Independent variable", "The agent configuration (arm)", "Single agent, full NEXUS, no Critic. Triage (now measured). Proposed: fixed fewer specialists, leave-one-out."],
  ["Dependent variables", "Accuracy, false diagnosis, abstention, time, cost", "Defined below, each with how it is computed."],
  ["Held constant", "Scenario, model, prompts, tools, loop cap", "Same live service, same runtime model, same MAX_REEVALUATION_LOOPS."],
  ["Blinding", "Agents never see ground truth", "Only run_experiment.py imports the scenario answers, and only after the run."],
];

const PROCEDURE: [string, string][] = [
  ["Reset", "Clear any fault so every run starts from a healthy service."],
  ["Inject", "Apply the scenario's fault through the production admin endpoint."],
  ["Run arm", "Run one arm on the live incident with real model calls. Recovery is off."],
  ["Record", "Store the decision, hypothesis text, timing and any failure as a raw record."],
  ["Score", "Compare the diagnosis with the ground truth after the run."],
  ["Aggregate", "Compute per-arm metrics and write the JSON report, including failed runs."],
];

const MEASURES: [string, string, string][] = [
  ["Root-cause accuracy", "correct diagnoses / runs", "NEXUS asserts a structured fault class from the same five-name list the single agent answers from. That class is compared with the truth."],
  ["False diagnosis rate", "wrong diagnoses / runs", "A confident wrong answer. Abstaining is never counted here."],
  ["Abstention rate", "abstentions / runs", "Reported separately so caution is not mistaken for accuracy."],
  ["Diagnosis time", "seconds, incident to decision", "Wall clock, including model latency."],
  ["Cost", "model calls and tokens per run", "Provider-reported only. Dollar cost and quota are not computed."],
];

const ANALYSIS: string[] = [
  "Per-arm metrics are aggregated over the same scenarios, so arms are compared like for like.",
  "A reduced configuration counts as a success only if accuracy holds and false diagnoses do not rise.",
  "With five scenarios the result is directional. No significance test is claimed.",
  "Failed runs (provider errors, rate limits) stay in the report and are not silently dropped.",
];

const THREATS: [string, string][] = [
  ["Small sample", "Five faults and three runs per arm. The repeats showed that single-run differences can be noise; the faults are still simple."],
  ["Single model", "One runtime model; results may not carry over."],
  ["Scoring", "An earlier keyword-matching scorer mislabelled correct answers and was replaced by the structured fault class. Reports from it are discarded."],
  ["Simulation gap", "The service is deterministic and simpler than real production."],
  ["Scope", "Recovery is excluded; this scores diagnosis, not remediation."],
];

function Methodology() {
  return (
    <section id="method" className={`${styles.section} ${styles.alt}`}>
      <div className={styles.container}>
        <Head
          id="method-title"
          label="Methodology"
          title="A controlled experiment: same faults, same model, only the agents change."
          lead="Ground truth is held by the evaluator and never reaches the agents."
        />

        <h3 className={styles.subhead0}>Experimental design</h3>
        <dl className={styles.design}>
          {DESIGN.map(([k, v, d]) => (
            <div key={k} className={styles.designRow}>
              <dt>{k}</dt>
              <dd>
                <b>{v}</b>
                <span>{d}</span>
              </dd>
            </div>
          ))}
        </dl>

        <h3 className={styles.subhead}>Procedure, repeated for every scenario and arm</h3>
        <ol className={styles.flow}>
          {PROCEDURE.map(([n, t], i) => (
            <motion.li
              key={n}
              initial={{ opacity: 0, y: 14 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-30px" }}
              transition={{ duration: 0.45, ease: EASE, delay: i * 0.06 }}
            >
              <span className={styles.flowN}>{i + 1}</span>
              <b>{n}</b>
              <span>{t}</span>
            </motion.li>
          ))}
        </ol>

        <h3 className={styles.subhead}>Fault scenarios (the test set)</h3>
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr><th>Scenario</th><th>Fault type</th><th>Symptom</th></tr>
            </thead>
            <tbody>
              {SCENARIOS.map(([id, ft, d]) => (
                <tr key={id}>
                  <td><code>{id}</code></td>
                  <td><code>{ft}</code></td>
                  <td>{d}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <h3 className={styles.subhead}>Measures and how each is computed</h3>
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr><th>Measure</th><th>Definition</th><th>Note</th></tr>
            </thead>
            <tbody>
              {MEASURES.map(([m, d, n]) => (
                <tr key={m}>
                  <td><b>{m}</b></td>
                  <td>{d}</td>
                  <td>{n}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className={styles.split2}>
          <div>
            <h3 className={styles.subhead}>Analysis plan</h3>
            <ul className={styles.gaps}>
              {ANALYSIS.map((g) => <li key={g}>{g}</li>)}
            </ul>
          </div>
          <div>
            <h3 className={styles.subhead}>Threats to validity</h3>
            <ul className={styles.threats}>
              {THREATS.map(([k, v]) => (
                <li key={k}><b>{k}</b><span>{v}</span></li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ---------------- 5. How it improved ---------------- */

type Fix = { problem: string; found: string; fix: string; check: string };

// Every row came from reading stored incidents or reports from real runs.
const FIXES: Fix[] = [
  {
    problem: "The scorer matched keywords in free text, so correct answers were marked wrong.",
    found: "Read the statements behind the “false diagnoses”.",
    fix: "The Evidence Agent now outputs a structured fault class from the same five-name list the baseline answers from. Scoring uses that.",
    check: "Unit tests for the class validation and a negation guard.",
  },
  {
    problem: "A stale “bad deployment” record and old logs survived between scenarios and contaminated later runs.",
    found: "Every later scenario blamed a deployment.",
    fix: "A full production reset before every arm.",
    check: "Regression test on the reset endpoint.",
  },
  {
    problem: "Faults were invisible: with no customer traffic the evidence looked healthy.",
    found: "A smoke run reported a healthy service during an injected fault.",
    fix: "The same 30 customer requests are sent before every arm.",
    check: "Runner change, covered by the benchmark itself.",
  },
  {
    problem: "The Critic demanded evidence no tool can return, and treated partial failure as a contradiction.",
    found: "Read the Critic’s stored verdicts on the runs that abstained.",
    fix: "Its prompt states what evidence can exist, forbids requesting anything outside it, and says partial failure is not a contradiction.",
    check: "Checked on live runs: the abstentions disappeared.",
  },
  {
    problem: "The git-diff tool crashed on Windows, so the diff was missing from the evidence.",
    found: "The Critic wrote “the git diff failed”. Reproduced it.",
    fix: "Git output is decoded as UTF-8.",
    check: "Regression test.",
  },
  {
    problem: "The re-evaluation loop repeated the same request until it hit the cap (31 to 34 model calls per abstention).",
    found: "Counted calls per abstained incident.",
    fix: "The loop stops when the Critic repeats a request or asks for nothing obtainable.",
    check: "Three loop tests.",
  },
  {
    problem: "The test harness showed up in the evidence: admin calls in the logs and a deployment tagged as injected.",
    found: "The Critic’s approval cited the fault-inject call.",
    fix: "Admin calls are no longer recorded, and the injected deployment looks like an ordinary one.",
    check: "Two regression tests.",
  },
  {
    problem: "Every investigation leaked one MCP server process.",
    found: "76 orphaned processes were found after earlier runs.",
    fix: "The toolset and runner are closed after each investigation.",
    check: "A test that fails without the fix and passes with it.",
  },
  {
    problem: "No token numbers: the usage panel said “unavailable”.",
    found: "The panel was a placeholder.",
    fix: "Provider-reported usage is metered per agent and summed per incident.",
    check: "Unit tests, and checked on live runs.",
  },
];

const BEFORE_AFTER: [string, string, string][] = [
  ["Accuracy", "40%", "80%"],
  ["False diagnoses", "20%", "0%"],
  ["Abstained", "40%", "0%"],
  ["Average tokens", "119,736", "70,255"],
  ["Average time", "84s", "51s"],
  ["Average model calls", "31", "18.8"],
];

function Improvements() {
  return (
    <section id="improved" className={styles.section}>
      <div className={styles.container}>
        <Head
          id="improved-title"
          label="How it improved"
          title="Nine problems, each found by reading real runs."
          lead="None of these came from guessing. Each was visible in a stored incident or a benchmark report."
        />

        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Problem</th>
                <th>How it was found</th>
                <th>Fix</th>
                <th>Check</th>
              </tr>
            </thead>
            <tbody>
              {FIXES.map((f) => (
                <tr key={f.problem}>
                  <td>{f.problem}</td>
                  <td>{f.found}</td>
                  <td>{f.fix}</td>
                  <td>{f.check}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <h3 className={styles.subhead}>Full NEXUS, before and after</h3>
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Measure</th>
                <th>First structured-scoring run</th>
                <th>After the fixes</th>
              </tr>
            </thead>
            <tbody>
              {BEFORE_AFTER.map(([m, b, a]) => (
                <tr key={m}>
                  <td>
                    <b>{m}</b>
                  </td>
                  <td>{b}</td>
                  <td>
                    <b>{a}</b>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className={styles.callout} style={{ marginTop: "1.5rem" }}>
          <span className={styles.calloutTag}>Read with care</span>
          <p>
            Both columns are one run per arm on five scenarios, and were measured on different code (the first before
            the fixes, the second on the merged branch). The Critic fix and the harness-leak fix were finished
            between the two runs, so the gain cannot be split between them. One check isolates the Critic fix: on the
            bad-deployment scenario, before the leak was closed, the same arm went from abstaining after 31 calls and
            104,000 tokens to a correct diagnosis in 10 calls and 30,000 tokens. The no-critic arm moved the opposite
            way between the same two runs (80% to 40%), which shows how much a single run can swing.
          </p>
        </div>
      </div>
    </section>
  );
}

export function ResearchPage() {
  useHashScroll();
  useEffect(() => {
    const previous = document.body.style.backgroundColor;
    document.body.style.backgroundColor = "#ffffff";
    return () => {
      document.body.style.backgroundColor = previous;
    };
  }, []);
  return (
    <div className={styles.page}>
      <header className={styles.hero}>
        <div className={styles.container}>
          <span className={styles.eyebrow}>Research</span>
          <h1>How NEXUS is built, protected and evaluated.</h1>
          <p>
            Research question, design sequence, safety net and method. Content is taken from the code and docs; items
            not yet built or measured are labelled as such.
          </p>
          <nav className={styles.toc} aria-label="On this page">
            <a href="#rq">Research question</a>
            <a href="#sequence">Design sequence</a>
            <a href="#safety">Safety net</a>
            <a href="#method">Methodology</a>
            <a href="#improved">How it improved</a>
          </nav>
        </div>
      </header>
      <ResearchQuestion />
      <Sequence />
      <SafetyNet />
      <Methodology />
      <Improvements />
    </div>
  );
}
