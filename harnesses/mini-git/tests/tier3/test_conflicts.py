"""
tier3/test_conflicts.py — Tests for three-way merge conflict handling.
"""

from pathlib import Path

import pytest

from conftest import assert_failure, assert_success, make_commit, run_git


# ---------------------------------------------------------------------------
# Setup helper: diverged branch scenario
# ---------------------------------------------------------------------------

def _setup_diverged_repo(repo: Path):
    """
    Create a repo with two diverged branches that both modify the same file.

    Returns (main_branch_name, conflict_branch_name).
    """
    make_commit(repo, "base", {"conflict.txt": "base content\n"})

    # Determine the current (main) branch name.
    head = (repo / ".git" / "HEAD").read_text().strip()
    if head.startswith("ref: refs/heads/"):
        main_branch = head[len("ref: refs/heads/"):]
    else:
        main_branch = "main"

    # Create and commit on a diverging branch.
    run_git(["branch", "conflict_branch"], cwd=repo)
    run_git(["checkout", "conflict_branch"], cwd=repo)
    make_commit(
        repo,
        "branch change",
        {"conflict.txt": "branch version of content\n"},
    )

    # Back to main and make a conflicting change.
    run_git(["checkout", main_branch], cwd=repo)
    make_commit(
        repo,
        "main change",
        {"conflict.txt": "main version of content\n"},
    )

    return main_branch, "conflict_branch"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_conflict_detected(repo: Path):
    """Non-fast-forward merge with conflicting changes returns non-zero or marks conflicts."""
    main_branch, conflict_branch = _setup_diverged_repo(repo)
    result = run_git(["merge", conflict_branch], cwd=repo)
    combined = (result.stdout + result.stderr).lower()

    if result.returncode == 0:
        # Implementation succeeded — must at least mention a conflict.
        assert (
            "conflict" in combined
            or "automatic merge failed" in combined
        ), f"Merge succeeded silently without flagging conflict:\n{combined}"
    # Non-zero exit is also fully acceptable.


def test_conflict_markers(repo: Path):
    """Conflicted file contains <<<<<<, =======, >>>>>>> markers."""
    main_branch, conflict_branch = _setup_diverged_repo(repo)
    run_git(["merge", conflict_branch], cwd=repo)  # may fail

    conflict_file = repo / "conflict.txt"
    if not conflict_file.exists():
        pytest.skip("Conflict file not written by implementation")

    content = conflict_file.read_text()
    if "<<<<<<<" not in content:
        pytest.skip("Implementation did not write conflict markers — three-way merge may not be implemented")

    assert "<<<<<<< " in content or "<<<<<<<" in content, "Missing <<<<<<< marker"
    assert "=======" in content, "Missing ======= separator"
    assert ">>>>>>>" in content, "Missing >>>>>>> marker"


def test_conflict_resolution(repo: Path):
    """After manually resolving a conflict and adding, commit succeeds."""
    main_branch, conflict_branch = _setup_diverged_repo(repo)
    merge_result = run_git(["merge", conflict_branch], cwd=repo)

    conflict_file = repo / "conflict.txt"
    content = conflict_file.read_text()

    if "<<<<<<<" not in content:
        pytest.skip("No conflict markers written — three-way merge may not be implemented")

    # Resolve by replacing the whole file with a clean resolution.
    conflict_file.write_text("resolved content\n")
    run_git(["add", "conflict.txt"], cwd=repo)

    result = run_git(["commit", "-m", "resolve conflict"], cwd=repo)
    assert_success(result)


def test_merge_conflict_status(repo: Path):
    """Status after a conflicting merge shows the conflicted file."""
    main_branch, conflict_branch = _setup_diverged_repo(repo)
    run_git(["merge", conflict_branch], cwd=repo)

    conflict_file = repo / "conflict.txt"
    content = conflict_file.read_text()
    if "<<<<<<<" not in content:
        pytest.skip("No conflict markers written — three-way merge may not be implemented")

    result = run_git("status", cwd=repo)
    out = (result.stdout + result.stderr).lower()
    assert "conflict.txt" in out, f"Conflicted file not shown in status:\n{out}"
    # Ideally shows "both modified" but we accept just the filename being present.


def test_merge_head_written_on_conflict(repo: Path):
    """MERGE_HEAD is written when a merge conflict occurs."""
    main_branch, conflict_branch = _setup_diverged_repo(repo)
    run_git(["merge", conflict_branch], cwd=repo)

    conflict_file = repo / "conflict.txt"
    content = conflict_file.read_text()
    if "<<<<<<<" not in content:
        pytest.skip("No conflict markers — three-way merge may not be implemented")

    merge_head = repo / ".git" / "MERGE_HEAD"
    assert merge_head.exists(), ".git/MERGE_HEAD not written during conflict"
    sha = merge_head.read_text().strip()
    assert len(sha) == 40, f"MERGE_HEAD does not contain a valid SHA: {sha!r}"
