"""get_git_diff robustness."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_get_diff_survives_non_cp1252_bytes_in_git_output(monkeypatch):
    """Regression: on Windows, text=True decoded git output as cp1252 and a UTF-8 byte
    (e.g. 0x9d inside an em dash) made stdout None, so get_git_diff errored for the agent."""
    import subprocess
    import git_diff_tool

    seen = {}
    real_run = subprocess.run

    def fake_run(cmd, **kwargs):
        seen.update(kwargs)
        return real_run(["git", "--version"], **{**kwargs, "check": False})

    monkeypatch.setattr(git_diff_tool.subprocess, "run", fake_run)
    out = git_diff_tool._run_git(["status"])
    assert seen["encoding"] == "utf-8" and seen["errors"] == "replace"
    assert isinstance(out, str)
