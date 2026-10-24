"""Red-team regression for nexus_guard. See docs/REDTEAM_RESULTS.md for what the numbers do and do not mean."""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import nexus_guard as g  # noqa: E402
import redteam_corpus as c  # noqa: E402


def _blocked(text):
    return not g.screen_user_text(text, max_chars=10**6, check_abuse=False).allowed


@pytest.mark.parametrize("category,text", c.ATTACKS, ids=[f"{k}-{i}" for i, (k, _) in enumerate(c.ATTACKS)])
def test_in_scope_attacks_are_blocked_in_user_text(category, text):
    assert _blocked(text), (category, ascii(text[:100]))


@pytest.mark.parametrize("category,text", c.ATTACKS, ids=[f"{k}-{i}" for i, (k, _) in enumerate(c.ATTACKS)])
def test_in_scope_attacks_never_reach_the_model_unredacted_in_tool_output(category, text):
    safe, flags = g.guard_tool_result({"ok": True, "line": text})
    assert flags, (category, ascii(text[:100]))
    assert safe["line"] != text


def test_holdout_attacks_after_generalisation():
    """These 30 cases were written after tuning. FIRST-PASS result was 21/30 (70%); the patterns were then generalised
    using these cases, so this number is no longer independent evidence (docs/REDTEAM_RESULTS.md)."""
    missed = [ascii(t[:70]) for _, t in c.HOLDOUT_ATTACKS if not _blocked(t)]
    assert len(missed) <= 3, missed


def test_no_false_positives_on_benign_text():
    wrong = [ascii(t[:80]) for t in c.BENIGN + c.HOLDOUT_BENIGN if not g.screen_user_text(t, max_chars=10**6).allowed]
    assert wrong == []


def test_benign_text_is_not_altered_in_tool_output():
    for text in c.BENIGN + c.HOLDOUT_BENIGN:
        safe, flags = g.guard_tool_result({"ok": True, "line": text})
        assert "instruction_like_text_redacted" not in flags and "obfuscated_instruction_redacted" not in flags, ascii(text[:80])


@pytest.mark.parametrize("kind,text", c.ABUSE, ids=[f"{k}-{i}" for i, (k, _) in enumerate(c.ABUSE)])
def test_abuse_is_blocked(kind, text):
    assert not g.screen_user_text(text, max_chars=10**6).allowed


def test_the_hard_group_documents_known_limits():
    """Paraphrases with no shared wording are NOT detected. Keeping them in the corpus keeps the limit visible; if the
    guard ever catches them the report should be updated, not this assertion silently weakened."""
    assert len(c.HARD_ATTACKS) >= 10
    caught = [t for _, t in c.HARD_ATTACKS if g.injection_categories(t)]
    assert len(caught) <= len(c.HARD_ATTACKS) // 2


def test_scanning_a_large_payload_stays_fast():
    payload = ("GET /orders 200 3.2ms trace_id=fcf43499b1784c3b " * 600)[:60000]
    start = time.perf_counter()
    g.screen_user_text(payload, max_chars=10**6)
    g.guard_tool_result({"ok": True, "log": payload[:3900]})
    assert time.perf_counter() - start < 2.0
