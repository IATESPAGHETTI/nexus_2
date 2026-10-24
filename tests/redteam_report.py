"""Prints the red-team numbers used in docs/REDTEAM_RESULTS.md:  python tests/redteam_report.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import nexus_guard as g
import redteam_corpus as c


def blocked(t):
    return not g.screen_user_text(t, max_chars=10**6, check_abuse=False).allowed


groups = {}
for kind, text in c.ATTACKS:
    groups.setdefault(kind.split(":")[0], []).append(blocked(text))
print("in-scope attacks by category (caught/total):")
for k, v in sorted(groups.items()):
    print(f"  {k:14s} {sum(v)}/{len(v)}")
print(f"in-scope total {sum(blocked(t) for _, t in c.ATTACKS)}/{len(c.ATTACKS)}")
print(f"hold-out (now tuned on) {sum(blocked(t) for _, t in c.HOLDOUT_ATTACKS)}/{len(c.HOLDOUT_ATTACKS)}")
print(f"hard (expected misses) caught {sum(bool(g.injection_categories(t)) for _, t in c.HARD_ATTACKS)}/{len(c.HARD_ATTACKS)}")
print(f"abuse caught {sum(not g.screen_user_text(t, max_chars=10**6).allowed for _, t in c.ABUSE)}/{len(c.ABUSE)}")
fp = sum(not g.screen_user_text(t, max_chars=10**6).allowed for t in c.BENIGN + c.HOLDOUT_BENIGN)
print(f"benign false positives {fp}/{len(c.BENIGN) + len(c.HOLDOUT_BENIGN)}")
