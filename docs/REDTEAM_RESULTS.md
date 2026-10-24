# Red-team results for the input and tool-output guards (requirement 8)

Run: `python tests/redteam_report.py`; regression: `pytest tests/test_redteam.py` (209 checks). Corpus: `tests/redteam_corpus.py`
(92 in-scope attacks, 14 hard attacks, 20 abuse cases, 79 benign cases, 30 hold-out attacks).

## What was measured

| Group | Result | Meaning |
|---|---|---|
| In-scope attacks (92: override, leak, role, delimiter, tool hijack, exfiltration, 9 languages, leetspeak, look-alike letters, zero-width, spaced letters, base64, rot13, URL, HTML, hex, attacks hidden in logs) | 92 / 92 blocked | The guard was tuned on these, so this is a regression number, not an independent estimate. |
| **Hold-out attacks, FIRST pass (30, written after tuning, never used to tune)** | **21 / 30 (70%)** | **This is the honest estimate for unseen attacks.** Misses were synonyms ("stop following your earlier rules", "nullify", "skip the guidelines"), "hidden instructions", "disclose the API key", and a German article. |
| Hold-out after generalising the patterns | 30 / 30 | No longer independent: the misses were used to improve the patterns. A fresh unseen set is needed for a new honest number. |
| Hard attacks (14: paraphrase, indirect, social-engineering, other-language phrasing with no shared wording) | 0 / 14 caught, by design | These are the known limit. |
| Abusive text (20: plain, leetspeak, spaced, zero-width, look-alike letters, 5 languages) | 20 / 20 blocked | Same caveat: tuned on these. |
| Benign text (79: real symptoms, log lines, deployment notes, scary-looking words, look-alikes, 5 languages) | 0 false positives | Includes first-pass benign hold-out (20/20 passed before any tuning). |
| Real evidence from 135 stored investigations | 0 blocked, 0 items redacted, slowest scan 112 ms | No false positives on genuine tool output. |
| Large payloads | 60 KB scanned well under 2 s | Normalisation is capped at the first 20 KB. |

## How it works (so the limits are clear)
- Patterns are grouped in categories (override, leak, role, delimiter, tool_hijack, exfil) and run against several normalised forms of
  the text: Unicode compatibility form, zero-width characters removed, look-alike letters mapped, leetspeak, split-up letters,
  URL / HTML / hex / base64 / rot13 decodings.
- A user description that matches is rejected before any model sees it. Tool output (logs, traces, deployment notes) that matches is
  redacted in place and flagged, so evidence numbers stay exact and the model is told the text was not an instruction.
- Text that only matches after decoding is withheld whole for single values; large composite payloads are flagged but not blanked.

## What this does NOT give you
- No semantic understanding: a paraphrase that shares no wording with the catalogue passes (0/14 on the hard set).
- It is a blocklist; attackers can keep trying. Do not describe the system as "secure against prompt injection".
- The protection that does not depend on detection: read-only MCP tools, a Recovery Agent with no tools, an allowlist re-validated by the
  guardrails code, human approval, per-incident token limits, a password on the dashboard.
- A model-based classifier would catch more paraphrases but costs tokens on every input; not added.
