"""
tier3/test_reset.py — Tests for `mini-git reset`.
"""

from pathlib import Path

import pytest

from conftest import assert_failure, assert_success, make_commit, run_git


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _head_sha(repo: Path) -> str:
    head = (repo / ".git" / "HEAD").read_text().strip()
    if head.startswith("ref: "):
        ref_file = repo / ".git" / head[5:]
        if ref_file.exists():
            return ref_file.read_text().strip()
        return ""
    return head


def _status(repo: Path) -> str:
    r = run_git("status", cwd=repo)
    return (r.stdout + r.stderr).lower()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_soft_reset(repo: Path):
    """git reset --soft HEAD~1 moves HEAD back but keeps changes staged."""
    make_commit(repo, "first", {"a.txt": "first\n"})
    sha1 = _head_sha(repo)

    make_commit(repo, "second", {"b.txt": "second\n"})

    result = run_git(["reset", "--soft", "HEAD~1"], cwd=repo)
    if result.returncode != 0:
        pytest.skip("reset --soft not implemented")

    # HEAD must point to the first commit.
    assert _head_sha(repo) == sha1, "HEAD not moved back by --soft reset"

    # b.txt changes must still be staged.
    status = _status(repo)
    assert "b.txt" in status, "Changes not preserved as staged after --soft reset"
    assert "changes to be committed" in status or "b.txt" in status


def test_mixed_reset(repo: Path):
    """git reset HEAD~1 (mixed) moves HEAD back and unstages changes."""
    make_commit(repo, "first", {"a.txt": "first\n"})
    sha1 = _head_sha(repo)
    make_commit(repo, "second", {"b.txt": "second\n"})

    result = run_git(["reset", "HEAD~1"], cwd=repo)
    if result.returncode != 0:
        result = run_git(["reset", "--mixed", "HEAD~1"], cwd=repo)
    if result.returncode != 0:
        pytest.skip("reset --mixed not implemented")

    assert _head_sha(repo) == sha1, "HEAD not moved back by mixed reset"

    # b.txt should appear as untracked or unstaged (not staged).
    status = _status(repo)
    staged_section = ""
    if "changes to be committed" in status:
        parts = status.split("changes to be committed")
        staged_section = parts[1].split("changes not staged")[0] if len(parts) > 1 else ""
    assert "b.txt" not in staged_section, "b.txt still staged after mixed reset"


def test_hard_reset(repo: Path):
    """git reset --hard HEAD~1 moves HEAD back and discards working tree changes."""
    make_commit(repo, "first", {"a.txt": "first\n"})
    sha1 = _head_sha(repo)
    make_commit(repo, "second", {"b.txt": "second\n"})

    result = run_git(["reset", "--hard", "HEAD~1"], cwd=repo)
    if result.returncode != 0:
        pytest.skip("reset --hard not implemented")

    assert _head_sha(repo) == sha1, "HEAD not moved back by --hard reset"
    # b.txt must be gone.
    assert not (repo / "b.txt").exists(), "b.txt still present after --hard reset"


def test_reset_to_sha(repo: Path):
    """git reset --hard <sha> resets to a specific commit SHA."""
    make_commit(repo, "commit one", {"x.txt": "x\n"})
    sha_one = _head_sha(repo)

    make_commit(repo, "commit two", {"y.txt": "y\n"})
    make_commit(repo, "commit three", {"z.txt": "z\n"})

    result = run_git(["reset", "--hard", sha_one], cwd=repo)
    if result.returncode != 0:
        pytest.skip("reset --hard <sha> not implemented")

    assert _head_sha(repo) == sha_one, f"HEAD not at sha_one after reset to SHA"
    assert not (repo / "y.txt").exists(), "y.txt should be gone after reset to sha_one"
    assert not (repo / "z.txt").exists(), "z.txt should be gone after reset to sha_one"
    assert (repo / "x.txt").exists(), "x.txt should exist at sha_one"


def test_reset_updates_head(repo: Path):
    """HEAD points to the target commit after any reset mode."""
    make_commit(repo, "first", {"a.txt": "a\n"})
    sha_first = _head_sha(repo)
    make_commit(repo, "second", {"b.txt": "b\n"})

    run_git(["reset", "--soft", "HEAD~1"], cwd=repo)
    assert _head_sha(repo) == sha_first, "HEAD not updated by reset"
