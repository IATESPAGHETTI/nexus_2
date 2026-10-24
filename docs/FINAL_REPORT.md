# NEXUS: Autonomous Multi-Agent Production Failure Investigation and Recovery

Team (submission): Deepu, Mukund, Vanshika. Implementation, testing and evaluation: Deepu.
Draft for the end-term report. Every number below comes from a stored run file or a test; where something is not verified, it says so.

## 1. Problem and approach
When a production service degrades, an engineer reads metrics, logs, traces and recent deployments and decides a cause. NEXUS automates that with a team of agents on a **simulated shop** (safe to break): a fault is injected, specialist agents gather evidence through MCP tools, an Evidence agent forms hypotheses, a Critic challenges them, and a Recovery agent proposes a bounded fix that **only a human can approve**. The system may abstain when the evidence is weak.

## 2. Architecture
- **Agents.** Incident Manager (client), Metrics, Logs/Traces, Change Analysis, Database, Evidence, Critic and Recovery. Seven independent A2A services (ports 8101-8107). Google ADK for the specialists and Recovery; **CrewAI** (real Agent + Task + Crew) can run the Evidence and Critic roles. Both frameworks are used; no third agent framework.
- **Communication.** Real A2A over HTTP between processes. One W3C trace id crosses every process. Three messaging topologies are implemented and compared: hub-and-spoke, shared **blackboard**, and a sequential **pipeline** where the Metrics finding is handed to the other agents.
- **Tools.** Two MCP servers over stdio: the diagnostic server (7 tools) and an analysis server (`search_runbook`, `evaluate_expression`, `detect_latency_step`).
- **Structured output.** Pydantic models (Finding, Hypothesis, Critique, RecoveryPlan, IncidentReport). Reports download as Markdown or JSON with summary, hypotheses, agents and evidence tables.
- **Monitoring and tracing.** Callbacks record every model and tool call (`AgentMonitor`); traces export as OTLP (seen in a real Jaeger); the incident page shows a timeline, the blackboard entries and the evidence lineage.
- **Safety.** Input and tool-output screening (pattern-based, 9 languages), read-only tools, a tool-less Recovery agent, an action allowlist, human approval, kill switch, spend limits.
- **Deployment.** Docker Compose behind Caddy (HTTPS) and a password, on an Azure for Students VM; GitHub Actions run the tests.

## 3. Evaluation
**Method.** A runner executes arms x scenarios x repeats against the live system, scores the final statement against the injected cause (ground truth is never shown to the agents), and records accuracy, false diagnoses, abstentions, healthy-control behaviour, time, tokens and estimated cost. Runs with provider errors are retried and, if still failing, excluded and counted.

**Run A: DeepSeek `deepseek-chat`, 144 runs** (8 arms, 6 scenarios, 3 repeats; `EVALUATION_RESULTS_2026-10-16.md`).
Single-agent baseline 87%; hub (shipped system) 80%; hub without critic 100%; blackboard 67%; few-shot prompt 40%. The critic's accuracy cost was not statistically significant (p = 0.16). Cost was about $0.004 per investigation.

**Run B: held-out, Gemini `gemini-3.5-flash-lite`, 126 valid runs** (7 arms, 9 scenarios never used for tuning, 2 repeats; `EVALUATION_RESULTS_HOLDOUT.md`).
Single-agent baseline 94%; multi-agent arms 62-75%. Hardest cases for multi-agent: a reworded database slowdown and a deployment-plus-database double fault. Four multi-agent arms named a fault on the healthy shop in 1 of 2 runs.

**Pooled view across both models (simple mean of the two runs; 18 runs per arm per model, only arms that were run on both).**
Different models and different scenarios, so this is a summary of the two experiments, not a third experiment.

| Arm | DeepSeek | Gemini | Mean accuracy | Mean tokens/run | Mean time/run |
|---|---|---|---|---|---|
| Single-agent baseline | 87% | 94% | **90.5%** | 2,696 | 1.9 s |
| Hub (shipped system) | 80% | 75% | **77.5%** | 27,019 | 14.9 s |
| Hub without critic | 100% | 69% | **84.5%** | 19,967 | 9.9 s |
| Blackboard | 67% | 62% | **64.5%** | 29,931 | 16.3 s |

The pattern is the same on both models: the baseline is the most accurate and about a tenth of the cost. The no-critic arm swings from first to near last between the two models, which shows how much of these differences is noise.

**Reading the results honestly.**
1. On these simulated faults one evidence snapshot is enough, so one model call matches or beats the multi-agent system on accuracy, at about a sixth of the tokens. This held on two different models.
2. Differences among the multi-agent variants (topology, critic, extra tools, CrewAI) are within noise at 18 runs per arm. We do not claim any of them is better.
3. What the multi-agent design adds is not accuracy: it is an auditable trail (who ran when, what evidence supports each claim), mandatory human approval for recovery, abstention, and framework interoperability.
4. Models differ between the two runs and must not be mixed.

## 4. Requirement coverage
See `REQUIREMENTS_EVIDENCE.md` for the table (where each of the 11 requirements lives, how to check it, and its limits). Test counts on 2026-10-19: 316 backend/root, 47 evaluation, 57 MCP, 8 CrewAI, plus agent and orchestrator suites (live-agent tests pass when the agents run).

## 5. Limitations
- CrewAI -> ADK needed a fix: ADK 2.9 serves A2A 1.0 agent cards that CrewAI's pinned a2a-sdk 0.3 rejects. ADK's services now add the three 0.3 fields to the card (`agents/common/legacy_card.py`), and CrewAI's own delegation function completed a task against an ADK agent. What was NOT shown: a CrewAI agent choosing to delegate on its own, because the small Gemini model wrote the agent name instead of the URL in CrewAI's structured field (a model quirk, not the protocol).
- The guardrail is a heuristic: 21/30 first-pass detection on unseen attacks; 14 hard paraphrases are missed by design. The real protection is structural.
- Faults are simulated and easy to read; real production would be harder. Recovery success was not measured.
- Small samples, one provider per run, free-tier limits; held-out scenarios were run once.
- Azure scripts (redeploy, backup, health check) and Approve-to-recovery on the cloud site are written but not yet rehearsed on the VM.

## 6. Future work
A CrewAI agent that delegates to ADK on its own with a stronger model; harder, real-incident datasets; tuning the false-alarm rate on a healthy shop; measuring recovery success.
