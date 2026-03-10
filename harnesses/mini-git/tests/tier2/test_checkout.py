"""
tier2/test_checkout.py — Tests for `mini-git checkout`.
"""

from pathlib import Path

import pytest

from conftest import assert_failure, assert_success, make_commit, run_git


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _current_branch(repo: Path) -> str:
    head = (repo / ".git" / "HEAD").read_text().strip()
    if head.startswith("ref: refs/heads/"):
        return head[len("ref: refs/heads/"):]
    return head


def _head_sha(repo: Path) -> str:
    head = (repo / ".git" / "HEAD").read_text().strip()
    if head.startswith("ref: "):
        ref_file = repo / ".git" / head[5:]
        if ref_file.exists():
            return ref_file.read_text().strip()
        return ""
    return head


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_checkout_branch(repo: Path):
    """git checkout <branch> switches HEAD to the target branch."""
    make_commit(repo, "initial", {"a.txt": "a\n"})
    run_git(["branch", "feature"], cwd=repo)

    result = run_git(["checkout", "feature"], cwd=repo)
    assert_success(result)
    assert _current_branch(repo) == "feature", (
        f"HEAD not pointing to 'feature' after checkout: {_current_branch(repo)!r}"
    )


def test_checkout_restores_files(repo: Path):
    """Checking out a branch restores that branch's files in the working tree."""
    # On main: create file_main.txt.
    make_commit(repo, "main commit", {"file_main.txt": "main content\n"})

    # Create and switch to feature; add feature-only file.
    run_git(["branch", "feature"], cwd=repo)
    run_git(["checkout", "feature"], cwd=repo)
    make_commit(repo, "feature commit", {"file_feature.txt": "feature content\n"})

    # Switch back to main.
    result = run_git(["checkout", "main"], cwd=repo)
    if result.returncode != 0:
        result = run_git(["checkout", "master"], cwd=repo)
    assert_success(result)

    # file_main.txt should be present; file_feature.txt should be absent.
    assert (repo / "file_main.txt").exists(), "file_main.txt missing after checkout to main"
    assert not (repo / "file_feature.txt").exists(), (
        "file_feature.txt present on main branch after checkout"
    )


def test_checkout_b_flag(repo: Path):
    """git checkout -b <name> creates a new branch and switches to it."""
    make_commit(repo, "initial", {"a.txt": "a\n"})
    result = run_git(["checkout", "-b", "new_branch"], cwd=repo)
    assert_success(result)
    assert _current_branch(repo) == "new_branch", (
        f"Not on new_branch after checkout -b: {_current_branch(repo)!r}"
    )
    assert (repo / ".git" / "refs" / "heads" / "new_branch").exists()


def test_checkout_nonexistent_fails(repo: Path):
    """git checkout of a non-existent branch returns non-zero."""
    make_commit(repo, "initial", {"a.txt": "a\n"})
    result = run_git(["checkout", "no_such_branch"], cwd=repo)
    assert_failure(result)


def test_checkout_updates_working_tree(repo: Path):
    """Files unique to each branch appear/disappear correctly after checkout."""
    make_commit(repo, "base", {"shared.txt": "shared\n"})

    # Create branchA with branchA_only.txt.
    run_git(["checkout", "-b", "branchA"], cwd=repo)
    make_commit(repo, "A commit", {"branchA_only.txt": "only on A\n"})

    # Go back to main and verify.
    main_branch = "main"
    r = run_git(["checkout", main_branch], cwd=repo)
    if r.returncode != 0:
        main_branch = "master"
        r = run_git(["checkout", main_branch], cwd=repo)
    assert_success(r)

    assert not (repo / "branchA_only.txt").exists(), (
        "branchA_only.txt should not exist on main"
    )

    # Go back to branchA.
    run_git(["checkout", "branchA"], cwd=repo)
    assert (repo / "branchA_only.txt").exists(), (
        "branchA_only.txt should exist on branchA"
    )
