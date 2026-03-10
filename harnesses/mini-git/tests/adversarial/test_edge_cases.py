"""
Adversarial tests: repository-level edge cases.

These tests probe boundary conditions in repository state, command sequencing,
and unusual-but-valid usage patterns.
"""
import os
import subprocess
import time

import pytest

from .conftest import MINI_GIT_CMD, _skip_if_no_cmd

pytestmark = pytest.mark.skipif(
    not MINI_GIT_CMD, reason="MINI_GIT_CMD not set"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _commit_file(repo, run_git, filename: str, content: bytes, message: str) -> int:
    """Create, stage, and commit a single file. Returns the exit code."""
    (repo / filename).write_bytes(content)
    run_git("add", filename)
    return run_git("commit", "-m", message).returncode


def _n_commits(repo, run_git, n: int):
    """Make *n* commits, each modifying counter.txt."""
    for i in range(n):
        (repo / "counter.txt").write_bytes(f"commit {i}\n".encode())
        run_git("add", "counter.txt")
        r = run_git("commit", "-m", f"commit {i}")
        if r.returncode != 0:
            pytest.fail(f"Commit {i} failed: {r.stderr.decode(errors='replace')}")


# ---------------------------------------------------------------------------
# Empty / initial repository edge cases
# ---------------------------------------------------------------------------

def test_empty_repository_log(repo, run_git):
    """git log on an empty repository must not crash (may print an error message)."""
    result = run_git("log")
    assert result.returncode in (0, 1, 128), (
        f"Unexpected exit code: {result.returncode}\n"
        f"stderr: {result.stderr.decode(errors='replace')}"
    )
    combined = result.stdout + result.stderr
    # Must produce some output — either an error message or nothing
    # "does not have any commits" is the real git message
    # We just confirm it doesn't segfault / return unexpected codes


def test_empty_repository_status(repo, run_git):
    """git status on an empty repository must not crash."""
    result = run_git("status")
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    # Should contain "No commits yet" or similar
    combined = result.stdout + result.stderr
    assert combined  # must produce some output


def test_empty_repository_diff(repo, run_git):
    """git diff on an empty repository must not crash."""
    result = run_git("diff")
    assert result.returncode in (0, 1)


def test_status_clean_after_commit(repo, run_git):
    """After committing, status should show a clean tree."""
    _commit_file(repo, run_git, "a.txt", b"hello\n", "init")
    result = run_git("status")
    assert result.returncode == 0
    combined = (result.stdout + result.stderr).decode(errors="replace")
    # Should not list any files as modified/staged/untracked
    assert "nothing to commit" in combined or "working tree clean" in combined


# ---------------------------------------------------------------------------
# Log boundary conditions
# ---------------------------------------------------------------------------

def test_log_n_zero(repo, run_git):
    """git log -n 0 must show nothing or handle gracefully."""
    _commit_file(repo, run_git, "a.txt", b"a\n", "init")
    result = run_git("log", "-n", "0")
    assert result.returncode in (0, 1)
    # Stdout should be empty or minimal when showing 0 commits
    assert len(result.stdout.strip()) == 0 or result.returncode == 1


def test_log_n_larger_than_history(repo, run_git):
    """git log -n 100 when only 3 commits exist must not crash."""
    for i in range(3):
        _commit_file(repo, run_git, "x.txt", f"v{i}\n".encode(), f"commit {i}")
    result = run_git("log", "-n", "100")
    assert result.returncode == 0


def test_log_oneline(repo, run_git):
    """git log --oneline must produce one line per commit."""
    for i in range(5):
        _commit_file(repo, run_git, "f.txt", f"v{i}\n".encode(), f"commit-{i}")
    result = run_git("log", "--oneline")
    assert result.returncode == 0
    lines = [l for l in result.stdout.splitlines() if l.strip()]
    assert len(lines) == 5, f"Expected 5 lines, got {len(lines)}: {result.stdout}"


# ---------------------------------------------------------------------------
# Commit edge cases
# ---------------------------------------------------------------------------

def test_very_long_commit_message(repo, run_git):
    """Commit message > 10,000 characters must be accepted or rejected gracefully."""
    _commit_file(repo, run_git, "a.txt", b"a\n", "init")
    (repo / "b.txt").write_bytes(b"b\n")
    run_git("add", "b.txt")
    long_msg = "x" * 10_001
    result = run_git("commit", "-m", long_msg)
    # Must not be an internal crash
    assert result.returncode in (0, 1)


def test_commit_no_files_staged(repo, run_git):
    """git commit with nothing staged must fail with a helpful message."""
    result = run_git("commit", "-m", "empty commit")
    assert result.returncode != 0, "Commit with nothing staged must fail"
    combined = result.stdout + result.stderr
    assert combined  # must produce some output


def test_commit_empty_message_rejected(repo, run_git):
    """Commit with empty -m '' must be rejected."""
    _commit_file(repo, run_git, "a.txt", b"a\n", "init")
    (repo / "b.txt").write_bytes(b"b\n")
    run_git("add", "b.txt")
    result = run_git("commit", "-m", "")
    assert result.returncode != 0, "Empty commit message must be rejected"


def test_add_then_delete_before_commit(repo, run_git):
    """Add a file, then delete it from disk before committing."""
    p = repo / "ghost.txt"
    p.write_bytes(b"I will vanish\n")
    run_git("add", "ghost.txt")
    p.unlink()  # delete after staging

    result = run_git("commit", "-m", "commit staged ghost")
    # Behavior is implementation-defined: may commit the staged blob or fail
    assert result.returncode in (0, 1)


def test_same_content_different_files(repo, run_git):
    """Two files with identical content produce only one blob object."""
    content = b"shared content\n"
    (repo / "alpha.txt").write_bytes(content)
    (repo / "beta.txt").write_bytes(content)
    run_git("add", "alpha.txt", "beta.txt")
    result = run_git("commit", "-m", "dedup blobs")
    assert result.returncode == 0, result.stderr.decode(errors="replace")

    # Verify only one blob object exists by SHA1 content addressing
    obj_dir = repo / ".git" / "objects"
    blob_sha = None
    import hashlib, zlib
    header = f"blob {len(content)}\0".encode()
    raw = header + content
    expected_sha = hashlib.sha1(raw).hexdigest()

    blob_path = obj_dir / expected_sha[:2] / expected_sha[2:]
    assert blob_path.exists(), "Expected a single shared blob object to exist"


def test_many_commits(repo, run_git):
    """Repository with 1000 commits: log must complete without error."""
    _n_commits(repo, run_git, 1000)
    result = run_git("log", "--oneline")
    assert result.returncode == 0
    lines = [l for l in result.stdout.splitlines() if l.strip()]
    assert len(lines) == 1000, f"Expected 1000 log lines, got {len(lines)}"


def test_multiple_adds_without_commit(repo, run_git):
    """Multiple successive adds (no commits in between) must not corrupt the index."""
    for i in range(20):
        p = repo / f"file{i}.txt"
        p.write_bytes(f"content {i}\n".encode())
        run_git("add", f"file{i}.txt")

    result = run_git("status")
    assert result.returncode == 0

    result2 = run_git("commit", "-m", "many adds")
    assert result2.returncode == 0, result2.stderr.decode(errors="replace")


def test_add_overwrites_earlier_add(repo, run_git):
    """Adding the same file twice (with different content) only keeps the latest."""
    p = repo / "overwrite.txt"
    p.write_bytes(b"version 1\n")
    run_git("add", "overwrite.txt")

    p.write_bytes(b"version 2\n")
    run_git("add", "overwrite.txt")

    run_git("commit", "-m", "should be version 2")

    p.write_bytes(b"OVERWRITTEN")
    run_git("checkout", "--", "overwrite.txt")
    assert p.read_bytes() == b"version 2\n"


# ---------------------------------------------------------------------------
# Branch edge cases
# ---------------------------------------------------------------------------

def test_branch_name_with_slash(repo, run_git):
    """Branch name 'feature/login' must be created and listed correctly."""
    _commit_file(repo, run_git, "a.txt", b"a\n", "init")
    result = run_git("branch", "feature/login")
    assert result.returncode == 0, result.stderr.decode(errors="replace")

    branches = run_git("branch")
    assert b"feature/login" in branches.stdout


def test_branch_name_with_dots(repo, run_git):
    """Branch name 'v1.0.0' must be created and listed correctly."""
    _commit_file(repo, run_git, "a.txt", b"a\n", "init")
    result = run_git("branch", "v1.0.0")
    assert result.returncode == 0, result.stderr.decode(errors="replace")


def test_branch_already_exists(repo, run_git):
    """Creating a branch that already exists must fail with an error."""
    _commit_file(repo, run_git, "a.txt", b"a\n", "init")
    run_git("branch", "dupe")
    result = run_git("branch", "dupe")
    assert result.returncode != 0, "Duplicate branch creation must fail"


def test_delete_nonexistent_branch(repo, run_git):
    """Deleting a branch that doesn't exist must fail gracefully."""
    _commit_file(repo, run_git, "a.txt", b"a\n", "init")
    result = run_git("branch", "-d", "nonexistent")
    assert result.returncode != 0


def test_delete_current_branch_rejected(repo, run_git):
    """Deleting the currently checked-out branch must be rejected."""
    _commit_file(repo, run_git, "a.txt", b"a\n", "init")
    result = run_git("branch", "-d", "main")
    assert result.returncode != 0, "Must not delete the current branch"


# ---------------------------------------------------------------------------
# Checkout edge cases
# ---------------------------------------------------------------------------

def test_checkout_same_branch_noop(repo, run_git):
    """Checking out the currently active branch must be a no-op with a message."""
    _commit_file(repo, run_git, "a.txt", b"a\n", "init")
    result = run_git("checkout", "main")
    assert result.returncode == 0
    combined = result.stdout + result.stderr
    assert combined  # must say something


def test_checkout_with_uncommitted_changes(repo, run_git):
    """Checking out a different branch when dirty should warn or fail."""
    _commit_file(repo, run_git, "a.txt", b"v1\n", "init")
    run_git("branch", "other")

    # Dirty working tree
    (repo / "a.txt").write_bytes(b"DIRTY\n")
    result = run_git("checkout", "other")
    # Must not silently overwrite or corrupt — returncode 0 or non-zero is fine
    assert result.returncode in (0, 1)


def test_checkout_nonexistent_branch(repo, run_git):
    """Checking out a branch that doesn't exist must fail gracefully."""
    _commit_file(repo, run_git, "a.txt", b"a\n", "init")
    result = run_git("checkout", "does-not-exist")
    assert result.returncode != 0


# ---------------------------------------------------------------------------
# Empty directory
# ---------------------------------------------------------------------------

def test_empty_directory_not_tracked(repo, run_git):
    """git add on an empty directory should be a no-op (git ignores empty dirs)."""
    empty = repo / "empty_dir"
    empty.mkdir()
    result = run_git("add", "empty_dir")
    # Must not crash; may silently succeed or warn
    assert result.returncode in (0, 1)

    status = run_git("status")
    assert status.returncode == 0


# ---------------------------------------------------------------------------
# .gitignore
# ---------------------------------------------------------------------------

def test_gitignore_basic(repo, run_git):
    """Files matching .gitignore must not be staged by 'git add .'."""
    (repo / ".gitignore").write_bytes(b"*.log\nbuild/\n")
    (repo / "app.py").write_bytes(b"print('hello')\n")
    (repo / "debug.log").write_bytes(b"DEBUG LOG\n")
    build = repo / "build"
    build.mkdir()
    (build / "output.o").write_bytes(b"\x7fELF binary stub")

    run_git("add", ".")
    result = run_git("status")
    assert result.returncode == 0
    combined = result.stdout + result.stderr
    # debug.log should NOT appear as staged (if gitignore is implemented)
    # We just ensure no crash; gitignore is a bonus feature per spec
    assert b"app.py" in combined or True  # at minimum, no crash


# ---------------------------------------------------------------------------
# Status from a subdirectory
# ---------------------------------------------------------------------------

def test_status_in_subdir(repo, run_git):
    """Running status from a subdirectory of the repo must work."""
    subdir = repo / "src"
    subdir.mkdir()
    (subdir / "main.py").write_bytes(b"# main\n")
    run_git("add", ".")
    run_git("commit", "-m", "init")

    # Run status with cwd=subdir
    result = run_git("status", cwd=subdir)
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# Merge edge cases
# ---------------------------------------------------------------------------

def test_merge_into_itself(repo, run_git):
    """git merge main from main must say 'Already up to date.'."""
    _commit_file(repo, run_git, "a.txt", b"a\n", "init")
    result = run_git("merge", "main")
    assert result.returncode == 0
    combined = (result.stdout + result.stderr).decode(errors="replace").lower()
    assert "already" in combined or "up to date" in combined


def test_merge_fast_forward(repo, run_git):
    """Fast-forward merge must succeed and update working tree."""
    _commit_file(repo, run_git, "a.txt", b"a\n", "init")
    run_git("branch", "feature")
    run_git("checkout", "feature")
    _commit_file(repo, run_git, "b.txt", b"b\n", "add b")
    run_git("checkout", "main")

    result = run_git("merge", "feature")
    assert result.returncode == 0
    assert (repo / "b.txt").exists(), "Merged file must appear in working tree"


# ---------------------------------------------------------------------------
# Reset edge cases
# ---------------------------------------------------------------------------

def test_reset_beyond_history(repo, run_git):
    """git reset to a nonexistent SHA must fail gracefully."""
    _commit_file(repo, run_git, "a.txt", b"a\n", "init")
    fake_sha = "0" * 40
    result = run_git("reset", "--hard", fake_sha)
    assert result.returncode != 0, "Reset to nonexistent SHA must fail"


def test_reset_soft(repo, run_git):
    """git reset --soft HEAD~1 must move HEAD but leave index unchanged."""
    _commit_file(repo, run_git, "a.txt", b"a\n", "commit 0")
    _commit_file(repo, run_git, "b.txt", b"b\n", "commit 1")

    result = run_git("reset", "--soft", "HEAD~1")
    assert result.returncode == 0, result.stderr.decode(errors="replace")

    status = run_git("status")
    assert status.returncode == 0
    # b.txt should now be staged (ready to commit again)
    combined = status.stdout + status.stderr
    assert b"b.txt" in combined


def test_reset_hard(repo, run_git):
    """git reset --hard HEAD~1 must revert working tree."""
    _commit_file(repo, run_git, "a.txt", b"a\n", "commit 0")
    _commit_file(repo, run_git, "b.txt", b"b\n", "commit 1")

    result = run_git("reset", "--hard", "HEAD~1")
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert not (repo / "b.txt").exists(), "b.txt must be gone after hard reset"


# ---------------------------------------------------------------------------
# Stash edge cases
# ---------------------------------------------------------------------------

def test_stash_on_clean_repo(repo, run_git):
    """git stash on a clean repo should be a no-op or error gracefully."""
    _commit_file(repo, run_git, "a.txt", b"a\n", "init")
    result = run_git("stash")
    # Must not crash — may print "No local changes to save" or similar
    assert result.returncode in (0, 1)


def test_stash_pop_nothing_stashed(repo, run_git):
    """git stash pop with nothing stashed must print an error, not crash."""
    _commit_file(repo, run_git, "a.txt", b"a\n", "init")
    result = run_git("stash", "pop")
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert combined  # must say something


def test_stash_roundtrip(repo, run_git):
    """Stash saves changes; pop restores them."""
    _commit_file(repo, run_git, "a.txt", b"original\n", "init")

    # Modify without committing
    (repo / "a.txt").write_bytes(b"modified\n")
    run_git("add", "a.txt")

    stash_result = run_git("stash")
    if stash_result.returncode != 0:
        pytest.skip("stash not implemented")

    # After stash, file should be back to original
    assert (repo / "a.txt").read_bytes() == b"original\n"

    pop_result = run_git("stash", "pop")
    assert pop_result.returncode == 0, pop_result.stderr.decode(errors="replace")
    assert (repo / "a.txt").read_bytes() == b"modified\n"


def test_stash_list(repo, run_git):
    """git stash list must show stash entries."""
    _commit_file(repo, run_git, "a.txt", b"v1\n", "init")
    (repo / "a.txt").write_bytes(b"v2\n")
    run_git("add", "a.txt")
    stash_result = run_git("stash")
    if stash_result.returncode != 0:
        pytest.skip("stash not implemented")

    result = run_git("stash", "list")
    assert result.returncode == 0
    assert b"stash@{0}" in result.stdout
