"""
tier2/test_merge.py — Tests for `mini-git merge` (fast-forward path).
"""

from pathlib import Path

import pytest

from conftest import assert_success, make_commit, run_git


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


def _current_branch(repo: Path) -> str:
    head = (repo / ".git" / "HEAD").read_text().strip()
    if head.startswith("ref: refs/heads/"):
        return head[len("ref: refs/heads/"):]
    return head


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_fast_forward_merge(repo: Path):
    """Main behind feature → merge fast-forwards main to feature tip."""
    make_commit(repo, "base", {"base.txt": "base\n"})

    # Record feature tip SHA before merge.
    run_git(["branch", "feature"], cwd=repo)
    run_git(["checkout", "feature"], cwd=repo)
    make_commit(repo, "feature work", {"feat.txt": "feat\n"})
    feature_sha = _head_sha(repo)

    # Switch back to main and merge.
    main = _current_branch(repo)
    for branch in ("main", "master"):
        r = run_git(["checkout", branch], cwd=repo)
        if r.returncode == 0:
            main = branch
            break

    result = run_git(["merge", "feature"], cwd=repo)
    assert_success(result)

    merged_sha = _head_sha(repo)
    assert merged_sha == feature_sha, (
        f"After fast-forward merge, HEAD {merged_sha!r} != feature tip {feature_sha!r}"
    )


def test_fast_forward_no_conflicts(repo: Path):
    """After fast-forward merge, the feature branch's file is present."""
    make_commit(repo, "base", {"base.txt": "base\n"})
    run_git(["branch", "ff"], cwd=repo)
    run_git(["checkout", "ff"], cwd=repo)
    make_commit(repo, "ff work", {"ff_file.txt": "from ff\n"})

    for branch in ("main", "master"):
        r = run_git(["checkout", branch], cwd=repo)
        if r.returncode == 0:
            break

    run_git(["merge", "ff"], cwd=repo)
    assert (repo / "ff_file.txt").exists(), "Merged file not present in working tree"
    assert (repo / "ff_file.txt").read_text() == "from ff\n"


def test_merge_already_up_to_date(repo: Path):
    """Merging a branch that is already an ancestor is a no-op."""
    make_commit(repo, "base", {"a.txt": "a\n"})
    run_git(["branch", "old_branch"], cwd=repo)

    # Advance main further.
    make_commit(repo, "ahead", {"b.txt": "b\n"})
    sha_before = _head_sha(repo)

    # Merge old_branch — it is behind main, so should be "already up to date".
    result = run_git(["merge", "old_branch"], cwd=repo)
    combined = (result.stdout + result.stderr).lower()
    # Either success with "already up to date" or success with no change.
    if result.returncode == 0:
        assert (
            "already up to date" in combined
            or _head_sha(repo) == sha_before
        ), f"Expected 'already up to date', got:\n{combined}"


def test_merge_message_fast_forward(repo: Path):
    """Merge output mentions 'fast-forward' or 'fast forward'."""
    make_commit(repo, "base", {"a.txt": "a\n"})
    run_git(["branch", "fwd"], cwd=repo)
    run_git(["checkout", "fwd"], cwd=repo)
    make_commit(repo, "fwd commit", {"fwd.txt": "fwd\n"})

    for branch in ("main", "master"):
        r = run_git(["checkout", branch], cwd=repo)
        if r.returncode == 0:
            break

    result = run_git(["merge", "fwd"], cwd=repo)
    assert_success(result)
    combined = (result.stdout + result.stderr).lower()
    assert "fast" in combined, f"Expected fast-forward mention in merge output:\n{combined}"
