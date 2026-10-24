"""Evidence Agent hypotheses carry a validated structured fault_class (used for fair scoring)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agents" / "evidence"))
sys.path.insert(0, str(ROOT / "agents" / "common"))

import agent as evidence  # noqa: E402

FINDINGS = {"metrics_agent": {"evidence": [{"evidence_id": "E1"}]}}


def _build(**over):
    item = {"statement": "s", "supporting_evidence_ids": ["E1"], "confidence": 0.8, **over}
    return evidence.build_hypotheses(FINDINGS, [item])[0]


def test_valid_class_kept():
    assert _build(fault_class="config_error")["fault_class"] == "config_error"


def test_invalid_or_missing_class_becomes_none():
    assert _build(fault_class="the database")["fault_class"] == "none"
    assert _build()["fault_class"] == "none"


def test_vocabulary_matches_production_fault_types():
    src = (ROOT / "production" / "state.py").read_text(encoding="utf-8")
    for name in evidence.FAULT_CLASSES:
        assert f'"{name}"' in src
