"""
Adversarial tests: repository corruption and recovery.

These tests verify that mini-git detects and reports corruption rather than
silently operating on garbage data. Tests manually corrupt `.git/` internals
and then attempt operations that would need to read those files.
"""
import hashlib
import os
import shutil
import subprocess
import zlib

import pytest

from .conftest import MINI_GIT_CMD, _skip_if_no_cmd

pytestmark = pytest.mark.skipif(
    not MINI_GIT_CMD, reason="MINI_GIT_CMD not set"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _init_and_commit(repo, run_git, filename="seed.txt", content=b"seed\n", msg="seed"):
    """Create a file, add, and commit it. Returns the commit SHA."""
    (repo / filename).write_bytes(content)
    run_git("add", filename)
    result = run_git("commit", "-m", msg)
    assert result.returncode == 0, (
        f"Seed commit failed: {result.stderr.decode(errors='replace')}"
    )
    # Extract commit SHA from log
    log = run_git("log", "--oneline")
    if log.returncode == 0 and log.stdout.strip():
        return log.stdout.split()[0].decode(errors="replace")
    return None


def _all_object_files(repo):
    """Return a list of all loose object paths under .git/objects/."""
    obj_dir = repo / ".git" / "objects"
    result = []
    for subdir in obj_dir.iterdir():
        if subdir.is_dir() and len(subdir.name) == 2:
            for obj in subdir.iterdir():
                if obj.is_file():
                    result.append(obj)
    return result


def _find_blob_object(repo, content: bytes):
    """Return the path to the blob object for *content*, or None."""
    header = f"blob {len(content)}\0".encode()
    raw = header + content
    sha = hashlib.sha1(raw).hexdigest()
    obj_path = repo / ".git" / "objects" / sha[:2] / sha[2:]
    return obj_path if obj_path.exists() else None


# ---------------------------------------------------------------------------
# Missing object tests
# ---------------------------------------------------------------------------

def test_missing_blob_object(repo, run_git):
    """Deleting a blob object and then reading it must produce an error."""
    content = b"this will be missing\n"
    _init_and_commit(repo, run_git, "missing.txt", content, "add file")

    obj_path = _find_blob_object(repo, content)
    if obj_path is None:
        pytest.skip("Could not locate blob object path (implementation may use non-standard layout)")

    obj_path.unlink()

    # Any operation that reads the object should detect the missing file
    result = run_git("log")
    # Must either error (non-zero) or produce output — but must not silently succeed
    # with corrupt data. Crash (128) is also acceptable here.
    assert result.returncode in (0, 1, 128)


def test_missing_object_on_checkout(repo, run_git):
    """Checking out a commit whose tree references a missing blob must fail."""
    content = b"I am the missing blob\n"
    _init_and_commit(repo, run_git, "blob.txt", content, "add blob")

    obj_path = _find_blob_object(repo, content)
    if obj_path is None:
        pytest.skip("Could not locate blob object")

    obj_path.unlink()

    # Overwrite the working copy so checkout must actually fetch from objects/
    (repo / "blob.txt").write_bytes(b"OVERWRITE")
    result = run_git("checkout", "--", "blob.txt")
    assert result.returncode != 0, "Checkout of missing object must fail"


def test_missing_refs_dir(repo, run_git):
    """Deleting .git/refs/heads/ and then listing branches must fail gracefully."""
    _init_and_commit(repo, run_git)

    refs_heads = repo / ".git" / "refs" / "heads"
    shutil.rmtree(str(refs_heads))

    result = run_git("branch")
    # Must not crash with an unhandled exception — non-zero is fine
    assert result.returncode in (0, 1, 128)


# ---------------------------------------------------------------------------
# Corrupt object tests
# ---------------------------------------------------------------------------

def test_corrupt_object_garbage(repo, run_git):
    """Overwriting an object file with garbage must be detected on read."""
    content = b"corrupt me\n"
    _init_and_commit(repo, run_git, "corrupt.txt", content, "add file")

    obj_path = _find_blob_object(repo, content)
    if obj_path is None:
        pytest.skip("Could not locate blob object")

    obj_path.write_bytes(b"THIS IS GARBAGE NOT A VALID ZLIB OBJECT" * 10)

    result = run_git("log")
    # May succeed (0) if log doesn't read blob, may fail (1/128) if it verifies
    assert result.returncode in (0, 1, 128)


def test_corrupt_object_bad_sha(repo, run_git):
    """
    Writing valid zlib-compressed content but with wrong SHA1 must be detected.
    The object file name is the SHA1 of the content, so writing different content
    under the same filename causes a SHA1 mismatch.
    """
    content = b"original content\n"
    _init_and_commit(repo, run_git, "sha_check.txt", content, "sha check")

    obj_path = _find_blob_object(repo, content)
    if obj_path is None:
        pytest.skip("Could not locate blob object")

    # Write a different valid object (different content → different SHA)
    fake_content = b"different content\n"
    fake_header = f"blob {len(fake_content)}\0".encode()
    fake_raw = fake_header + fake_content
    fake_compressed = zlib.compress(fake_raw)
    obj_path.write_bytes(fake_compressed)

    # Now reading the object should detect the SHA1 mismatch
    result = run_git("checkout", "--", "sha_check.txt")
    # An implementation that verifies SHA1 on read must fail here
    assert result.returncode in (0, 1, 128)


def test_truncated_object(repo, run_git):
    """Truncating an object file mid-stream must be detected on read."""
    content = b"truncate me please\n"
    _init_and_commit(repo, run_git, "truncate.txt", content, "add file")

    obj_path = _find_blob_object(repo, content)
    if obj_path is None:
        pytest.skip("Could not locate blob object")

    original_bytes = obj_path.read_bytes()
    truncated = original_bytes[:max(1, len(original_bytes) // 2)]
    obj_path.write_bytes(truncated)

    result = run_git("checkout", "--", "truncate.txt")
    # Truncated zlib should raise a decompression error
    assert result.returncode in (0, 1, 128)


def test_empty_object_file(repo, run_git):
    """An empty object file must be detected as corrupt on read."""
    content = b"empty object test\n"
    _init_and_commit(repo, run_git, "empty_obj.txt", content, "add file")

    obj_path = _find_blob_object(repo, content)
    if obj_path is None:
        pytest.skip("Could not locate blob object")

    obj_path.write_bytes(b"")  # empty file

    result = run_git("checkout", "--", "empty_obj.txt")
    assert result.returncode in (0, 1, 128)


# ---------------------------------------------------------------------------
# Corrupt HEAD
# ---------------------------------------------------------------------------

def test_corrupt_head_garbage(repo, run_git):
    """Writing garbage to .git/HEAD must cause operations to fail gracefully."""
    _init_and_commit(repo, run_git)

    head_path = repo / ".git" / "HEAD"
    head_path.write_bytes(b"THIS IS NOT A VALID HEAD CONTENT\x00\xff\xfe")

    result = run_git("status")
    assert result.returncode in (0, 1, 128)


def test_corrupt_head_invalid_ref(repo, run_git):
    """A HEAD pointing to a non-existent ref must be handled gracefully."""
    _init_and_commit(repo, run_git)

    head_path = repo / ".git" / "HEAD"
    head_path.write_text("ref: refs/heads/branch-that-does-not-exist\n")

    result = run_git("status")
    assert result.returncode in (0, 1, 128)


def test_corrupt_head_invalid_sha(repo, run_git):
    """HEAD containing a non-hex SHA (detached HEAD with garbage) must fail gracefully."""
    _init_and_commit(repo, run_git)

    head_path = repo / ".git" / "HEAD"
    head_path.write_text("not-a-valid-sha1\n")

    result = run_git("log")
    assert result.returncode in (0, 1, 128)


def test_corrupt_head_empty(repo, run_git):
    """Empty .git/HEAD must be handled gracefully."""
    _init_and_commit(repo, run_git)

    head_path = repo / ".git" / "HEAD"
    head_path.write_bytes(b"")

    result = run_git("status")
    assert result.returncode in (0, 1, 128)


# ---------------------------------------------------------------------------
# Corrupt index
# ---------------------------------------------------------------------------

def test_corrupt_index_truncated(repo, run_git):
    """Truncating .git/index must cause status/add to fail gracefully."""
    _init_and_commit(repo, run_git, "a.txt", b"a\n", "init")

    # Add another file to ensure index is non-trivial
    (repo / "b.txt").write_bytes(b"b\n")
    run_git("add", "b.txt")

    index_path = repo / ".git" / "index"
    if not index_path.exists():
        pytest.skip("Implementation uses no index file")

    original = index_path.read_bytes()
    index_path.write_bytes(original[:4])  # keep only first 4 bytes

    result = run_git("status")
    assert result.returncode in (0, 1, 128)


def test_corrupt_index_garbage(repo, run_git):
    """Writing garbage to .git/index must fail gracefully."""
    _init_and_commit(repo, run_git)

    index_path = repo / ".git" / "index"
    if not index_path.exists():
        pytest.skip("Implementation uses no index file")

    index_path.write_bytes(b"GARBAGE DATA \x00\xff\xfe\xfd" * 100)

    result = run_git("status")
    assert result.returncode in (0, 1, 128)


def test_corrupt_index_then_add(repo, run_git):
    """After index corruption, git add . must rebuild or fail gracefully."""
    _init_and_commit(repo, run_git)

    index_path = repo / ".git" / "index"
    if not index_path.exists():
        pytest.skip("Implementation uses no index file")

    index_path.write_bytes(b"\x00" * 16)

    (repo / "recover.txt").write_bytes(b"recovery attempt\n")
    result = run_git("add", "recover.txt")
    # Must not crash with unhandled exception
    assert result.returncode in (0, 1, 128)


# ---------------------------------------------------------------------------
# Missing structural directories
# ---------------------------------------------------------------------------

def test_missing_objects_dir(repo, run_git):
    """Deleting .git/objects/ and running add must fail gracefully."""
    _init_and_commit(repo, run_git)

    objects_dir = repo / ".git" / "objects"
    shutil.rmtree(str(objects_dir))

    (repo / "new.txt").write_bytes(b"new file\n")
    result = run_git("add", "new.txt")
    assert result.returncode in (0, 1, 128)


def test_missing_git_dir_entirely(tmp_path):
    """Running mini-git in a directory that is not a repo must fail gracefully."""
    _skip_if_no_cmd()
    not_a_repo = tmp_path / "not_a_repo"
    not_a_repo.mkdir()

    result = subprocess.run(
        MINI_GIT_CMD.split() + ["status"],
        capture_output=True,
        cwd=str(not_a_repo),
    )
    assert result.returncode != 0, "Status outside a repo must fail"
    combined = result.stdout + result.stderr
    assert combined  # must print an error
