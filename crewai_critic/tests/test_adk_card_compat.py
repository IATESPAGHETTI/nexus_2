"""CrewAI's pinned a2a-sdk (0.3.x) must be able to read an ADK (A2A 1.0) agent card once LegacyCardMiddleware is in front of it."""
import json
import sys
from pathlib import Path

from a2a.types import AgentCard
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agents" / "common"))
from legacy_card import CARD_PATH, LegacyCardMiddleware, add_legacy_fields  # noqa: E402

ADK_1_0_CARD = {
    "name": "metrics_agent", "description": "d", "version": "0.0.1",
    "supportedInterfaces": [{"url": "http://127.0.0.1:8101", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}],
    "capabilities": {"streaming": True}, "defaultInputModes": ["text/plain"], "defaultOutputModes": ["text/plain"],
    "skills": [{"id": "s", "name": "n", "description": "d", "tags": ["llm"]}],
}


def _client() -> TestClient:
    app = Starlette(routes=[Route(CARD_PATH, lambda r: JSONResponse(ADK_1_0_CARD)), Route("/other", lambda r: JSONResponse({"a": 1}))])
    app.add_middleware(LegacyCardMiddleware)
    return TestClient(app)


def test_raw_adk_card_is_rejected_by_a2a_0_3():
    try:
        AgentCard.model_validate(ADK_1_0_CARD)
    except Exception:  # noqa: BLE001
        return
    raise AssertionError("the 0.3 parser now accepts raw 1.0 cards: this compatibility layer may no longer be needed")


def test_patched_card_parses_in_a2a_0_3_and_keeps_the_1_0_fields():
    body = _client().get(CARD_PATH).json()
    card = AgentCard.model_validate(body)
    assert card.url == "http://127.0.0.1:8101" and card.protocol_version == "0.3.0"
    assert body["supportedInterfaces"] == ADK_1_0_CARD["supportedInterfaces"]


def test_other_paths_and_existing_fields_are_untouched():
    assert _client().get("/other").json() == {"a": 1}
    card = dict(ADK_1_0_CARD, url="http://elsewhere")
    assert add_legacy_fields(card)["url"] == "http://elsewhere"
    assert add_legacy_fields({"name": "x"}) == {"name": "x"}
