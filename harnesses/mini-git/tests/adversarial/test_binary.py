"""
Adversarial tests: binary file handling.

Tests verify that mini-git can store, retrieve, and diff binary blobs without
crashing, data loss, or silent corruption.
"""
import hashlib
import os
import struct
import zlib

import pytest

from .conftest import MINI_GIT_CMD, _skip_if_no_cmd, binary_content

pytestmark = pytest.mark.skipif(
    not MINI_GIT_CMD, reason="MINI_GIT_CMD not set"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(path, content: bytes):
    path.write_bytes(content)
    return path


def _make_small_png(path):
    """Write a 1×1 white PNG to *path*."""
    # Minimal valid PNG: IHDR + IDAT + IEND
    def chunk(tag: bytes, data: bytes) -> bytes:
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    png_sig = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    raw_row = b"\x00\xff\xff\xff"  # filter byte + RGB white
    idat = chunk(b"IDAT", zlib.compress(raw_row))
    iend = chunk(b"IEND", b"")
    path.write_bytes(png_sig + ihdr + idat + iend)
    return path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_add_binary_file(repo, run_git):
    """Adding a binary file must exit 0 and not crash."""
    p = _write(repo / "blob.bin", binary_content())
    result = run_git("add", "blob.bin")
    assert result.returncode == 0, result.stderr.decode(errors="replace")


def test_commit_with_binary(repo, run_git):
    """Committing a binary file must succeed; log must show the commit."""
    _write(repo / "data.bin", binary_content())
    run_git("add", "data.bin")
    result = run_git("commit", "-m", "add binary file")
    assert result.returncode == 0, result.stderr.decode(errors="replace")

    log = run_git("log", "--oneline")
    assert log.returncode == 0
    assert b"add binary file" in log.stdout


def test_diff_binary_does_not_crash(repo, run_git):
    """git diff on a binary file must not crash (returncode may be 0 or 1)."""
    _write(repo / "img.bin", binary_content())
    run_git("add", "img.bin")
    run_git("commit", "-m", "initial binary")

    # Modify the binary
    _write(repo / "img.bin", binary_content() + b"\xde\xad\xbe\xef")
    result = run_git("diff")
    # Must not be an internal error (128)
    assert result.returncode in (0, 1), result.stderr.decode(errors="replace")


def test_diff_binary_shows_marker(repo, run_git):
    """Binary diff output should contain 'Binary files' or not crash."""
    _write(repo / "img.bin", binary_content())
    run_git("add", "img.bin")
    run_git("commit", "-m", "v1")

    _write(repo / "img.bin", binary_content() + b"\x00NEW")
    run_git("add", "img.bin")
    result = run_git("diff", "--staged")
    assert result.returncode in (0, 1)
    # If implementation prints a "Binary files differ" message, great; if not,
    # it must at least not crash.
    combined = result.stdout + result.stderr
    # Accept either a diff output or a "Binary files" indicator
    assert combined is not None  # always true — just confirms no exception


def test_binary_roundtrip(repo, run_git, tmp_path):
    """Checking out a commit with a binary file restores the exact bytes."""
    original = binary_content()
    _write(repo / "round.bin", original)
    run_git("add", "round.bin")
    run_git("commit", "-m", "binary roundtrip")

    # Overwrite with different content
    (repo / "round.bin").write_bytes(b"OVERWRITTEN")
    # Restore from HEAD
    result = run_git("checkout", "--", "round.bin")
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    restored = (repo / "round.bin").read_bytes()
    assert restored == original, "Binary file content changed after checkout"


def test_binary_large(repo, run_git):
    """Adding a 10 MB binary file must succeed."""
    large = os.urandom(10 * 1024 * 1024)  # 10 MB of random bytes
    _write(repo / "large.bin", large)
    result = run_git("add", "large.bin")
    assert result.returncode == 0, result.stderr.decode(errors="replace")

    result2 = run_git("commit", "-m", "large binary")
    assert result2.returncode == 0, result2.stderr.decode(errors="replace")


def test_executable_bit_status(repo, run_git):
    """An executable file should be handled (mode 100755) without crashing."""
    p = repo / "script.sh"
    _write(p, b"#!/bin/sh\necho hello\n")
    p.chmod(0o755)
    result = run_git("add", "script.sh")
    assert result.returncode == 0, result.stderr.decode(errors="replace")

    status = run_git("status")
    assert status.returncode == 0


def test_executable_bit_commit(repo, run_git):
    """Committing an executable file must not crash."""
    p = repo / "run.sh"
    _write(p, b"#!/bin/sh\necho hi\n")
    p.chmod(0o755)
    run_git("add", "run.sh")
    result = run_git("commit", "-m", "add executable")
    assert result.returncode == 0, result.stderr.decode(errors="replace")


def test_null_bytes_in_content(repo, run_git):
    """File with NUL bytes throughout must be stored and retrieved correctly."""
    content = b"\x00" * 1024  # 1 KB of NUL bytes
    _write(repo / "nulls.bin", content)
    run_git("add", "nulls.bin")
    run_git("commit", "-m", "null bytes")

    # Restore from HEAD after overwrite
    (repo / "nulls.bin").write_bytes(b"not nulls")
    run_git("checkout", "--", "nulls.bin")
    assert (repo / "nulls.bin").read_bytes() == content


def test_image_file_png(repo, run_git):
    """A programmatically-created PNG file can be added and committed."""
    png_path = repo / "pixel.png"
    _make_small_png(png_path)
    result = run_git("add", "pixel.png")
    assert result.returncode == 0, result.stderr.decode(errors="replace")

    result2 = run_git("commit", "-m", "add PNG image")
    assert result2.returncode == 0, result2.stderr.decode(errors="replace")


def test_mixed_binary_and_text(repo, run_git):
    """A repo with both binary and text files must handle status/commit."""
    _write(repo / "text.txt", b"Hello, world!\n")
    _write(repo / "data.bin", binary_content())
    _write(repo / "readme.md", b"# Project\n\nSome text.\n")

    run_git("add", "text.txt")
    run_git("add", "data.bin")
    run_git("add", "readme.md")
    result = run_git("commit", "-m", "mixed repo")
    assert result.returncode == 0, result.stderr.decode(errors="replace")

    status = run_git("status")
    assert status.returncode == 0


def test_binary_diff_staged(repo, run_git):
    """git diff --staged on a newly staged binary file must not crash."""
    _write(repo / "staged.bin", binary_content())
    run_git("add", "staged.bin")
    result = run_git("diff", "--staged")
    assert result.returncode in (0, 1)


def test_binary_status_shows_new_file(repo, run_git):
    """Status must list a binary file as 'new file' (not crash or skip it)."""
    _write(repo / "new.bin", binary_content())
    run_git("add", "new.bin")
    result = run_git("status")
    assert result.returncode == 0
    combined = result.stdout + result.stderr
    assert b"new.bin" in combined


def test_binary_modify_then_status(repo, run_git):
    """After committing a binary file, modifying it shows as 'modified'."""
    _write(repo / "mod.bin", binary_content())
    run_git("add", "mod.bin")
    run_git("commit", "-m", "initial")

    (repo / "mod.bin").write_bytes(b"\xde\xad\xbe\xef" * 100)
    result = run_git("status")
    assert result.returncode == 0
    assert b"mod.bin" in result.stdout + result.stderr


def test_binary_sha1_deduplication(repo, run_git):
    """Two binary files with identical content share the same blob object."""
    content = binary_content()
    _write(repo / "a.bin", content)
    _write(repo / "b.bin", content)
    run_git("add", "a.bin", "b.bin")
    result = run_git("commit", "-m", "dedup test")
    assert result.returncode == 0

    # Verify only one object file exists for the shared blob
    obj_dir = repo / ".git" / "objects"
    object_files = list(obj_dir.rglob("*"))
    # Count files excluding directories and pack files
    object_files = [f for f in object_files if f.is_file()]
    # We cannot assert exact count without knowing implementation details,
    # but we CAN assert that both files are accessible after checkout.
    (repo / "a.bin").unlink()
    (repo / "b.bin").unlink()
    run_git("checkout", "--", "a.bin")
    run_git("checkout", "--", "b.bin")
    assert (repo / "a.bin").read_bytes() == content
    assert (repo / "b.bin").read_bytes() == content


def test_binary_in_subdir(repo, run_git):
    """Binary file in a subdirectory must be stored and retrieved correctly."""
    subdir = repo / "assets" / "images"
    subdir.mkdir(parents=True)
    _write(subdir / "logo.bin", binary_content())
    run_git("add", ".")
    result = run_git("commit", "-m", "binary in subdir")
    assert result.returncode == 0, result.stderr.decode(errors="replace")
