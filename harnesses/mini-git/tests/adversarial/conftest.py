"""
Adversarial test fixtures for mini-git.

If a parent conftest.py exists at the tests/ level with a `run_git` fixture or
`repo` fixture, those are inherited automatically by pytest. This file adds
adversarial-specific helpers on top.
"""
import os
import shutil
import subprocess
import tempfile

import pytest

# ---------------------------------------------------------------------------
# Environment / skip guard
# ---------------------------------------------------------------------------

MINI_GIT_CMD = os.environ.get("MINI_GIT_CMD", "")


def _skip_if_no_cmd():
    if not MINI_GIT_CMD:
        pytest.skip("MINI_GIT_CMD is not set — skipping mini-git integration test")


# ---------------------------------------------------------------------------
# Core fixtures (used when no parent conftest provides them)
# ---------------------------------------------------------------------------


@pytest.fixture()
def repo(tmp_path):
    """Initialize a fresh mini-git repository and return its path."""
    _skip_if_no_cmd()
    result = subprocess.run(
        MINI_GIT_CMD.split() + ["init", str(tmp_path)],
        capture_output=True,
        text=False,
    )
    if result.returncode != 0:
        pytest.fail(
            f"git init failed: {result.stderr.decode(errors='replace')}"
        )
    return tmp_path


@pytest.fixture()
def run_git(repo):
    """Return a helper that runs mini-git in the repo directory."""

    def _run(*args, check=False, input=None, text=False, cwd=None):
        cmd = MINI_GIT_CMD.split() + list(str(a) for a in args)
        return subprocess.run(
            cmd,
            capture_output=True,
            text=text,
            input=input,
            cwd=cwd or repo,
        )

    return _run


# ---------------------------------------------------------------------------
# Content helpers
# ---------------------------------------------------------------------------


def binary_content() -> bytes:
    """
    Return a byte string that contains NUL bytes and non-UTF-8 sequences.
    This is deliberately un-decodable as UTF-8 text.
    """
    nul_segment = b"\x00" * 16
    non_utf8 = bytes(range(128, 256))  # raw high bytes
    valid_ascii = b"BINARY_CONTENT_MARKER"
    return valid_ascii + nul_segment + non_utf8 + b"\x00\xff\xfe\xfd"


def unicode_filename(category: str) -> str:
    """
    Return a filename for the given unicode category.

    Categories
    ----------
    emoji          : 🐙.py
    cjk            : 汉字テスト한국어.txt
    rtl            : مرحبا.txt  (Arabic)
    hebrew         : שלום.txt
    combining      : café.txt  (e + combining acute accent)
    nbsp           : file\u00a0name.txt  (non-breaking space)
    zero_width     : file\u200bname.txt  (zero-width space)
    math           : ∑∆∏.txt
    long_unicode   : 256 chars of 'ä'
    mixed          : mix_🐙_汉_مرحبا.txt
    """
    mapping = {
        "emoji": "🐙.py",
        "cjk": "汉字テスト한국어.txt",
        "rtl": "مرحبا.txt",
        "hebrew": "שלום.txt",
        "combining": "cafe\u0301.txt",  # e + combining acute
        "nbsp": "file\u00a0name.txt",
        "zero_width": "file\u200bname.txt",
        "math": "∑∆∏.txt",
        "long_unicode": ("ä" * 63) + ".txt",  # 63 × 2-byte char + 4 = 130 bytes, safe FS
        "mixed": "mix_🐙_汉_مرحبا.txt",
    }
    if category not in mapping:
        raise ValueError(f"Unknown unicode category: {category!r}")
    return mapping[category]
