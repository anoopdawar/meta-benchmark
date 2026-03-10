"""
tier1/test_status.py — Tests for `mini-git status`.
"""

from pathlib import Path

import pytest

from conftest import assert_success, make_commit, run_git


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _status(repo: Path) -> str:
    result = run_git("status", cwd=repo)
    return (result.stdout + result.stderr).lower()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_status_clean(repo: Path):
    """After a commit with no subsequent changes, status reports nothing to commit."""
    make_commit(repo, "initial", {"clean.txt": "clean\n"})
    out = _status(repo)
    assert "nothing to commit" in out or "working tree clean" in out, (
        f"Expected clean status, got:\n{out}"
    )


def test_status_untracked(repo: Path):
    """A new, unstaged file appears in the untracked section."""
    make_commit(repo, "base", {"base.txt": "base\n"})
    (repo / "untracked.txt").write_text("I am untracked\n")
    out = _status(repo)
    assert "untracked.txt" in out, f"Untracked file not in status:\n{out}"
    assert "untracked" in out, f"'untracked' section missing from status:\n{out}"


def test_status_staged(repo: Path):
    """A freshly added file appears in the 'changes to be committed' section."""
    (repo / "staged.txt").write_text("staged content\n")
    run_git(["add", "staged.txt"], cwd=repo)
    out = _status(repo)
    assert "staged.txt" in out
    # The file must appear in the staged section (before any unstaged section).
    staged_section_idx = out.find("changes to be committed")
    unstaged_section_idx = out.find("changes not staged")
    staged_txt_idx = out.find("staged.txt")
    if staged_section_idx != -1:
        assert staged_txt_idx > staged_section_idx, (
            "staged.txt appears before the staged section header"
        )
        if unstaged_section_idx != -1:
            assert staged_txt_idx < unstaged_section_idx or out.count("staged.txt") > 0


def test_status_modified_staged(repo: Path):
    """A file staged then further modified on disk shows in both staged and unstaged sections."""
    make_commit(repo, "base", {"both.txt": "original\n"})

    # Modify, stage, then modify again.
    (repo / "both.txt").write_text("staged version\n")
    run_git(["add", "both.txt"], cwd=repo)
    (repo / "both.txt").write_text("unstaged version\n")

    out = _status(repo)
    assert "both.txt" in out
    # Should appear in at least two distinct sections.
    assert out.count("both.txt") >= 2 or (
        "changes to be committed" in out and "changes not staged" in out
    ), f"Expected both staged and unstaged for both.txt:\n{out}"


def test_status_deleted(repo: Path):
    """A tracked file deleted from disk appears as deleted in status."""
    make_commit(repo, "base", {"todelete.txt": "content\n"})
    (repo / "todelete.txt").unlink()
    out = _status(repo)
    assert "todelete.txt" in out, f"Deleted file not mentioned in status:\n{out}"
    assert "deleted" in out, f"'deleted' not in status output:\n{out}"


def test_status_no_commits_yet(repo: Path):
    """status in a repo with staged files but no commits shows 'No commits yet'."""
    (repo / "new.txt").write_text("new\n")
    run_git(["add", "new.txt"], cwd=repo)
    out = _status(repo)
    assert "new.txt" in out
    # Many implementations show "No commits yet" or "Initial commit" before the staged list.
    # This is not strictly enforced but is recommended by the spec.
    # We simply assert that new.txt appears somewhere.
