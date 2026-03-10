"""
tier1/test_commit.py — Tests for `mini-git commit`.
"""

from pathlib import Path

import pytest

from conftest import assert_failure, assert_success, make_commit, run_git


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _count_objects(repo: Path) -> int:
    objects_dir = repo / ".git" / "objects"
    count = 0
    for subdir in objects_dir.iterdir():
        if subdir.is_dir() and len(subdir.name) == 2:
            count += sum(1 for f in subdir.iterdir() if f.is_file())
    return count


def _read_head_sha(repo: Path) -> str:
    """Resolve HEAD to a commit SHA (follows symbolic refs one level)."""
    head_text = (repo / ".git" / "HEAD").read_text().strip()
    if head_text.startswith("ref: "):
        ref_path = repo / ".git" / head_text[5:]
        if ref_path.exists():
            return ref_path.read_text().strip()
        return ""
    return head_text


def _log_output(repo: Path) -> str:
    result = run_git("log", cwd=repo)
    return result.stdout + result.stderr


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_commit_creates_commit_object(repo: Path):
    """Commit grows the object store (blob + tree + commit = at least 3 new objects)."""
    before = _count_objects(repo)
    make_commit(repo, "initial commit", {"file.txt": "hello\n"})
    after = _count_objects(repo)
    assert after >= before + 2, (
        f"Expected at least 2 new objects after commit, got {after - before}"
    )


def test_commit_updates_head(repo: Path):
    """After commit, HEAD (via branch ref) points to a non-empty SHA."""
    make_commit(repo, "initial commit", {"a.txt": "a\n"})
    sha = _read_head_sha(repo)
    assert sha and len(sha) == 40, f"HEAD SHA invalid after commit: {sha!r}"


def test_commit_message_stored(repo: Path):
    """log output contains the commit message."""
    make_commit(repo, "my unique message xyz123", {"f.txt": "data\n"})
    log = _log_output(repo)
    assert "my unique message xyz123" in log, f"Message not found in log:\n{log}"


def test_empty_commit_fails(repo: Path):
    """Committing with nothing staged returns non-zero."""
    result = run_git(["commit", "-m", "empty"], cwd=repo)
    assert_failure(result)


def test_commit_output_format(repo: Path):
    """Commit output contains branch name and/or SHA."""
    (repo / "f.txt").write_text("data\n")
    run_git(["add", "f.txt"], cwd=repo)
    result = run_git(["commit", "-m", "test output"], cwd=repo)
    assert_success(result)
    combined = result.stdout + result.stderr
    # Must contain at least a short SHA (7 hex chars) or branch name.
    import re
    has_sha = bool(re.search(r"[0-9a-f]{7,}", combined))
    assert has_sha, f"Commit output does not contain a SHA:\n{combined}"


def test_second_commit_has_parent(repo: Path):
    """The second commit object references the first commit SHA as its parent."""
    make_commit(repo, "first", {"a.txt": "a\n"})
    first_sha = _read_head_sha(repo)

    make_commit(repo, "second", {"b.txt": "b\n"})
    second_sha = _read_head_sha(repo)

    assert first_sha != second_sha, "HEAD did not advance after second commit"

    # Read the second commit object and verify it mentions the first SHA.
    obj_path = repo / ".git" / "objects" / second_sha[:2] / second_sha[2:]
    assert obj_path.exists(), f"Commit object not found at {obj_path}"

    import zlib
    raw = zlib.decompress(obj_path.read_bytes()).decode("utf-8", errors="replace")
    assert first_sha in raw, (
        f"Second commit object does not reference first SHA.\n"
        f"First SHA: {first_sha}\nCommit content:\n{raw}"
    )


def test_commit_advances_branch_ref(repo: Path):
    """Each commit updates the branch ref in .git/refs/heads/."""
    make_commit(repo, "c1", {"x.txt": "x\n"})
    sha1 = _read_head_sha(repo)

    make_commit(repo, "c2", {"y.txt": "y\n"})
    sha2 = _read_head_sha(repo)

    assert sha1 != sha2, "Branch ref did not advance after second commit"
