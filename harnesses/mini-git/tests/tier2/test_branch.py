"""
tier2/test_branch.py — Tests for `mini-git branch`.
"""

from pathlib import Path

import pytest

from conftest import assert_failure, assert_success, make_commit, run_git


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _branch_output(repo: Path) -> str:
    result = run_git("branch", cwd=repo)
    return result.stdout + result.stderr


def _current_branch(repo: Path) -> str:
    head = (repo / ".git" / "HEAD").read_text().strip()
    if head.startswith("ref: refs/heads/"):
        return head[len("ref: refs/heads/"):]
    return head  # detached


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_create_branch(repo: Path):
    """git branch <name> creates a new branch."""
    make_commit(repo, "initial", {"a.txt": "a\n"})
    result = run_git(["branch", "feature"], cwd=repo)
    assert_success(result)

    # Branch ref file must exist.
    ref = repo / ".git" / "refs" / "heads" / "feature"
    assert ref.exists(), f".git/refs/heads/feature not created"


def test_list_branches(repo: Path):
    """git branch lists branches and marks the current one with *."""
    make_commit(repo, "initial", {"a.txt": "a\n"})
    run_git(["branch", "other"], cwd=repo)

    out = _branch_output(repo)
    assert "other" in out, f"'other' branch not listed:\n{out}"
    assert "*" in out, f"Current branch marker '*' missing:\n{out}"


def test_delete_branch(repo: Path):
    """git branch -d <name> removes the branch."""
    make_commit(repo, "initial", {"a.txt": "a\n"})
    run_git(["branch", "to_delete"], cwd=repo)

    result = run_git(["branch", "-d", "to_delete"], cwd=repo)
    assert_success(result)

    ref = repo / ".git" / "refs" / "heads" / "to_delete"
    assert not ref.exists(), "Branch ref still exists after deletion"


def test_delete_current_branch_fails(repo: Path):
    """Deleting the currently checked-out branch returns non-zero."""
    make_commit(repo, "initial", {"a.txt": "a\n"})
    current = _current_branch(repo)
    result = run_git(["branch", "-d", current], cwd=repo)
    assert_failure(result)


def test_branch_ref_created(repo: Path):
    """After branch creation, .git/refs/heads/<name> exists with a valid SHA."""
    make_commit(repo, "initial", {"a.txt": "a\n"})
    run_git(["branch", "myfeature"], cwd=repo)

    ref_path = repo / ".git" / "refs" / "heads" / "myfeature"
    assert ref_path.exists()

    sha = ref_path.read_text().strip()
    assert len(sha) == 40, f"Branch ref does not contain a 40-char SHA: {sha!r}"


def test_branch_points_to_current_commit(repo: Path):
    """A newly created branch points to the same commit as HEAD."""
    make_commit(repo, "initial", {"a.txt": "a\n"})

    head_text = (repo / ".git" / "HEAD").read_text().strip()
    if head_text.startswith("ref: "):
        current_sha = (repo / ".git" / head_text[5:]).read_text().strip()
    else:
        current_sha = head_text

    run_git(["branch", "snapshot"], cwd=repo)
    branch_sha = (repo / ".git" / "refs" / "heads" / "snapshot").read_text().strip()
    assert branch_sha == current_sha, (
        f"New branch SHA {branch_sha!r} != HEAD SHA {current_sha!r}"
    )


def test_delete_nonexistent_branch_fails(repo: Path):
    """Deleting a branch that doesn't exist returns non-zero."""
    make_commit(repo, "initial", {"a.txt": "a\n"})
    result = run_git(["branch", "-d", "no_such_branch"], cwd=repo)
    assert_failure(result)
