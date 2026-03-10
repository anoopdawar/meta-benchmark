"""
tier1/test_init.py — Tests for `mini-git init`.
"""

import os
from pathlib import Path

import pytest

from conftest import assert_failure, assert_success, run_git


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _head_content(repo: Path) -> str:
    return (repo / ".git" / "HEAD").read_text().strip()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_creates_git_dir(tmp_path: Path):
    """init creates a .git/ directory."""
    result = run_git("init", cwd=tmp_path)
    assert_success(result)
    assert (tmp_path / ".git").is_dir(), ".git/ directory was not created"


def test_creates_objects_dir(tmp_path: Path):
    """init creates .git/objects/."""
    run_git("init", cwd=tmp_path)
    assert (tmp_path / ".git" / "objects").is_dir()


def test_creates_refs_dir(tmp_path: Path):
    """init creates .git/refs/heads/."""
    run_git("init", cwd=tmp_path)
    assert (tmp_path / ".git" / "refs" / "heads").is_dir()


def test_creates_head(tmp_path: Path):
    """init creates .git/HEAD pointing to main or master."""
    run_git("init", cwd=tmp_path)
    head = _head_content(tmp_path)
    assert head in (
        "ref: refs/heads/main",
        "ref: refs/heads/master",
    ), f"Unexpected HEAD content: {head!r}"


def test_idempotent(tmp_path: Path):
    """Re-running init in an existing repo does not destroy it."""
    run_git("init", cwd=tmp_path)

    # Write a sentinel file into .git/objects/ to verify it survives reinit.
    sentinel = tmp_path / ".git" / "objects" / "sentinel.txt"
    sentinel.write_text("do not delete")

    result = run_git("init", cwd=tmp_path)
    assert_success(result)
    assert sentinel.exists(), "Re-init destroyed existing .git/objects/ content"

    # HEAD must still be valid.
    head = _head_content(tmp_path)
    assert head.startswith("ref: refs/heads/"), f"HEAD corrupted after re-init: {head!r}"


def test_empty_repo_status(tmp_path: Path):
    """status in a freshly initialised repo mentions 'nothing to commit'."""
    run_git("init", cwd=tmp_path)
    result = run_git("status", cwd=tmp_path)
    # Either success or non-zero is acceptable for an empty repo, but the
    # combined output must convey "nothing to commit".
    combined = (result.stdout + result.stderr).lower()
    assert (
        "nothing to commit" in combined
        or "no commits yet" in combined
        or "empty" in combined
    ), f"Expected empty-repo message, got:\n{combined}"


def test_init_output_contains_path(tmp_path: Path):
    """init output mentions the absolute path of the new .git directory."""
    result = run_git("init", cwd=tmp_path)
    assert_success(result)
    combined = result.stdout + result.stderr
    # The spec mandates output like: Initialized empty Git repository in <path>/.git/
    assert ".git" in combined, f"Expected path in init output, got:\n{combined}"
