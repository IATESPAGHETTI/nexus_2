import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
import board_io as b  # noqa: E402


def _msg(role="diagnose", iid="INC-0a1b2c3d", **extra):
    return json.dumps({"nexus_board": {"incident_id": iid, "role": role, **extra}})


def test_pointer_parsing_accepts_valid_and_rejects_everything_else():
    assert b.parse_board_message(_msg()) == {"incident_id": "INC-0a1b2c3d", "role": "diagnose"}
    for bad in ("", "plain text", "{}", '{"nexus_board": 1}', _msg(iid="../../etc"), _msg(iid="INC-"), _msg(role="rm -rf"), "{not json"):
        assert b.parse_board_message(bad) is None


def test_backend_address_never_comes_from_the_message(monkeypatch):
    monkeypatch.setenv("NEXUS_BACKEND_URL", "http://127.0.0.1:8000/")
    assert b.parse_board_message(_msg(backend_url="http://evil.example")) == {"incident_id": "INC-0a1b2c3d", "role": "diagnose"}
    assert b.backend_url() == "http://127.0.0.1:8000"


ENTRIES = [
    {"entry_id": "bb-1", "type": "description", "author": "incident_manager", "content": {"text": "orders are slow"}},
    {"entry_id": "bb-2", "type": "request", "author": "incident_manager", "content": {"text": "orders are slow", "targets": ["metrics_agent", "database_agent"]}},
    {"entry_id": "bb-3", "type": "finding", "author": "metrics_agent", "content": {"finding_id": "f1", "evidence": [{"evidence_id": "ev-1"}]}},
    {"entry_id": "bb-4", "type": "finding", "author": "database_agent", "content": {"finding_id": "f2", "evidence": [{"evidence_id": "ev-2"}]}},
    {"entry_id": "bb-5", "type": "request", "author": "incident_manager", "content": {"text": "look at traces", "targets": ["metrics_agent"]}},
    {"entry_id": "bb-6", "type": "finding", "author": "metrics_agent", "content": {"finding_id": "f3", "evidence": [{"evidence_id": "ev-3"}]}},
    {"entry_id": "bb-7", "type": "review_request", "author": "incident_manager", "content": {"hypothesis": {"hypothesis_id": "H1"}}},
]


def test_diagnose_reads_the_latest_request_addressed_to_me_else_the_description():
    assert b.build_question("diagnose", ENTRIES, "metrics_agent") == "look at traces"
    assert b.build_question("diagnose", ENTRIES, "database_agent") == "orders are slow"
    assert b.build_question("diagnose", ENTRIES[:1], "logs_traces_agent") == "orders are slow"


def test_synthesize_uses_the_latest_finding_per_author_exactly_like_the_hub_path():
    findings = json.loads(b.build_question("synthesize", ENTRIES, "evidence_agent"))
    assert set(findings) == {"metrics_agent", "database_agent"} and findings["metrics_agent"]["finding_id"] == "f3"


def test_review_combines_the_requested_hypothesis_with_all_current_evidence():
    payload = json.loads(b.build_question("review", ENTRIES, "root_cause_critic"))
    assert payload["hypothesis"] == {"hypothesis_id": "H1"}
    assert [e["evidence_id"] for e in payload["evidence_pool"]] == ["ev-3", "ev-2"]
