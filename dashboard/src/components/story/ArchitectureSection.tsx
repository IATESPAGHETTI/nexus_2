import { motion } from "motion/react";
import { SectionMarker } from "./StorySections";
import styles from "./Architecture.module.css";

const EASE = [0.16, 1, 0.3, 1] as const;

type Pattern = { name: string; used: boolean; text: string; where: string };

// Each entry is checked against orchestrator/, agents/common/ and backend/ (see docs/ARCHITECTURE.md).
const PATTERNS: Pattern[] = [
  {
    name: "Hierarchy (hub and spoke)",
    used: true,
    text: "The Incident Manager is the only component that calls agents. All seven sit behind real A2A endpoints, each its own process and port with a public Agent Card. Specialists never call each other.",
    where: "orchestrator/incident_manager.py",
  },
  {
    name: "Fan-out and gather",
    used: true,
    text: "One question goes to the four specialists at once. Each gets its own A2A task ID and the manager gathers the findings. This is the nearest thing to broadcast, but it is four addressed calls, not a shared channel.",
    where: "ADK ParallelAgent over RemoteA2aAgent",
  },
  {
    name: "Pipeline with a feedback loop",
    used: true,
    text: "Evidence Agent, then Root-Cause Critic. If the critic wants more evidence the manager re-dispatches to the specialists and the cycle repeats, capped by MAX_REEVALUATION_LOOPS (default 3). Hitting the cap ends in abstention.",
    where: "orchestrator/investigation.py",
  },
  {
    name: "Event log (one writer, many readers)",
    used: true,
    text: "Every transition is written as a structured event to the backend event store. The dashboard and any auditor read the same log. The dashboard polls it about every 1.5 seconds; it is not a push stream.",
    where: "backend/app/incident_store.py",
  },
  {
    name: "Peer-to-peer mesh",
    used: false,
    text: "Agents negotiating directly. Not built. Specialists are meant to gather independent evidence; side conversations would let one agent's guess anchor the others, multiply paid model calls and scatter the audit trail.",
    where: "design choice",
  },
  {
    name: "Broadcast / publish-subscribe between agents",
    used: false,
    text: "A shared channel every agent listens to. Not built. No agent needs another's raw stream, and every listener would be another model call. The one-to-many need is met by fan-out plus the event log.",
    where: "design choice",
  },
];

const PRINCIPLES: [string, string][] = [
  ["Evidence before opinion", "Every hypothesis must cite evidence IDs that exist. Invented IDs are dropped in code and counted, never recorded as fact."],
  ["One job, least privilege", "Each specialist has its own tool allow-list. The Evidence Agent and the Critic have no tools at all; they only reason over what they are handed."],
  ["Isolation", "Every agent is a separate OS process. Each component has its own Python environment, so one dependency cannot break another."],
  ["Bounded, and allowed to say no", "A loop cap limits re-evaluation, and abstention is a valid result. A garbled critic reply counts as insufficient evidence, never as support."],
  ["Safety is plain code", "Guardrails are deterministic checks with no model in them: an action allow-list, a kill-switch file and a required human approval."],
  ["Auditable", "Agent calls, tool calls and decisions are events. MCP tool calls are also logged locally by the MCP server."],
];

const SPECIALISTS: [string, number][] = [
  ["Metrics", 8101],
  ["Logs & Traces", 8102],
  ["Change Analysis", 8103],
  ["Database", 8104],
];
const REASONING: [string, number][] = [
  ["Evidence", 8105],
  ["Root-Cause Critic", 8106],
  ["Recovery", 8107],
];

function Diagram() {
  const line = "#4a4a4a";
  const brand = "#f34e3f";
  const quiet = "#8a8a8a";
  return (
    <svg
      className={styles.svg}
      viewBox="0 0 780 522"
      role="img"
      aria-label="The Incident Manager in the centre calls four specialist agents in parallel above it. The specialists read a simulated shop through MCP tools. Below it the Evidence, Critic and Recovery agents are called in sequence, and the Critic can send the investigation back to the specialists for up to three rounds. Guardrails on the left check a proposed fix, wait for human approval, and only then change the shop. The event store on the right records every step."
    >
      <defs>
        <marker id="arch-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" fill={brand} />
        </marker>
        <marker id="arch-arrow-quiet" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" fill={quiet} />
        </marker>
      </defs>

      {/* ---- tool layer: specialists -> MCP -> the simulated shop ---- */}
      {SPECIALISTS.map(([, ], i) => {
        const cx = 125 + i * 170;
        return <line key={i} x1={cx} y1={126} x2={380} y2={64} stroke={line} strokeWidth={1.2} />;
      })}
      <rect x={280} y={14} width={200} height={50} rx={10} className={styles.box} />
      <text x={380} y={36} className={styles.boxName}>Simulated shop</text>
      <text x={380} y={53} className={styles.boxSub}>production · :8001</text>
      <rect x={265} y={78} width={230} height={22} rx={11} className={styles.pill} />
      <text x={380} y={93} className={styles.pillText}>MCP tools · one stdio server per task</text>

      {/* ---- the original hub-and-spoke, shifted down ---- */}
      <g transform="translate(0,100)">
        {SPECIALISTS.map(([, ], i) => {
          const cx = 125 + i * 170;
          return <line key={i} x1={380} y1={170} x2={cx} y2={80} stroke={brand} strokeWidth={1.5} className={styles.flow} />;
        })}
        {REASONING.map(([, ], i) => {
          const cx = 190 + i * 190;
          return <line key={i} x1={380} y1={226} x2={cx} y2={320} stroke={line} strokeWidth={1.5} />;
        })}
        <line x1={170} y1={198} x2={290} y2={198} stroke={line} strokeWidth={1.5} />
        <line x1={470} y1={198} x2={590} y2={198} stroke={line} strokeWidth={1.5} strokeDasharray="5 5" />

        {SPECIALISTS.map(([name, port], i) => {
          const x = 50 + i * 170;
          return (
            <g key={name}>
              <rect x={x} y={26} width={150} height={54} rx={10} className={styles.box} />
              <text x={x + 75} y={49} className={styles.boxName}>{name}</text>
              <text x={x + 75} y={67} className={styles.boxSub}>A2A :{port} · MCP tools</text>
            </g>
          );
        })}
        {REASONING.map(([name, port], i) => {
          const x = 115 + i * 190;
          return (
            <g key={name}>
              <rect x={x} y={320} width={150} height={54} rx={10} className={styles.box} />
              <text x={x + 75} y={343} className={styles.boxName}>{name}</text>
              <text x={x + 75} y={361} className={styles.boxSub}>A2A :{port} · no tools</text>
            </g>
          );
        })}

        <rect x={290} y={170} width={180} height={56} rx={12} className={styles.hub} />
        <text x={380} y={194} className={styles.hubName}>Incident Manager</text>
        <text x={380} y={212} className={styles.boxSub}>orchestrator</text>

        <rect x={30} y={176} width={140} height={44} rx={10} className={styles.box} />
        <text x={100} y={195} className={styles.boxName}>Guardrails</text>
        <text x={100} y={211} className={styles.boxSub}>in-process, no LLM</text>

        <rect x={590} y={176} width={140} height={44} rx={10} className={styles.box} />
        <text x={660} y={195} className={styles.boxName}>Event store</text>
        <text x={660} y={211} className={styles.boxSub}>backend · dashboard</text>

        <rect x={290} y={110} width={180} height={22} rx={11} className={styles.pill} />
        <text x={380} y={125} className={styles.pillText}>parallel fan-out</text>
        <rect x={290} y={268} width={180} height={22} rx={11} className={styles.pill} />
        <text x={380} y={283} className={styles.pillText}>sequential calls</text>
        <text x={530} y={190} className={styles.edgeLabel}>events</text>
      </g>

      {/* ---- the safety path: guardrails -> human -> (approved fix) -> the shop ---- */}
      <line x1={100} y1={320} x2={100} y2={346} stroke={line} strokeWidth={1.5} />
      <text x={150} y={338} className={styles.edgeLabel}>approve / reject</text>
      <rect x={30} y={348} width={140} height={44} rx={10} className={styles.box} />
      <text x={100} y={367} className={styles.boxName}>Human approval</text>
      <text x={100} y={383} className={styles.boxSub}>dashboard · backend</text>
      <path d="M30,298 L12,298 L12,39 L278,39" fill="none" stroke={quiet} strokeWidth={1.5} strokeDasharray="5 5" markerEnd="url(#arch-arrow-quiet)" />
      <text x={26} y={170} className={styles.edgeLabel} transform="rotate(-90 26 170)">runs the approved fix, nothing else</text>

      {/* ---- the evidence loop: Critic -> manager -> specialists, up to 3 rounds ---- */}
      <path d="M380,474 L380,510 L752,510 L752,153 L712,153" fill="none" stroke={brand} strokeWidth={1.5} strokeDasharray="2 5" markerEnd="url(#arch-arrow)" />
      <text x={768} y={330} className={styles.edgeLabel} transform="rotate(90 768 330)">evidence loop, via the manager · max 3 rounds</text>

      <text x={570} y={492} className={styles.edgeLabel}>runs only after the Critic approves</text>
    </svg>
  );
}

export function ArchitectureSection() {
  return (
    <section id="pl-architecture" className={styles.section}>
      <div className={styles.container}>
        <SectionMarker label="Architecture" />
        <motion.h2
          className={styles.title}
          initial={{ opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.7, ease: EASE }}
        >
          One coordinator, specialists that never talk to each other.{" "}
          <span>The shape is chosen so the evidence stays independent and the cost stays bounded.</span>
        </motion.h2>

        <motion.div
          className={styles.frame}
          initial={{ opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-60px" }}
          transition={{ duration: 0.7, ease: EASE }}
        >
          <Diagram />
          <p className={styles.note}>
            Drawn from the code in <code>orchestrator/</code>, <code>guardrails/</code> and <code>agents/common/ports.py</code>. It shows the
            architecture, not a recorded run. Every line marked A2A is a real network call between processes. Solid lines are calls,
            the red dashed lines are the parallel fan-out and the evidence loop, and the grey dashed line is the only path that changes the shop.
          </p>
        </motion.div>

        <h3 className={styles.subhead}>Communication patterns, and which ones NEXUS actually uses</h3>
        <div className={styles.grid}>
          {PATTERNS.map((p, i) => (
            <motion.article
              key={p.name}
              className={styles.card}
              initial={{ opacity: 0, y: 18 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-40px" }}
              transition={{ duration: 0.5, ease: EASE, delay: (i % 3) * 0.08 }}
            >
              <span className={`${styles.chip} ${p.used ? styles.chipOn : styles.chipOff}`}>
                {p.used ? "Implemented" : "Not used, by design"}
              </span>
              <h4 className={styles.cardName}>{p.name}</h4>
              <p className={styles.cardText}>{p.text}</p>
              <span className={styles.where}>{p.where}</span>
            </motion.article>
          ))}
        </div>

        <h3 className={styles.subhead}>Principles behind the design</h3>
        <ul className={styles.principles}>
          {PRINCIPLES.map(([name, text], i) => (
            <motion.li
              key={name}
              className={styles.principle}
              initial={{ opacity: 0, y: 14 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-30px" }}
              transition={{ duration: 0.45, ease: EASE, delay: (i % 3) * 0.06 }}
            >
              <span className={styles.principleN}>0{i + 1}</span>
              <b>{name}</b>
              <span>{text}</span>
            </motion.li>
          ))}
        </ul>
      </div>
    </section>
  );
}
