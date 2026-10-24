# Dashboard Local Instructions

## Purpose
Live command center for an autonomous investigation — not a dashboard that
displays a prerecorded incident. Mission Control (real system status + the
real "Inject Controlled Failure" trigger), investigation graph, agent status
cards, A2A stream, MCP activity, timeline, evidence/hypothesis/critic/recovery
panels. Vanshika's workstream (implemented by Deepu). Stack: React +
TypeScript + Vite, hand-rolled CSS (tokens + CSS Modules, no utility
framework), Framer Motion, TanStack Query, React Router. Design direction
(2026-09, current): restrained premium observability aesthetic — warm
off-white/stone neutrals, translucent glass, no decorative color, no ambient
background effects; sophistication comes from spacing/typography/material
depth/motion and the live investigation itself. (Supersedes an earlier,
more colorful ambient-background pass from the same month that the user
explicitly reversed — see `docs/PROJECT_STATE.md`'s Phase 10 entries for
both, kept for accurate history.)

## Owned
- `src/styles/tokens.css` — design tokens: warm stone/cream/graphite/muted
  palette, no accent/decorative hues, semantic green/amber/red (state only;
  text variants darkened for small-text contrast — see the token comments),
  restrained glass material (16px blur, 115% saturate, soft shadow with an
  inset top highlight, no glow, 3 densities: default/`strong`/`light`),
  spacing/typography/motion constants.
- `src/styles/global.css` — a body background plus two faint, fixed, fully
  static (unanimated, unblurred) tonal gradients — not a decorative effect,
  just enough to keep the page from reading as one flat fill.
- `src/components/layout/` — `AppShell.tsx` (persistent left-sidebar
  layout wrapping every page; the app uses the full desktop viewport width,
  never a centered ~800px column) + `Sidebar.tsx` (Mission Control link,
  Active/Recent Incidents — real localStorage-cached incident_ids, each
  live-refetched so its status dot is current, never fabricated — and a
  compact real System Status block, same probe as `useDemoStatus`).
- `src/components/primitives/` — shared building blocks: `GlassSurface`,
  `StatusDot`, `Badge`, `ConfidenceBar` (spring-animated fill), `MonoLabel`,
  `Timestamp`, `CollapsibleSection`, `semantics.ts` (single source of truth
  mapping real backend enums -> the 4 semantic tones).
- `src/api/` — `types.ts` (mirrors `docs/API_CONTRACT.md`/`docs/EVENT_SCHEMA.md`
  exactly — must never drift from the real backend contract), `client.ts` (pure
  fetch wrapper, no business logic, incl. `injectControlledFailure`/
  `getDemoStatus`/`approveRecoveryPlan`), `useIncident.ts` (TanStack Query
  polling hooks + `deriveAgentStates`, which derives each diagnostic agent's
  IDLE/RUNNING/WAITING/COMPLETED/FAILED status purely from the real event
  log; `useIncidentQuery` polls through both `INVESTIGATING` and
  `DIAGNOSED` — the real recovery flow runs entirely inside `DIAGNOSED` —
  stopping only on the genuinely terminal `ABSTAINED`/`RESOLVED`),
  `useDemoStatus.ts` (polls `GET /demo/status` every 5s).
- `src/lib/derive.ts` — pure derivation helpers: phase index from real event
  types present, evidence_id -> real evidence item lookup, A2A/MCP row
  shaping. No component computes derived state inline outside this file.
- `src/lib/recentIncidents.ts` — localStorage-backed "recently opened
  incidents" convenience (see "No incidents list endpoint" below) — never a
  source of truth, always re-fetched live.
- `src/pages/MissionControlPage.tsx` — the home page: real system status
  (production/agent/MCP/A2A reachability, live-probed — see
  `backend/app/demo.py`), the real "Inject Controlled Failure" primary
  action (`POST /demo/investigate`, then navigates to the real incident_id
  it returns — never a fake timer or simulated event), and the real recent-
  incidents list.
- `src/pages/InvestigationPage.tsx` + `src/components/investigation/*` — the
  core screen: `TopBar`+`PhaseTimeline`, `AgentConstellation`, `A2AStreamPanel`,
  `MCPActivityPanel`, `HypothesisPanel` (selector + `HypothesisConstellation`,
  the evidence<->hypothesis spatial centerpiece + `RevisionBanner`),
  `CriticChallengePanel`, `ReEvaluationLoopIndicator`, `DecisionPanel`
  (diagnosis/abstention), `UsagePanel` (2026-10-10: renders the real
  `incident.token_usage` — model calls/tokens vs NEXUS's own limits, per-agent
  usage, a warning when a limit stopped the run; empty state when none recorded;
  provider quota is still always "Unavailable from provider"),
  `RecoveryPanel` (Phase 8, real — renders `incident.recovery_plan`/
  `approval_state`/`action_history` plus whichever real recovery-related
  events have actually been emitted; an honest neutral empty state, never
  "Pending", when none exist yet since recovery only triggers on a DIAGNOSED
  outcome; replaced the old static `RecoveryPlaceholder` stub). When
  `approval_state.decision === "PENDING"`, renders real Approve/Reject
  buttons wired to `POST /incidents/{id}/approve` (Phase 10) — a genuine
  human-in-the-loop action, not a mock.

## Rules
No business logic here — this is a pure renderer of `backend/` state and the live
event stream (`docs/EVENT_SCHEMA.md`). Never expose private model chain-of-thought;
only the auditable artifacts (observation, evidence, hypothesis, supporting/
contradicting evidence, requested evidence, decision). Never fabricate/invent
usage numbers, activity, or confidence deltas the real data doesn't support —
see `RevisionBanner.tsx`'s docstring for a concrete example (no same-hypothesis
confidence-delta signal exists in the real data; a verdict-transition + critic
rationale is shown instead of the originally-sketched "78% -> 41%" delta).
Every optional field on a real API response (see `Critique` in `api/types.ts`)
must be read defensively — `orchestrator/investigation.py`'s fallback critique
object (used when a real A2A response is unparseable) omits most fields, and
this was hit for real during Phase 7 verification (Groq daily quota
exhaustion), not just a hypothetical.

## No `GET /incidents` list endpoint (deliberate, Phase 7 scope)
The home page's incident list is a per-viewer `localStorage` convenience
(`src/lib/recentIncidents.ts`), not backed by a real list endpoint —
deliberately deferred per user direction ("don't expand backend scope just to
make the UI prettier"). Add a real `GET /incidents` endpoint to `backend/`
only when explicitly asked.

## Local commands
```bash
cd dashboard
npm install
npm run dev      # http://localhost:5173, proxies /api -> http://127.0.0.1:8000
npm run build    # tsc -b && vite build
```

## Presentation page (2026-09-21)
`/presentation` = plain-English layer over the same real data (hero, lifecycle,
agent analogy, live pipeline, master switch, 7-question Command Center). Rules:
never show incident data, numbers or activity unless agents are ON and the backend
answered; OFF shows only the data-free `command_center/sevenQuestions.ts`. All
derivations live in `src/lib/presentation.ts` (real events/state -> labels);
`src/api/useActiveIncident.ts` follows one real incident. The demo failure is
`db_slowdown`; `sendCustomerRequests` sends real `GET /orders` traffic through the
narrow `/production` Vite proxy (`vite.config.ts`) because the fault is invisible
without requests. Do not reintroduce a static scenario or hardcoded telemetry.

## Status
Phase 7: **implemented + tested** (typecheck clean, production build clean,
verified against a real live investigation through the full stack — see
`docs/PROJECT_STATE.md`). Phase 8 (Recovery) UI: **implemented** —
`RecoveryPanel` renders the real backend recovery state/events (see above);
verified against a manually-posted realistic event/state sequence through
the real backend (no live LLM call — see docs/PROJECT_STATE.md), not yet
verified against an actual live Groq-driven DIAGNOSED->RESOLVED run.

**2026-09 visual refinement pass** (implemented + build-verified): warm
stone/cream palette replacing the earlier near-white/graphite base, a
purely-decorative slow-drifting ambient color background
(`AmbientBackground.tsx`), 3-density glass material (`GlassSurface`'s
`strong`/default/`light`), a hover "material response" (`interactive` prop)
on click-through glass cards. Fixed two real drift bugs caught while wiring
`RecoveryPanel` to genuine data: `api/types.ts`'s `NexusEventType` union and
`IncidentStatus` still had the old Phase-6-era draft event/status names
(`RECOVERY_PLAN_CREATED`, `SAFETY_CHECK`, etc., and a missing `RESOLVED`
status) instead of the real names `orchestrator/recovery.py` actually emits
— corrected to match source, not the earlier docs draft.

## 2026-10-13
- Live section re-themed LIGHT: `story/LiveBand.module.css` overrides the shared `--nx-*` tokens under `.band`.
- New: `command_center/AgentFlow` (animated flow map; states from real events), `AgentConversation` (requests and
  callbacks from `lib/conversation.ts`), `PlainEnglishBox` (+ `lib/glossary.ts`; words listed only if they appear in the
  incident text), `lib/scenarios.ts` (five failures + blind symptoms), `story/FailuresSection` and `story/FixesSection`.
- Inject flow: `resetShop()` first, then traffic, then inject. Event type `AGENTS_SELECTED` added to `api/types.ts`.

## Recorded runs (2026-10-14) — the one allowed replay
`src/data/recordings/*.json` hold REAL investigations copied unchanged from `backend/.data/nexus.db` after a real benchmark run
(`api/recordings.ts`; header says model, fault, source report). `api/client.ts` serves a recording instead of calling the backend
when the id matches one, and `InvestigationPage` shows the red "Recorded run, not live" banner with Play / Pause / Restart / Show
all. Playback (`lib/replay.ts`) reveals the real events in order; hypotheses, critic verdicts, decision and token totals appear only
when their real events are reached. Rules: never edit a recording's contents, never show one without the banner, never keep one in
the viewer's recent-incidents list. To add one: run a real investigation, then export it from the SQLite store.

