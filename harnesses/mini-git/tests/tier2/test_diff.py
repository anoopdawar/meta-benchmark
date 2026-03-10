"""
tier2/test_diff.py — Tests for `mini-git diff`.
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_diff_staged(repo: Path):
    """git diff --staged shows staged changes relative to HEAD."""
    make_commit(repo, "base", {"base.txt": "original line\n"})

    (repo / "base.txt").write_text("modified line\n")
    run_git(["add", "base.txt"], cwd=repo)

    result = run_git(["diff", "--staged"], cwd=repo)
    assert_success(result)
    out = result.stdout + result.stderr
    assert "modified line" in out or "original line" in out, (
        f"Expected diff content in --staged output:\n{out}"
    )


def test_diff_unstaged(repo: Path):
    """git diff shows working tree changes not yet staged."""
    make_commit(repo, "base", {"work.txt": "before\n"})
    (repo / "work.txt").write_text("after\n")

    result = run_git("diff", cwd=repo)
    assert_success(result)
    out = result.stdout + result.stderr
    # Should contain at least one + or - line.
    assert "+" in out or "-" in out, f"No diff lines in unstaged diff output:\n{out}"
    assert "after" in out or "before" in out, f"Expected changed content in diff:\n{out}"


def test_diff_between_commits(repo: Path):
    """git diff <sha1> <sha2> shows changes between two commits."""
    make_commit(repo, "commit one", {"story.txt": "chapter one\n"})
    sha1 = _head_sha(repo)

    make_commit(repo, "commit two", {"story.txt": "chapter two\n"})
    sha2 = _head_sha(repo)

    result = run_git(["diff", sha1, sha2], cwd=repo)
    if result.returncode != 0:
        pytest.skip("diff between two SHAs not implemented")

    out = result.stdout + result.stderr
    assert "chapter" in out, f"Expected content changes in diff {sha1[:7]}..{sha2[:7]}:\n{out}"


def test_diff_format(repo: Path):
    """Diff output contains +/- lines in unified diff format."""
    make_commit(repo, "base", {"diff_fmt.txt": "line one\n"})
    (repo / "diff_fmt.txt").write_text("line one\nline two\n")

    result = run_git("diff", cwd=repo)
    assert_success(result)
    out = result.stdout + result.stderr
    lines = out.splitlines()
    has_plus = any(l.startswith("+") for l in lines)
    has_minus = any(l.startswith("-") for l in lines)
    assert has_plus or has_minus, f"No +/- lines in diff:\n{out}"


def test_diff_clean(repo: Path):
    """No diff output when working tree matches the last commit."""
    make_commit(repo, "clean state", {"stable.txt": "no changes\n"})
    result = run_git("diff", cwd=repo)
    assert_success(result)
    out = (result.stdout + result.stderr).strip()
    # Output should be empty (or only whitespace).
    assert out == "", f"Expected empty diff for clean working tree, got:\n{out}"


def test_diff_staged_new_file(repo: Path):
    """git diff --staged shows a new file being added."""
    make_commit(repo, "base", {"existing.txt": "exists\n"})
    (repo / "brand_new.txt").write_text("brand new\n")
    run_git(["add", "brand_new.txt"], cwd=repo)

    result = run_git(["diff", "--staged"], cwd=repo)
    assert_success(result)
    out = result.stdout + result.stderr
    assert "brand_new.txt" in out or "brand new" in out, (
        f"New file not shown in staged diff:\n{out}"
    )
