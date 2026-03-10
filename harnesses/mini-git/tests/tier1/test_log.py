"""
tier1/test_log.py — Tests for `mini-git log`.
"""

import re
import subprocess
from pathlib import Path

import pytest

from conftest import assert_failure, assert_success, make_commit, run_git


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log(repo: Path, *extra_args) -> subprocess.CompletedProcess:
    return run_git(["log"] + list(extra_args), cwd=repo)


def _log_output(repo: Path, *extra_args) -> str:
    r = run_git(["log"] + list(extra_args), cwd=repo)
    return r.stdout + r.stderr


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_log_empty_repo(repo: Path):
    """log on an empty repo (no commits) shows an appropriate message or exits non-zero."""
    result = run_git("log", cwd=repo)
    combined = (result.stdout + result.stderr).lower()
    # Either exit non-zero, or output must mention "does not have any commits" / "no commits".
    if result.returncode == 0:
        assert (
            "no commit" in combined
            or "does not have any commit" in combined
            or "fatal" in combined
        ), f"Expected empty-repo message from log, got:\n{combined}"


def test_log_single_commit(repo: Path):
    """log with one commit shows the commit hash and message."""
    make_commit(repo, "first commit ever", {"a.txt": "alpha\n"})
    result = run_git("log", cwd=repo)
    assert_success(result)
    out = result.stdout + result.stderr
    assert "first commit ever" in out, f"Commit message missing from log:\n{out}"
    assert re.search(r"[0-9a-f]{7,}", out), f"No SHA found in log:\n{out}"


def test_log_multiple_commits(repo: Path):
    """log shows commits in reverse chronological order (newest first)."""
    make_commit(repo, "commit alpha", {"f1.txt": "1\n"})
    make_commit(repo, "commit beta", {"f2.txt": "2\n"})
    make_commit(repo, "commit gamma", {"f3.txt": "3\n"})

    result = run_git("log", cwd=repo)
    assert_success(result)
    out = result.stdout + result.stderr

    pos_gamma = out.find("commit gamma")
    pos_beta = out.find("commit beta")
    pos_alpha = out.find("commit alpha")

    assert pos_gamma != -1 and pos_beta != -1 and pos_alpha != -1, (
        f"Not all commit messages found in log:\n{out}"
    )
    assert pos_gamma < pos_beta < pos_alpha, (
        "Commits not in reverse chronological order in log output"
    )


def test_log_format(repo: Path):
    """Each log entry contains a hash line and the message."""
    make_commit(repo, "format test commit", {"fmt.txt": "fmt\n"})
    result = run_git("log", cwd=repo)
    assert_success(result)
    out = result.stdout + result.stderr
    # Expect a line starting with "commit " followed by a SHA.
    assert re.search(r"commit\s+[0-9a-f]{40}", out, re.IGNORECASE), (
        f"Expected 'commit <sha>' line in log:\n{out}"
    )
    assert "format test commit" in out


def test_log_shows_all_commits(repo: Path):
    """10 commits → log shows all 10 messages."""
    messages = [f"commit number {i}" for i in range(1, 11)]
    for i, msg in enumerate(messages):
        make_commit(repo, msg, {f"file{i}.txt": f"content {i}\n"})

    result = run_git("log", cwd=repo)
    assert_success(result)
    out = result.stdout + result.stderr

    for msg in messages:
        assert msg in out, f"Message '{msg}' missing from log:\n{out}"


def test_log_n_flag(repo: Path):
    """log -n 2 shows only the 2 most recent commits (if -n is implemented)."""
    make_commit(repo, "oldest commit", {"old.txt": "old\n"})
    make_commit(repo, "middle commit", {"mid.txt": "mid\n"})
    make_commit(repo, "newest commit", {"new.txt": "new\n"})

    result = run_git(["log", "-n", "2"], cwd=repo)
    # If the flag is unrecognised, the implementation may exit non-zero —
    # in that case skip rather than fail.
    if result.returncode != 0:
        pytest.skip("log -n flag not implemented")

    out = result.stdout + result.stderr
    assert "newest commit" in out, f"Newest commit missing from log -n 2:\n{out}"
    assert "middle commit" in out, f"Middle commit missing from log -n 2:\n{out}"
    # The oldest commit should NOT appear.
    assert "oldest commit" not in out, (
        f"log -n 2 showed more than 2 commits:\n{out}"
    )
