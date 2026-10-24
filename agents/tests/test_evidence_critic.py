"""Fast unit tests (Phase 6) for the Evidence Agent's and Root-Cause Critic's
Python-side structural enforcement -- pure functions, no network, no LLM call.

These prove the evidence-first guarantee holds even when the model's raw JSON
output tries to invent evidence or return a garbled verdict: `build_hypotheses`
and `build_critique` are the only code allowed to assign ids / trust a verdict,
mirroring how `agents/common/finding.py`'s `build_finding` is the only code
allowed to build `observation` for a diagnostic agent's Finding.

Run with the isolated agents venv:
    .venv-agents/Scripts/python -m pytest agents/tests/test_evidence_critic.py -q
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evidence"))

from agent import build_hypotheses as build_hypotheses_evidence  # noqa: E402
from reasoning_agent import extract_json  # noqa: E402

# agents/critic/agent.py is ALSO a module literally named "agent.py" -- loading
# it via sys.path + `import agent` would collide with (and, depending on
# import-cache order, silently shadow) agents/evidence/agent.py above. Load it
# by explicit file path under its own module name instead.
import importlib  # noqa: E402

_critic_spec = importlib.util.spec_from_file_location(
    "critic_agent_module", str(Path(__file__).resolve().parents[1] / "critic" / "agent.py")
)
critic_agent_module = importlib.util.module_from_spec(_critic_spec)
_critic_spec.loader.exec_module(critic_agent_module)
build_critique = critic_agent_module.build_critique


SAMPLE_FINDINGS = {
    "metrics_agent": {
        "finding_id": "find-aaa",
        "agent": "metrics_agent",
        "evidence": [
            {"evidence_id": "ev-1", "tool": "get_metrics", "arguments": {}, "result": {"ok": True}},
        ],
    },
    "database_agent": {
        "finding_id": "find-bbb",
        "agent": "database_agent",
        "evidence": [
            {"evidence_id": "ev-2", "tool": "get_database_stats", "arguments": {}, "result": {"ok": True}},
        ],
    },
}


def test_extract_json_parses_fenced_block():
    text = 'Here you go:\n```json\n{"a": 1, "b": [1, 2]}\n```\nThanks.'
    assert extract_json(text) == {"a": 1, "b": [1, 2]}


def test_extract_json_parses_plain_array():
    text = '[{"statement": "x", "confidence": 0.5}]'
    assert extract_json(text) == [{"statement": "x", "confidence": 0.5}]


def test_extract_json_returns_none_for_unparseable_text():
    assert extract_json("I am not JSON at all.") is None


def test_extract_json_returns_none_for_empty_text():
    assert extract_json("") is None
    assert extract_json(None) is None


def test_build_hypotheses_keeps_real_evidence_ids():
    raw = [
        {
            "statement": "Database is slow",
            "supporting_evidence_ids": ["ev-2"],
            "contradicting_evidence_ids": [],
            "confidence": 0.8,
            "missing_evidence": [],
            "requested_next_investigation": None,
        }
    ]
    hypotheses = build_hypotheses_evidence(SAMPLE_FINDINGS, raw)
    assert len(hypotheses) == 1
    h = hypotheses[0]
    assert h["hypothesis_id"] == "H1"
    assert h["supporting_evidence_ids"] == ["ev-2"]
    assert h["status"] == "PROPOSED"
    assert h["dropped_invented_evidence_ids"] == 0


def test_build_hypotheses_drops_invented_evidence_ids():
    raw = [
        {
            "statement": "Deployment broke checkout",
            "supporting_evidence_ids": ["ev-2", "ev-does-not-exist"],
            "contradicting_evidence_ids": ["ev-also-fake"],
            "confidence": 1.5,  # out of range, must be clamped
            "missing_evidence": ["needs trace correlation"],
        }
    ]
    hypotheses = build_hypotheses_evidence(SAMPLE_FINDINGS, raw)
    h = hypotheses[0]
    assert h["supporting_evidence_ids"] == ["ev-2"]
    assert h["contradicting_evidence_ids"] == []
    assert h["dropped_invented_evidence_ids"] == 2
    assert h["confidence"] == 1.0  # clamped, not trusted verbatim


def test_build_hypotheses_ignores_non_list_model_output():
    assert build_hypotheses_evidence(SAMPLE_FINDINGS, {"not": "a list"}) == []
    assert build_hypotheses_evidence(SAMPLE_FINDINGS, None) == []


def test_build_hypotheses_flags_hypothesis_with_no_real_evidence_at_all():
    raw = [{"statement": "Pure speculation", "confidence": 0.9}]
    hypotheses = build_hypotheses_evidence(SAMPLE_FINDINGS, raw)
    assert "no real evidence_id" in hypotheses[0]["missing_evidence"][0]


def test_build_hypotheses_sorted_by_confidence_descending():
    raw = [
        {"statement": "low", "confidence": 0.2, "supporting_evidence_ids": ["ev-1"]},
        {"statement": "high", "confidence": 0.9, "supporting_evidence_ids": ["ev-2"]},
    ]
    hypotheses = build_hypotheses_evidence(SAMPLE_FINDINGS, raw)
    assert [h["statement"] for h in hypotheses] == ["high", "low"]


SAMPLE_HYPOTHESIS = {"hypothesis_id": "H1", "statement": "Database is slow"}
SAMPLE_EVIDENCE_POOL = [{"evidence_id": "ev-2", "tool": "get_database_stats"}]


def test_build_critique_accepts_valid_verdict():
    raw = {
        "verdict": "SUPPORTED",
        "contradictions": [],
        "unsupported_assumptions": [],
        "alternative_explanations": [],
        "requested_evidence": [],
        "rationale": "evidence backs it up",
    }
    critique = build_critique(SAMPLE_HYPOTHESIS, SAMPLE_EVIDENCE_POOL, raw)
    assert critique["verdict"] == "SUPPORTED"
    assert critique["hypothesis_id"] == "H1"
    assert critique["evidence_pool_size"] == 1
    assert critique["critique_id"].startswith("crit-")


def test_build_critique_falls_back_on_invalid_verdict():
    raw = {"verdict": "TOTALLY_SURE", "rationale": "vibes"}
    critique = build_critique(SAMPLE_HYPOTHESIS, SAMPLE_EVIDENCE_POOL, raw)
    assert critique["verdict"] == "INSUFFICIENT_EVIDENCE"
    assert "did not return a recognized verdict" in critique["rationale"]


def test_build_critique_falls_back_when_model_output_unparseable():
    critique = build_critique(SAMPLE_HYPOTHESIS, SAMPLE_EVIDENCE_POOL, None)
    assert critique["verdict"] == "INSUFFICIENT_EVIDENCE"


def test_build_critique_coerces_non_list_fields_to_empty_lists():
    raw = {"verdict": "CONTRADICTED", "contradictions": "not a list", "rationale": "r"}
    critique = build_critique(SAMPLE_HYPOTHESIS, SAMPLE_EVIDENCE_POOL, raw)
    assert critique["contradictions"] == []
    assert critique["verdict"] == "CONTRADICTED"


def test_build_hypotheses_accepts_wrapped_and_bare_shapes_but_not_garbage():
    from agent import build_hypotheses  # noqa: E402  (agents/evidence/agent.py, on sys.path in this module)
    item = {"statement": "slow queries", "confidence": 0.7, "supporting_evidence_ids": []}
    assert len(build_hypotheses({}, [item])) == 1
    assert len(build_hypotheses({}, {"hypotheses": [item]})) == 1      # wrapped in an object
    assert len(build_hypotheses({}, item)) == 1                         # one bare object
    assert build_hypotheses({}, {"note": "no list here"}) == []
    assert build_hypotheses({}, "just prose") == [] and build_hypotheses({}, None) == []
