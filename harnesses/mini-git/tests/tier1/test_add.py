"""
tier1/test_add.py — Tests for `mini-git add`.
"""

from pathlib import Path

import pytest

from conftest import assert_failure, assert_success, make_commit, run_git


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _count_objects(repo: Path) -> int:
    """Count the number of loose objects currently in .git/objects/."""
    objects_dir = repo / ".git" / "objects"
    count = 0
    for subdir in objects_dir.iterdir():
        if subdir.is_dir() and len(subdir.name) == 2:
            count += sum(1 for f in subdir.iterdir() if f.is_file())
    return count


def _status_output(repo: Path) -> str:
    result = run_git("status", cwd=repo)
    return (result.stdout + result.stderr).lower()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_add_single_file(repo: Path):
    """add a single file; status shows it as staged."""
    (repo / "hello.txt").write_text("hello world\n")
    result = run_git(["add", "hello.txt"], cwd=repo)
    assert_success(result)
    status = _status_output(repo)
    assert "hello.txt" in status, f"Staged file not in status:\n{status}"


def test_add_multiple_files(repo: Path):
    """add multiple files at once; all appear as staged."""
    (repo / "a.txt").write_text("aaa")
    (repo / "b.txt").write_text("bbb")
    result = run_git(["add", "a.txt", "b.txt"], cwd=repo)
    assert_success(result)
    status = _status_output(repo)
    assert "a.txt" in status
    assert "b.txt" in status


def test_add_directory(repo: Path):
    """`git add .` stages all files in the working tree."""
    (repo / "x.txt").write_text("x")
    (repo / "y.txt").write_text("y")
    result = run_git(["add", "."], cwd=repo)
    assert_success(result)
    status = _status_output(repo)
    assert "x.txt" in status
    assert "y.txt" in status


def test_add_creates_blob(repo: Path):
    """A blob object appears in .git/objects/ after add."""
    before = _count_objects(repo)
    (repo / "file.txt").write_text("some content\n")
    run_git(["add", "file.txt"], cwd=repo)
    after = _count_objects(repo)
    assert after > before, "No new objects in .git/objects/ after add"


def test_add_nonexistent_file(repo: Path):
    """add a non-existent file returns non-zero exit code."""
    result = run_git(["add", "no_such_file.txt"], cwd=repo)
    assert_failure(result)


def test_add_modified_file(repo: Path):
    """add a file, modify it, add again — staged version reflects latest content."""
    f = repo / "mod.txt"
    f.write_text("version 1\n")
    run_git(["add", "mod.txt"], cwd=repo)

    f.write_text("version 2\n")
    result = run_git(["add", "mod.txt"], cwd=repo)
    assert_success(result)

    # Commit and verify the committed content is version 2.
    run_git(["commit", "-m", "test mod"], cwd=repo)
    # After commit, file should be clean (no unstaged changes).
    status = _status_output(repo)
    assert "nothing to commit" in status or "mod.txt" not in status.split("untracked")[0]


def test_unstaged_after_add(repo: Path):
    """A file that has not been modified after add shows no unstaged changes."""
    (repo / "stable.txt").write_text("stable\n")
    run_git(["add", "stable.txt"], cwd=repo)
    status_raw = run_git("status", cwd=repo)
    out = (status_raw.stdout + status_raw.stderr).lower()
    # "Changes not staged for commit" section must NOT mention stable.txt.
    not_staged_section = ""
    if "changes not staged" in out:
        not_staged_section = out.split("changes not staged")[1]
    assert "stable.txt" not in not_staged_section, (
        "stable.txt appeared in unstaged section after clean add"
    )


def test_add_empty_file(repo: Path):
    """add an empty file succeeds and creates a blob."""
    (repo / "empty.txt").write_text("")
    result = run_git(["add", "empty.txt"], cwd=repo)
    assert_success(result)
    status = _status_output(repo)
    assert "empty.txt" in status
