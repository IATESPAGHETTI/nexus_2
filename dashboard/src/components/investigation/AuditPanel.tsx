import { GlassSurface } from "../primitives/GlassSurface";
import styles from "./AuditPanel.module.css";

/**
 * Observability and provenance (course requirement 9), rendered from what the orchestrator stored on the incident:
 * `run_config`, `trace_id`, `trace` (span tree), `lineage` (conclusion -> evidence -> critique -> plan) and the
 * shared `blackboard`. Nothing here is computed in the browser; absent data shows an explicit empty state.
 */
interface Span {
  span_id: string;
  parent_span_id: string | null;
  name: string;
  kind: string;
  duration_ms?: number | null;
  trace_id_seen_by_agent?: string | null;
  start_estimated?: boolean;
  offset_ms?: number | null;
  ok?: boolean | null;
  prompt_variant?: string | null;
}
interface EvidenceRef {
  evidence_id: string;
  tool?: string;
  agent?: string;
  missing?: boolean;
}
export interface AuditIncident {
  trace_id?: string;
  run_config?: Record<string, unknown>;
  trace?: { spans: Span[]; span_count: number; note?: string };
  lineage?: {
    conclusion: string | null;
    evidence: EvidenceRef[];
    critique: { verdict?: string; framework?: string } | null;
    recovery_actions: string[];
  };
  blackboard?: { entry_id: string; type: string; author: string; timestamp: string; content?: Record<string, unknown> }[];
  report?: {
    markdown?: string;
    summary_rows?: string[][];
    hypotheses?: { hypothesis_id: string; status: string; confidence: number; statement: string; supporting: number; contradicting: number }[];
  };
  incident_id?: string;
}

/** One line saying what a board entry holds, from its real content (nothing is invented). */
function describeEntry(type: string, content: Record<string, unknown> | undefined): string {
  const c = content ?? {};
  const text = (v: unknown) => (typeof v === "string" ? v : "");
  const clip = (s: string, n = 110) => (s.length > n ? `${s.slice(0, n)}…` : s);
  switch (type) {
    case "description":
      return clip(text(c.text));
    case "request": {
      const t = text(c.text);
      const handoff = t.indexOf("HANDOFF from the");
      const targets = Array.isArray(c.targets) ? (c.targets as string[]).join(", ") : "";
      return handoff >= 0 ? `hand-off to ${targets}: ${clip(t.slice(handoff + 17), 90)}` : `ask ${targets}`;
    }
    case "finding":
      return `${clip(text(c.interpretation), 100)} (confidence ${typeof c.confidence === "number" ? Math.round(c.confidence * 100) : "?"}%)`;
    case "hypotheses": {
      const list = Array.isArray(c.hypotheses) ? (c.hypotheses as { statement?: string }[]) : [];
      return `${list.length} hypothes${list.length === 1 ? "is" : "es"}${list[0]?.statement ? `: ${clip(list[0].statement, 80)}` : ""}`;
    }
    case "review_request": {
      const h = (c.hypothesis ?? {}) as { hypothesis_id?: string };
      return `review ${h.hypothesis_id ?? "hypothesis"}`;
    }
    case "critique":
      return `verdict ${text(c.verdict) || "?"}`;
    default:
      return "";
  }
}

export function AuditPanel({ incident }: { incident: AuditIncident }) {
  const spans = incident.trace?.spans ?? [];
  const agents = spans.filter((s) => s.kind === "agent");
  const board = incident.blackboard ?? [];
  const rootMs = spans.find((s) => s.kind === "incident")?.duration_ms ?? 0;
  const cfg = Object.entries(incident.run_config ?? {});
  const hasAnything = incident.trace_id || spans.length || board.length || incident.lineage;

  return (
    <GlassSurface className={styles.wrap} light>
      <div className={styles.title}>Audit trail &amp; provenance</div>
      {!hasAnything && <div className={styles.empty}>Recorded when an investigation finishes.</div>}

      {incident.trace_id && (
        <div className={styles.row}>
          <span className={styles.label}>Trace id</span>
          <code className={styles.value} title="One id for the whole investigation, sent to every agent as a W3C traceparent header">
            {incident.trace_id}
          </code>
        </div>
      )}

      {cfg.length > 0 && (
        <div className={styles.chips}>
          {cfg.map(([k, v]) => (
            <span key={k} className={styles.chip}>
              {k}: <b>{String(v)}</b>
            </span>
          ))}
        </div>
      )}

      {agents.length > 0 && rootMs > 0 && (
        <>
          <div className={styles.sub}>Timeline (each bar = one agent's run, within the whole investigation)</div>
          <div className={styles.timeline}>
            {agents.map((s) =>
              typeof s.offset_ms === "number" && typeof s.duration_ms === "number" ? (
                <div key={s.span_id} className={styles.tlRow} title={`${s.name}: starts ${(s.offset_ms / 1000).toFixed(1)} s, runs ${(s.duration_ms / 1000).toFixed(1)} s`}>
                  <span className={styles.tlLabel}>{s.name.replace("agent ", "")}</span>
                  <span className={styles.tlTrack}>
                    <span
                      className={styles.tlBar}
                      style={{
                        left: `${Math.min(99, (s.offset_ms / rootMs) * 100)}%`,
                        width: `${Math.max(1.5, Math.min(100 - (s.offset_ms / rootMs) * 100, (s.duration_ms / rootMs) * 100))}%`,
                      }}
                    />
                  </span>
                </div>
              ) : null,
            )}
          </div>
          <div className={styles.note}>Whole investigation: {(rootMs / 1000).toFixed(0)} s. Times are reconstructed and accurate to about a second.</div>
        </>
      )}

      {agents.length > 0 && (
        <>
          <div className={styles.sub}>Agents seen in the trace</div>
          <table className={styles.table}>
            <tbody>
              {agents.map((s) => (
                <tr key={s.span_id}>
                  <td>{s.name.replace("agent ", "")}</td>
                  <td>{s.duration_ms != null ? `${s.duration_ms} ms` : "—"}</td>
                  <td title="The trace id this agent process received over the wire">
                    {s.trace_id_seen_by_agent && s.trace_id_seen_by_agent === incident.trace_id ? "same trace ✓" : "no trace id"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {incident.trace?.note && <div className={styles.note}>{incident.trace.note}</div>}
        </>
      )}

      {incident.lineage?.conclusion && (
        <>
          <div className={styles.sub}>Why we believe it</div>
          <div className={styles.text}>{incident.lineage.conclusion}</div>
          <ul className={styles.list}>
            {incident.lineage.evidence.map((e) => (
              <li key={e.evidence_id}>
                <code>{e.evidence_id}</code> {e.missing ? "(not found in any finding)" : `${e.tool} via ${e.agent}`}
              </li>
            ))}
          </ul>
          {incident.lineage.critique && (
            <div className={styles.text}>
              Critic: <b>{incident.lineage.critique.verdict}</b>
              {incident.lineage.critique.framework ? ` (${incident.lineage.critique.framework})` : ""}
            </div>
          )}
        </>
      )}

      {board.length > 0 && (
        <>
          <div className={styles.sub}>Shared blackboard ({board.length} entries)</div>
          <ul className={styles.list}>
            {board.map((e) => (
              <li key={e.entry_id}>
                <code>{e.entry_id}</code> {e.type} <span className={styles.dim}>by {e.author}</span>
                {describeEntry(e.type, e.content) && <div className={styles.dim}>{describeEntry(e.type, e.content)}</div>}
              </li>
            ))}
          </ul>
        </>
      )}

      {incident.report?.summary_rows && incident.report.summary_rows.length > 0 && (
        <>
          <div className={styles.sub}>Final report: summary</div>
          <table className={styles.table}>
            <tbody>
              {incident.report.summary_rows.map(([k, v]) => (
                <tr key={k}>
                  <td className={styles.label}>{k}</td>
                  <td>{v}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      {incident.report?.hypotheses && incident.report.hypotheses.length > 0 && (
        <>
          <div className={styles.sub}>Hypotheses</div>
          <table className={styles.table}>
            <tbody>
              {incident.report.hypotheses.map((h) => (
                <tr key={h.hypothesis_id}>
                  <td>{h.hypothesis_id}</td>
                  <td>{h.status}</td>
                  <td>{Math.round(h.confidence * 100)}%</td>
                  <td>
                    {h.supporting}/{h.contradicting} evidence
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      {incident.report?.markdown && incident.incident_id && (
        <div className={styles.row}>
          <a className={styles.label} href={`/api/incidents/${incident.incident_id}/report?format=md`} download>
            Download report (.md)
          </a>
          <a className={styles.label} href={`/api/incidents/${incident.incident_id}/report?format=json`} target="_blank" rel="noreferrer">
            Open as JSON
          </a>
        </div>
      )}
      {incident.report?.markdown && (
        <details className={styles.details}>
          <summary>Final report (Markdown source)</summary>
          <pre className={styles.pre}>{incident.report.markdown}</pre>
        </details>
      )}
    </GlassSurface>
  );
}
