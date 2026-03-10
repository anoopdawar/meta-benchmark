"""
Adversarial tests: unusual, shell-hostile, and boundary-condition filenames.

These tests verify that mini-git correctly handles filenames that could trip
up implementations that use shell expansion, string splitting, or naive
path handling.
"""
import os
import sys

import pytest

from .conftest import MINI_GIT_CMD, _skip_if_no_cmd

pytestmark = pytest.mark.skipif(
    not MINI_GIT_CMD, reason="MINI_GIT_CMD not set"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_and_add(repo, run_git, fname: str, content: bytes = b"test\n"):
    """Create *fname* in *repo* and stage it. Skip if the OS rejects the name."""
    try:
        p = repo / fname
        p.write_bytes(content)
    except (OSError, ValueError) as exc:
        pytest.skip(f"OS rejected filename {fname!r}: {exc}")
    result = run_git("add", fname)
    return result


# ---------------------------------------------------------------------------
# Spaces
# ---------------------------------------------------------------------------

def test_filename_with_spaces(repo, run_git):
    """Filename containing spaces must be addable and committable."""
    result = _create_and_add(repo, run_git, "my file.txt")
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    r = run_git("commit", "-m", "add file with spaces")
    assert r.returncode == 0, r.stderr.decode(errors="replace")


def test_filename_with_leading_trailing_spaces(repo, run_git):
    """Filenames with leading or trailing spaces (unusual but valid on some FS)."""
    _create_and_add(repo, run_git, " leading.txt")
    r = run_git("commit", "-m", "leading space")
    assert r.returncode in (0, 1)  # may reject — must not crash internally


def test_filename_with_multiple_spaces(repo, run_git):
    """Multiple consecutive spaces in a filename."""
    result = _create_and_add(repo, run_git, "hello   world.txt")
    assert result.returncode == 0, result.stderr.decode(errors="replace")


# ---------------------------------------------------------------------------
# Quotes
# ---------------------------------------------------------------------------

def test_filename_with_single_quote(repo, run_git):
    """Single-quote in filename must not confuse the CLI parser."""
    result = _create_and_add(repo, run_git, "it's a test.txt")
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    r = run_git("commit", "-m", "single quote filename")
    assert r.returncode == 0


def test_filename_with_double_quote(repo, run_git):
    """Double-quote in filename must be handled."""
    fname = 'say "hello".txt'
    result = _create_and_add(repo, run_git, fname)
    assert result.returncode == 0, result.stderr.decode(errors="replace")


def test_filename_with_backtick(repo, run_git):
    """Backtick in filename must not trigger shell command substitution."""
    fname = "`whoami`.txt"
    result = _create_and_add(repo, run_git, fname)
    assert result.returncode == 0, result.stderr.decode(errors="replace")


# ---------------------------------------------------------------------------
# Dash / flag-like names
# ---------------------------------------------------------------------------

def test_filename_starts_with_dash(repo, run_git):
    """Filename starting with '-' looks like a CLI flag."""
    result = _create_and_add(repo, run_git, "-myfile.txt")
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    r = run_git("commit", "-m", "dash filename")
    assert r.returncode == 0


def test_filename_double_dash(repo, run_git):
    """Filename '--help' looks like end-of-options sentinel."""
    result = _create_and_add(repo, run_git, "--help")
    assert result.returncode == 0, result.stderr.decode(errors="replace")


def test_filename_single_dash(repo, run_git):
    """Filename '-' (often means stdin) must be handled."""
    result = _create_and_add(repo, run_git, "-")
    # Implementation may reject '-' as a filename — must not crash
    assert result.returncode in (0, 1)


# ---------------------------------------------------------------------------
# Shell special characters
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("char,label", [
    ("$", "dollar"),
    ("!", "exclamation"),
    ("&", "ampersand"),
    (";", "semicolon"),
    ("*", "asterisk"),
    ("?", "question_mark"),
    ("[", "open_bracket"),
    ("]", "close_bracket"),
    ("(", "open_paren"),
    (")", "close_paren"),
    ("{", "open_brace"),
    ("}", "close_brace"),
    ("|", "pipe"),
    ("<", "less_than"),
    (">", "greater_than"),
    ("~", "tilde"),
    ("^", "caret"),
    ("#", "hash"),
    ("@", "at"),
    ("%", "percent"),
])
def test_filename_special_char(repo, run_git, char, label):
    """Each shell-special character can appear in a filename."""
    fname = f"file{char}test.txt"
    result = _create_and_add(repo, run_git, fname)
    assert result.returncode == 0, (
        f"[{label}] git add of {fname!r} failed: {result.stderr.decode(errors='replace')}"
    )


# ---------------------------------------------------------------------------
# Hidden / dot files
# ---------------------------------------------------------------------------

def test_filename_dot_hidden(repo, run_git):
    """Hidden file starting with '.' must be addable."""
    result = _create_and_add(repo, run_git, ".hidden")
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    r = run_git("commit", "-m", "hidden file")
    assert r.returncode == 0


def test_filename_dotfile_variants(repo, run_git):
    """Various dot-prefixed filenames must be handled."""
    for fname in [".env", ".gitignore2", ".bashrc_custom", "..hidden"]:
        _create_and_add(repo, run_git, fname)
    r = run_git("commit", "-m", "dotfiles")
    assert r.returncode == 0


def test_filename_double_dot_rejected(repo, run_git):
    """'..' must never be a valid add target (path traversal)."""
    result = run_git("add", "..")
    # Must fail — adding '..' should not succeed
    assert result.returncode != 0, "git add .. must fail"


# ---------------------------------------------------------------------------
# Length boundary tests
# ---------------------------------------------------------------------------

def test_filename_long_255(repo, run_git):
    """255-character filename (max on most filesystems) must work."""
    fname = "a" * 251 + ".txt"  # 255 chars total
    assert len(fname) == 255
    result = _create_and_add(repo, run_git, fname)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    r = run_git("commit", "-m", "255 char filename")
    assert r.returncode == 0


def test_filename_very_long_over_255(repo, run_git):
    """Filename > 255 chars must fail gracefully (OS will reject it)."""
    fname = "b" * 300 + ".txt"
    try:
        (repo / fname).write_bytes(b"content")
        # If OS allowed it (unusual), try to add
        result = run_git("add", fname)
        # May succeed or fail — must not crash
        assert result.returncode in (0, 1)
    except OSError:
        pass  # Expected: OS rejected the filename


# ---------------------------------------------------------------------------
# Path traversal
# ---------------------------------------------------------------------------

def test_path_traversal_rejected(repo, run_git):
    """Path traversal via '../../escape' must be rejected by mini-git."""
    result = run_git("add", "../../escape")
    assert result.returncode != 0, "Path traversal must be rejected"


def test_path_traversal_with_dotdot_in_middle(repo, run_git):
    """Path like 'subdir/../../../etc/passwd' must be rejected."""
    result = run_git("add", "subdir/../../../etc/passwd")
    assert result.returncode != 0, "Path traversal via middle ../ must be rejected"


# ---------------------------------------------------------------------------
# Git-related filenames
# ---------------------------------------------------------------------------

def test_filename_gitignore_variant(repo, run_git):
    """Files named '.gitignore2', 'gitconfig', 'git-hook' must be addable."""
    for fname in [".gitignore2", "gitconfig", "git-hook", "git_config"]:
        _create_and_add(repo, run_git, fname)
    r = run_git("commit", "-m", "git-like filenames")
    assert r.returncode == 0


def test_filename_nested_git_dir(repo, run_git):
    """A path component named '.git' that is not the root .git must be handled."""
    # Create a file whose path contains '.git' as a directory name
    fake_git = repo / "src" / ".git" / "config"
    try:
        fake_git.parent.mkdir(parents=True)
        fake_git.write_bytes(b"not a real git config\n")
    except OSError:
        pytest.skip("OS rejected nested .git dir")
    result = run_git("add", ".")
    # Implementation may refuse or accept — must not silently corrupt
    assert result.returncode in (0, 1)


# ---------------------------------------------------------------------------
# Newline in filename
# ---------------------------------------------------------------------------

def test_filename_newline_rejected(repo, run_git):
    """Filename with newline character must be rejected gracefully."""
    fname = "file\nname.txt"
    try:
        (repo / fname).write_bytes(b"content")
        result = run_git("add", fname)
        assert result.returncode in (0, 1)  # May succeed on unusual FS
    except (OSError, ValueError):
        pass  # Expected: OS rejected the name


# ---------------------------------------------------------------------------
# Null byte in filename
# ---------------------------------------------------------------------------

def test_filename_null_byte_rejected(repo, run_git):
    """Filename with embedded NUL byte must be rejected gracefully."""
    fname = "file\x00name.txt"
    try:
        (repo / fname).write_bytes(b"content")
        result = run_git("add", fname)
        assert result.returncode in (0, 1)
    except (OSError, ValueError, TypeError):
        pass  # Expected: Python/OS rejects NUL in path
