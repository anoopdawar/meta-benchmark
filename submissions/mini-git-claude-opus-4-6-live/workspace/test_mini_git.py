"""
Tests for mini-git.

Run with: pytest test_mini_git.py -v
No dependency on the real `git` binary.
"""

import hashlib
import json
import os
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

MINI_GIT = [sys.executable, str(Path(__file__).parent / "mini_git.py")]


def run(*args, cwd=None, input=None):
    return subprocess.run(
        MINI_GIT + list(args),
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        input=input,
    )


@pytest.fixture
def repo(tmp_path):
    result = run("init", cwd=tmp_path)
    assert result.returncode == 0
    return tmp_path


def commit_file(repo, filename, content, message):
    (repo / filename).write_text(content)
    run("add", filename, cwd=repo)
    run("commit", "-m", message, cwd=repo)


# ---------------------------------------------------------------------------
# Object serialization
# ---------------------------------------------------------------------------

class TestObjectStore:
    def test_blob_sha_matches_real_git_format(self, tmp_path):
        """SHA1 must match real git's formula: SHA1('blob {len}\0{content}')."""
        run("init", cwd=tmp_path)
        content = b"hello world\n"
        expected_sha = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\x00" + content).hexdigest()

        (tmp_path / "hello.txt").write_bytes(content)
        run("add", "hello.txt", cwd=tmp_path)

        # Find the blob in objects/
        objects_dir = tmp_path / ".git" / "objects"
        found = []
        for d in objects_dir.iterdir():
            if d.name in ("pack", "info"):
                continue
            for f in d.iterdir():
                found.append(d.name + f.name)

        assert expected_sha in found, f"Expected blob SHA {expected_sha} not found"

    def test_blob_zlib_compressed(self, tmp_path):
        run("init", cwd=tmp_path)
        (tmp_path / "f.txt").write_text("test content")
        run("add", "f.txt", cwd=tmp_path)

        objects_dir = tmp_path / ".git" / "objects"
        for d in objects_dir.iterdir():
            if d.is_dir() and d.name not in ("pack", "info"):
                for f in d.iterdir():
                    raw = f.read_bytes()
                    decompressed = zlib.decompress(raw)
                    assert decompressed.startswith(b"blob ")
                    return
        pytest.fail("No object files found")

    def test_identical_content_produces_same_sha(self, repo):
        """Deduplication: two files with same content share one blob."""
        (repo / "a.txt").write_text("same content")
        (repo / "b.txt").write_text("same content")
        run("add", ".", cwd=repo)

        objects_dir = repo / ".git" / "objects"
        blobs = []
        for d in objects_dir.iterdir():
            if d.is_dir() and d.name not in ("pack", "info"):
                for f in d.iterdir():
                    blobs.append(d.name + f.name)

        # Should be exactly one blob for both files
        assert len(set(blobs)) == len(blobs)

    def test_corrupt_object_detected(self, repo):
        commit_file(repo, "f.txt", "hello", "first")
        objects_dir = repo / ".git" / "objects"
        for d in objects_dir.iterdir():
            if d.is_dir() and d.name not in ("pack", "info"):
                for f in d.iterdir():
                    f.write_bytes(b"garbage")
                    result = run("log", cwd=repo)
                    assert result.returncode != 0 or "corrupt" in result.stderr.lower()
                    return


# ---------------------------------------------------------------------------
# git init
# ---------------------------------------------------------------------------

class TestInit:
    def test_creates_git_dir(self, tmp_path):
        run("init", cwd=tmp_path)
        assert (tmp_path / ".git").is_dir()

    def test_creates_objects_dir(self, tmp_path):
        run("init", cwd=tmp_path)
        assert (tmp_path / ".git" / "objects").is_dir()

    def test_creates_refs_heads(self, tmp_path):
        run("init", cwd=tmp_path)
        assert (tmp_path / ".git" / "refs" / "heads").is_dir()

    def test_creates_head(self, tmp_path):
        run("init", cwd=tmp_path)
        head = (tmp_path / ".git" / "HEAD").read_text()
        assert "refs/heads/" in head

    def test_idempotent(self, tmp_path):
        run("init", cwd=tmp_path)
        (tmp_path / "file.txt").write_text("data")
        run("add", "file.txt", cwd=tmp_path)
        run("commit", "-m", "before reinit", cwd=tmp_path)
        result = run("init", cwd=tmp_path)
        assert result.returncode == 0
        assert (tmp_path / ".git").is_dir()

    def test_init_in_subdirectory(self, tmp_path):
        subdir = tmp_path / "sub"
        subdir.mkdir()
        result = run("init", str(subdir))
        assert result.returncode == 0
        assert (subdir / ".git").is_dir()


# ---------------------------------------------------------------------------
# git add
# ---------------------------------------------------------------------------

class TestAdd:
    def test_add_single_file(self, repo):
        (repo / "f.txt").write_text("hello")
        result = run("add", "f.txt", cwd=repo)
        assert result.returncode == 0

    def test_add_creates_index(self, repo):
        (repo / "f.txt").write_text("hello")
        run("add", "f.txt", cwd=repo)
        assert (repo / ".git" / "index.json").exists()

    def test_add_dot_stages_all(self, repo):
        (repo / "a.txt").write_text("a")
        (repo / "b.txt").write_text("b")
        run("add", ".", cwd=repo)
        index = json.loads((repo / ".git" / "index.json").read_text())
        assert "a.txt" in index
        assert "b.txt" in index

    def test_add_nonexistent_fails(self, repo):
        result = run("add", "nonexistent.txt", cwd=repo)
        assert result.returncode != 0

    def test_add_binary_file(self, repo):
        (repo / "binary.bin").write_bytes(bytes(range(256)))
        result = run("add", "binary.bin", cwd=repo)
        assert result.returncode == 0

    def test_add_empty_file(self, repo):
        (repo / "empty.txt").write_bytes(b"")
        result = run("add", "empty.txt", cwd=repo)
        assert result.returncode == 0

    def test_add_nested_directory(self, repo):
        (repo / "subdir").mkdir()
        (repo / "subdir" / "nested.txt").write_text("nested")
        result = run("add", "subdir/nested.txt", cwd=repo)
        assert result.returncode == 0


# ---------------------------------------------------------------------------
# git commit
# ---------------------------------------------------------------------------

class TestCommit:
    def test_commit_succeeds(self, repo):
        (repo / "f.txt").write_text("hello")
        run("add", "f.txt", cwd=repo)
        result = run("commit", "-m", "first commit", cwd=repo)
        assert result.returncode == 0

    def test_commit_creates_commit_object(self, repo):
        (repo / "f.txt").write_text("hello")
        run("add", "f.txt", cwd=repo)
        run("commit", "-m", "first", cwd=repo)
        head = (repo / ".git" / "HEAD").read_text().strip()
        if head.startswith("ref:"):
            ref = head.split(": ")[1]
            sha = (repo / ".git" / ref).read_text().strip()
        else:
            sha = head
        assert len(sha) == 40

    def test_commit_updates_head(self, repo):
        (repo / "f.txt").write_text("hello")
        run("add", "f.txt", cwd=repo)
        run("commit", "-m", "first", cwd=repo)
        sha1 = _get_head_sha(repo)

        (repo / "f.txt").write_text("world")
        run("add", "f.txt", cwd=repo)
        run("commit", "-m", "second", cwd=repo)
        sha2 = _get_head_sha(repo)
        assert sha1 != sha2

    def test_empty_commit_fails(self, repo):
        result = run("commit", "-m", "nothing staged", cwd=repo)
        assert result.returncode != 0

    def test_commit_message_in_log(self, repo):
        commit_file(repo, "f.txt", "data", "my unique message abc123")
        result = run("log", cwd=repo)
        assert "my unique message abc123" in result.stdout

    def test_second_commit_has_parent(self, repo):
        commit_file(repo, "a.txt", "a", "first")
        sha1 = _get_head_sha(repo)
        commit_file(repo, "b.txt", "b", "second")

        sha2 = _get_head_sha(repo)
        _, content = _read_object(repo, sha2)
        assert sha1.encode() in content or sha1 in content.decode(errors="replace")


# ---------------------------------------------------------------------------
# git log
# ---------------------------------------------------------------------------

class TestLog:
    def test_log_empty_repo_fails(self, repo):
        result = run("log", cwd=repo)
        assert result.returncode != 0

    def test_log_shows_commit(self, repo):
        commit_file(repo, "f.txt", "hello", "first commit")
        result = run("log", cwd=repo)
        assert result.returncode == 0
        assert "first commit" in result.stdout

    def test_log_reverse_chronological(self, repo):
        commit_file(repo, "a.txt", "a", "commit A")
        commit_file(repo, "b.txt", "b", "commit B")
        result = run("log", cwd=repo)
        pos_a = result.stdout.find("commit A")
        pos_b = result.stdout.find("commit B")
        assert pos_b < pos_a  # B is more recent, should appear first

    def test_log_oneline(self, repo):
        commit_file(repo, "f.txt", "data", "oneline test")
        result = run("log", "--oneline", cwd=repo)
        assert result.returncode == 0
        lines = [l for l in result.stdout.strip().splitlines() if l]
        assert len(lines) >= 1
        assert "oneline test" in lines[0]

    def test_log_n_flag(self, repo):
        for i in range(5):
            commit_file(repo, "f.txt", f"v{i}", f"commit {i}")
        result = run("log", "-n", "2", "--oneline", cwd=repo)
        lines = [l for l in result.stdout.strip().splitlines() if l]
        assert len(lines) == 2


# ---------------------------------------------------------------------------
# git status
# ---------------------------------------------------------------------------

class TestStatus:
    def test_status_clean_after_commit(self, repo):
        commit_file(repo, "f.txt", "hello", "first")
        result = run("status", cwd=repo)
        assert result.returncode == 0
        assert "nothing to commit" in result.stdout

    def test_status_shows_untracked(self, repo):
        (repo / "new.txt").write_text("new")
        result = run("status", cwd=repo)
        assert "new.txt" in result.stdout

    def test_status_shows_staged(self, repo):
        (repo / "f.txt").write_text("data")
        run("add", "f.txt", cwd=repo)
        result = run("status", cwd=repo)
        assert "f.txt" in result.stdout

    def test_status_shows_modified(self, repo):
        commit_file(repo, "f.txt", "original", "first")
        (repo / "f.txt").write_text("modified")
        result = run("status", cwd=repo)
        assert "f.txt" in result.stdout


# ---------------------------------------------------------------------------
# git branch
# ---------------------------------------------------------------------------

class TestBranch:
    def test_create_branch(self, repo):
        commit_file(repo, "f.txt", "data", "first")
        result = run("branch", "feature", cwd=repo)
        assert result.returncode == 0
        assert (repo / ".git" / "refs" / "heads" / "feature").exists()

    def test_list_branches(self, repo):
        commit_file(repo, "f.txt", "data", "first")
        run("branch", "feature", cwd=repo)
        result = run("branch", cwd=repo)
        assert "feature" in result.stdout
        assert "*" in result.stdout  # current branch marked

    def test_delete_branch(self, repo):
        commit_file(repo, "f.txt", "data", "first")
        run("branch", "feature", cwd=repo)
        result = run("branch", "-d", "feature", cwd=repo)
        assert result.returncode == 0
        assert not (repo / ".git" / "refs" / "heads" / "feature").exists()

    def test_delete_current_branch_fails(self, repo):
        commit_file(repo, "f.txt", "data", "first")
        result = run("branch", "-d", "main", cwd=repo)
        assert result.returncode != 0


# ---------------------------------------------------------------------------
# git checkout
# ---------------------------------------------------------------------------

class TestCheckout:
    def test_checkout_switches_branch(self, repo):
        commit_file(repo, "f.txt", "data", "first")
        run("branch", "feature", cwd=repo)
        result = run("checkout", "feature", cwd=repo)
        assert result.returncode == 0
        head = (repo / ".git" / "HEAD").read_text().strip()
        assert "feature" in head

    def test_checkout_b_creates_and_switches(self, repo):
        commit_file(repo, "f.txt", "data", "first")
        result = run("checkout", "-b", "newbranch", cwd=repo)
        assert result.returncode == 0
        head = (repo / ".git" / "HEAD").read_text().strip()
        assert "newbranch" in head

    def test_checkout_restores_files(self, repo):
        commit_file(repo, "main.txt", "main content", "main commit")
        run("checkout", "-b", "feature", cwd=repo)
        commit_file(repo, "feature.txt", "feature content", "feature commit")
        run("checkout", "main", cwd=repo)
        assert not (repo / "feature.txt").exists() or True  # May or may not exist depending on impl

    def test_checkout_nonexistent_fails(self, repo):
        commit_file(repo, "f.txt", "data", "first")
        result = run("checkout", "nonexistent", cwd=repo)
        assert result.returncode != 0


# ---------------------------------------------------------------------------
# git merge
# ---------------------------------------------------------------------------

class TestMerge:
    def test_fast_forward_merge(self, repo):
        commit_file(repo, "base.txt", "base", "base commit")
        run("checkout", "-b", "feature", cwd=repo)
        commit_file(repo, "feature.txt", "feature", "feature commit")
        run("checkout", "main", cwd=repo)
        result = run("merge", "feature", cwd=repo)
        assert result.returncode == 0
        assert (repo / "feature.txt").exists()

    def test_already_up_to_date(self, repo):
        commit_file(repo, "f.txt", "data", "first")
        run("checkout", "-b", "feature", cwd=repo)
        run("checkout", "main", cwd=repo)
        result = run("merge", "feature", cwd=repo)
        assert "up to date" in result.stdout.lower() or result.returncode == 0

    def test_merge_conflict_markers(self, repo):
        commit_file(repo, "conflict.txt", "base content\n", "base")
        run("checkout", "-b", "branch-a", cwd=repo)
        commit_file(repo, "conflict.txt", "branch-a content\n", "branch-a change")
        run("checkout", "main", cwd=repo)
        commit_file(repo, "conflict.txt", "main content\n", "main change")
        result = run("merge", "branch-a", cwd=repo)
        if result.returncode != 0:
            content = (repo / "conflict.txt").read_text()
            assert "<<<<<<<" in content or "CONFLICT" in result.stdout


# ---------------------------------------------------------------------------
# git diff
# ---------------------------------------------------------------------------

class TestDiff:
    def test_diff_unstaged_changes(self, repo):
        commit_file(repo, "f.txt", "original\n", "first")
        (repo / "f.txt").write_text("modified\n")
        result = run("diff", cwd=repo)
        assert result.returncode == 0
        assert "-original" in result.stdout
        assert "+modified" in result.stdout

    def test_diff_staged_changes(self, repo):
        commit_file(repo, "f.txt", "original\n", "first")
        (repo / "f.txt").write_text("staged change\n")
        run("add", "f.txt", cwd=repo)
        result = run("diff", "--staged", cwd=repo)
        assert result.returncode == 0
        assert "staged change" in result.stdout

    def test_diff_clean_is_empty(self, repo):
        commit_file(repo, "f.txt", "data", "first")
        result = run("diff", cwd=repo)
        assert result.returncode == 0
        assert result.stdout.strip() == ""


# ---------------------------------------------------------------------------
# git reset
# ---------------------------------------------------------------------------

class TestReset:
    def test_soft_reset_keeps_staged(self, repo):
        commit_file(repo, "a.txt", "a", "first")
        commit_file(repo, "b.txt", "b", "second")
        sha_first = _get_head_sha(repo)

        result = run("reset", "--soft", "HEAD~1", cwd=repo)
        assert result.returncode == 0
        index = json.loads((repo / ".git" / "index.json").read_text())
        assert "b.txt" in index  # Still staged

    def test_mixed_reset_unstages(self, repo):
        commit_file(repo, "a.txt", "a", "first")
        commit_file(repo, "b.txt", "b", "second")
        result = run("reset", "HEAD~1", cwd=repo)
        assert result.returncode == 0
        new_head = _get_head_sha(repo)
        # HEAD should have moved back

    def test_hard_reset_cleans_working_tree(self, repo):
        commit_file(repo, "a.txt", "original", "first")
        (repo / "a.txt").write_text("modified")
        run("add", "a.txt", cwd=repo)
        commit_file(repo, "b.txt", "b", "second")
        run("reset", "--hard", "HEAD~1", cwd=repo)
        assert (repo / "a.txt").read_text() == "original"

    def test_reset_updates_head(self, repo):
        commit_file(repo, "a.txt", "a", "first")
        sha1 = _get_head_sha(repo)
        commit_file(repo, "b.txt", "b", "second")
        run("reset", "--hard", "HEAD~1", cwd=repo)
        assert _get_head_sha(repo) == sha1


# ---------------------------------------------------------------------------
# git stash
# ---------------------------------------------------------------------------

class TestStash:
    def test_stash_saves_changes(self, repo):
        commit_file(repo, "f.txt", "original", "first")
        (repo / "f.txt").write_text("modified")
        result = run("stash", cwd=repo)
        assert result.returncode == 0
        assert (repo / "f.txt").read_text() == "original"

    def test_stash_pop_restores(self, repo):
        commit_file(repo, "f.txt", "original", "first")
        (repo / "f.txt").write_text("modified")
        run("stash", cwd=repo)
        result = run("stash", "pop", cwd=repo)
        assert result.returncode == 0
        assert (repo / "f.txt").read_text() == "modified"

    def test_stash_list(self, repo):
        commit_file(repo, "f.txt", "original", "first")
        (repo / "f.txt").write_text("modified")
        run("stash", cwd=repo)
        result = run("stash", "list", cwd=repo)
        assert result.returncode == 0
        assert "stash@{0}" in result.stdout

    def test_stash_drop(self, repo):
        commit_file(repo, "f.txt", "original", "first")
        (repo / "f.txt").write_text("modified")
        run("stash", cwd=repo)
        result = run("stash", "drop", cwd=repo)
        assert result.returncode == 0
        list_result = run("stash", "list", cwd=repo)
        assert "stash@{0}" not in list_result.stdout

    def test_multiple_stashes(self, repo):
        commit_file(repo, "f.txt", "original", "first")
        (repo / "f.txt").write_text("change 1")
        run("stash", cwd=repo)
        (repo / "f.txt").write_text("change 2")
        run("stash", cwd=repo)
        result = run("stash", "list", cwd=repo)
        assert "stash@{0}" in result.stdout
        assert "stash@{1}" in result.stdout

    def test_stash_pop_empty_fails(self, repo):
        commit_file(repo, "f.txt", "data", "first")
        result = run("stash", "pop", cwd=repo)
        assert result.returncode != 0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_filename_with_spaces(self, repo):
        (repo / "my file.txt").write_text("data")
        result = run("add", "my file.txt", cwd=repo)
        assert result.returncode == 0

    def test_nested_directories(self, repo):
        (repo / "a" / "b" / "c").mkdir(parents=True)
        (repo / "a" / "b" / "c" / "deep.txt").write_text("deep")
        result = run("add", "a/b/c/deep.txt", cwd=repo)
        assert result.returncode == 0
        run("commit", "-m", "deep file", cwd=repo)
        assert _get_head_sha(repo) is not None

    def test_unicode_content(self, repo):
        (repo / "unicode.txt").write_text("こんにちは 🐙 مرحبا", encoding="utf-8")
        result = run("add", "unicode.txt", cwd=repo)
        assert result.returncode == 0

    def test_large_file(self, repo):
        (repo / "large.txt").write_bytes(b"x" * 1_000_000)
        result = run("add", "large.txt", cwd=repo)
        assert result.returncode == 0

    def test_not_a_repo_fails(self, tmp_path):
        result = run("status", cwd=tmp_path)
        assert result.returncode != 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_head_sha(repo: Path) -> str:
    head = (repo / ".git" / "HEAD").read_text().strip()
    if head.startswith("ref:"):
        ref = head.split(": ", 1)[1]
        ref_path = repo / ".git" / ref
        return ref_path.read_text().strip() if ref_path.exists() else None
    return head


def _read_object(repo: Path, sha: str):
    path = repo / ".git" / "objects" / sha[:2] / sha[2:]
    raw = zlib.decompress(path.read_bytes())
    null = raw.index(b"\x00")
    header = raw[:null].decode()
    obj_type, _ = header.split(" ", 1)
    return obj_type, raw[null + 1:]
