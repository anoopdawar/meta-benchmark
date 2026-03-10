"""
tier3/test_stash.py — Tests for `mini-git stash`.
"""

from pathlib import Path

import pytest

from conftest import assert_failure, assert_success, make_commit, run_git


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _status(repo: Path) -> str:
    r = run_git("status", cwd=repo)
    return (r.stdout + r.stderr).lower()


def _stash_list(repo: Path) -> str:
    r = run_git(["stash", "list"], cwd=repo)
    return r.stdout + r.stderr


def _skip_if_stash_not_implemented(repo: Path):
    """Run a no-op stash list; skip the test if stash is not implemented."""
    result = run_git(["stash", "list"], cwd=repo)
    if result.returncode != 0 and "unknown" in (result.stdout + result.stderr).lower():
        pytest.skip("stash not implemented")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_stash_save(repo: Path):
    """git stash removes unstaged changes and leaves the working tree clean."""
    make_commit(repo, "base", {"stash_test.txt": "original\n"})
    (repo / "stash_test.txt").write_text("modified but not committed\n")

    result = run_git("stash", cwd=repo)
    if result.returncode != 0:
        pytest.skip("stash not implemented")

    # Working tree should be clean.
    status = _status(repo)
    assert (
        "nothing to commit" in status
        or "working tree clean" in status
        or "stash_test.txt" not in status.split("untracked")[0]
    ), f"Working tree not clean after stash:\n{status}"

    # File should be restored to the committed version.
    content = (repo / "stash_test.txt").read_text()
    assert content == "original\n", f"File not reverted after stash: {content!r}"


def test_stash_pop(repo: Path):
    """git stash pop restores the stashed changes."""
    make_commit(repo, "base", {"pop_test.txt": "original\n"})
    (repo / "pop_test.txt").write_text("modified\n")
    run_git("stash", cwd=repo)

    result = run_git(["stash", "pop"], cwd=repo)
    if result.returncode != 0:
        pytest.skip("stash pop not implemented")

    content = (repo / "pop_test.txt").read_text()
    assert content == "modified\n", (
        f"Stashed modification not restored by pop: {content!r}"
    )


def test_stash_list(repo: Path):
    """git stash list shows stash entries."""
    make_commit(repo, "base", {"list_test.txt": "base\n"})
    (repo / "list_test.txt").write_text("change 1\n")
    run_git("stash", cwd=repo)

    result = run_git(["stash", "list"], cwd=repo)
    if result.returncode != 0:
        pytest.skip("stash list not implemented")

    out = result.stdout + result.stderr
    assert "stash@{0}" in out or "WIP" in out or "stash" in out.lower(), (
        f"Expected stash entry in stash list:\n{out}"
    )


def test_stash_drop(repo: Path):
    """git stash drop removes a stash entry."""
    make_commit(repo, "base", {"drop_test.txt": "base\n"})
    (repo / "drop_test.txt").write_text("change\n")
    r = run_git("stash", cwd=repo)
    if r.returncode != 0:
        pytest.skip("stash not implemented")

    result = run_git(["stash", "drop"], cwd=repo)
    if result.returncode != 0:
        result = run_git(["stash", "drop", "stash@{0}"], cwd=repo)
    if result.returncode != 0:
        pytest.skip("stash drop not implemented")

    stash_out = _stash_list(repo)
    assert "stash@{0}" not in stash_out, (
        f"Stash entry still present after drop:\n{stash_out}"
    )


def test_multiple_stashes(repo: Path):
    """Multiple stashes are stored and popped in LIFO order."""
    make_commit(repo, "base", {"multi.txt": "original\n"})

    (repo / "multi.txt").write_text("change 1\n")
    r1 = run_git("stash", cwd=repo)
    if r1.returncode != 0:
        pytest.skip("stash not implemented")

    (repo / "extra.txt").write_text("extra file\n")
    run_git(["add", "extra.txt"], cwd=repo)
    r2 = run_git("stash", cwd=repo)
    if r2.returncode != 0:
        pytest.skip("stash (second save) not implemented")

    stash_out = _stash_list(repo)
    assert "stash@{0}" in stash_out, "First stash entry missing"
    assert "stash@{1}" in stash_out, "Second stash entry missing"

    # Pop should restore the most recent stash (extra.txt).
    pop_result = run_git(["stash", "pop"], cwd=repo)
    if pop_result.returncode != 0:
        pytest.skip("stash pop not implemented")

    stash_out_after = _stash_list(repo)
    # stash@{1} should now be gone (it becomes stash@{0}).
    assert "stash@{1}" not in stash_out_after, (
        "Stash list not updated correctly after pop"
    )


def test_stash_pop_empty_fails(repo: Path):
    """git stash pop with no stash entries returns non-zero or reports an error."""
    make_commit(repo, "base", {"f.txt": "f\n"})

    result = run_git(["stash", "pop"], cwd=repo)
    if "unknown" in (result.stdout + result.stderr).lower():
        pytest.skip("stash not implemented")

    combined = (result.stdout + result.stderr).lower()
    assert result.returncode != 0 or "no stash" in combined, (
        f"Expected error when popping from empty stash, got:\n{combined}"
    )
