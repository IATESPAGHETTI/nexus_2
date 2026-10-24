import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "critic"))
import prompt_variants as pv  # noqa: E402
from critic_core import INSTRUCTION  # noqa: E402


@pytest.mark.parametrize("variant", pv.VARIANTS)
@pytest.mark.parametrize("agent", ["metrics_agent", "evidence_agent", "root_cause_critic", "recovery_agent"])
def test_every_variant_keeps_the_original_instruction_and_output_contract(monkeypatch, variant, agent):
    monkeypatch.setenv("NEXUS_PROMPT_VARIANT", variant)
    out = pv.apply_variant(INSTRUCTION, agent)
    assert out.startswith(INSTRUCTION)  # contract text is never edited, only extended
    assert "SUPPORTED" in out and "verdict" in out
    assert (out == INSTRUCTION) == (variant == "default")


def test_unknown_variant_falls_back_to_default_and_is_reported(monkeypatch):
    monkeypatch.setenv("NEXUS_PROMPT_VARIANT", "nonsense")
    assert pv.current_variant() == ("default", True)
    assert pv.apply_variant("abc", "x") == "abc"


def test_variants_do_not_name_any_scenario_cause():
    text = " ".join([pv._REACT, *pv._FEWSHOT.values(), *pv._PERSONA.values()]).lower()
    for leak in ("db_slowdown", "bad_deployment", "config_error", "dependency_failure", "resource_exhaustion", "/admin", "inject"):
        assert leak not in text


def test_agent_kind_routing():
    names = ("metrics_agent", "evidence_agent", "root_cause_critic", "recovery_agent")
    assert [pv.agent_kind(n) for n in names] == ["diagnostic", "evidence", "critic", "recovery"]
