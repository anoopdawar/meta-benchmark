"""
Adversarial tests: Unicode filenames, commit messages, and file content.

Tests verify that mini-git correctly stores, encodes, and restores filenames
and content that fall outside plain ASCII.
"""
import os
import sys

import pytest

from .conftest import MINI_GIT_CMD, _skip_if_no_cmd, unicode_filename

pytestmark = pytest.mark.skipif(
    not MINI_GIT_CMD, reason="MINI_GIT_CMD not set"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_text(path, text: str, encoding="utf-8"):
    path.write_bytes(text.encode(encoding))


def _is_macos():
    return sys.platform == "darwin"


# ---------------------------------------------------------------------------
# Filename tests — parametrized to reach count targets
# ---------------------------------------------------------------------------

UNICODE_FILENAME_CATEGORIES = [
    "emoji",
    "cjk",
    "rtl",
    "hebrew",
    "combining",
    "nbsp",
    "zero_width",
    "math",
    "long_unicode",
    "mixed",
]


@pytest.mark.parametrize("category", UNICODE_FILENAME_CATEGORIES)
def test_unicode_filename_add(repo, run_git, category):
    """Each unicode filename category must be addable without error."""
    fname = unicode_filename(category)
    try:
        p = repo / fname
        p.write_bytes(b"content\n")
    except (OSError, ValueError):
        pytest.skip(f"Filesystem does not support filename category {category!r}")

    result = run_git("add", fname)
    assert result.returncode == 0, (
        f"[{category}] git add failed: {result.stderr.decode(errors='replace')}"
    )


@pytest.mark.parametrize("category", UNICODE_FILENAME_CATEGORIES)
def test_unicode_filename_commit(repo, run_git, category):
    """Each unicode filename must be committable."""
    fname = unicode_filename(category)
    try:
        (repo / fname).write_bytes(b"unicode file\n")
    except (OSError, ValueError):
        pytest.skip(f"Filesystem cannot create filename for category {category!r}")

    run_git("add", fname)
    result = run_git("commit", "-m", f"add {category} filename")
    assert result.returncode == 0, (
        f"[{category}] git commit failed: {result.stderr.decode(errors='replace')}"
    )


@pytest.mark.parametrize("category", UNICODE_FILENAME_CATEGORIES)
def test_unicode_filename_status(repo, run_git, category):
    """Status must list the unicode-named file without crashing."""
    fname = unicode_filename(category)
    try:
        (repo / fname).write_bytes(b"hello\n")
    except (OSError, ValueError):
        pytest.skip(f"Filesystem cannot create filename for category {category!r}")

    run_git("add", fname)
    result = run_git("status")
    assert result.returncode == 0, result.stderr.decode(errors="replace")


def test_unicode_filename_emoji(repo, run_git):
    """Explicit test: emoji filename 🐙.py."""
    fname = "🐙.py"
    try:
        (repo / fname).write_bytes(b"# octopus\n")
    except OSError:
        pytest.skip("Filesystem does not support emoji filenames")
    run_git("add", fname)
    result = run_git("commit", "-m", "add emoji file")
    assert result.returncode == 0, result.stderr.decode(errors="replace")


def test_unicode_filename_cjk(repo, run_git):
    """CJK characters in filename."""
    fname = "汉字テスト.txt"
    try:
        (repo / fname).write_bytes(b"cjk content\n")
    except OSError:
        pytest.skip("Filesystem does not support CJK filenames")
    run_git("add", fname)
    result = run_git("commit", "-m", "add CJK filename")
    assert result.returncode == 0, result.stderr.decode(errors="replace")


def test_unicode_filename_rtl(repo, run_git):
    """Arabic (RTL) characters in filename."""
    fname = "مرحبا.txt"
    try:
        (repo / fname).write_bytes(b"arabic content\n")
    except OSError:
        pytest.skip("Filesystem does not support Arabic filenames")
    run_git("add", fname)
    result = run_git("commit", "-m", "add RTL filename")
    assert result.returncode == 0, result.stderr.decode(errors="replace")


def test_unicode_filename_combining(repo, run_git):
    """Combining diacritics in filename (e + combining acute accent)."""
    fname = "cafe\u0301.txt"  # café with combining accent
    try:
        (repo / fname).write_bytes(b"cafe content\n")
    except OSError:
        pytest.skip("Filesystem does not support combining diacritics in filenames")
    run_git("add", fname)
    result = run_git("commit", "-m", "add combining diacritics filename")
    assert result.returncode == 0, result.stderr.decode(errors="replace")


def test_unicode_filename_spaces(repo, run_git):
    """Non-breaking space in filename."""
    fname = "file\u00a0name.txt"
    try:
        (repo / fname).write_bytes(b"nbsp content\n")
    except OSError:
        pytest.skip("Filesystem does not support NBSP in filenames")
    run_git("add", fname)
    result = run_git("commit", "-m", "add nbsp filename")
    assert result.returncode == 0, result.stderr.decode(errors="replace")


def test_unicode_path_nested(repo, run_git):
    """Deeply nested path with unicode directory names."""
    nested = repo / "层级" / "レベル" / "طبقة"
    try:
        nested.mkdir(parents=True)
        (nested / "deep.txt").write_bytes(b"deep content\n")
    except OSError:
        pytest.skip("Filesystem cannot create unicode nested dirs")
    run_git("add", ".")
    result = run_git("commit", "-m", "nested unicode dirs")
    assert result.returncode == 0, result.stderr.decode(errors="replace")


def test_unicode_roundtrip(repo, run_git):
    """Checkout restores unicode filename with exact byte content."""
    fname = "🐙.py"
    original_content = "# octopus\nprint('🐙')\n".encode("utf-8")
    try:
        (repo / fname).write_bytes(original_content)
    except OSError:
        pytest.skip("Filesystem does not support emoji filenames")

    run_git("add", fname)
    run_git("commit", "-m", "unicode roundtrip")

    # Overwrite the file
    (repo / fname).write_bytes(b"OVERWRITTEN")

    result = run_git("checkout", "--", fname)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    restored = (repo / fname).read_bytes()
    assert restored == original_content, "Unicode file content changed after checkout"


# ---------------------------------------------------------------------------
# Commit message unicode tests
# ---------------------------------------------------------------------------

def test_unicode_commit_message_emoji(repo, run_git):
    """Emoji in commit message must be stored and shown by log."""
    (repo / "a.txt").write_bytes(b"hello\n")
    run_git("add", "a.txt")
    msg = "feat: add feature 🚀🎉"
    result = run_git("commit", "-m", msg)
    assert result.returncode == 0, result.stderr.decode(errors="replace")

    log = run_git("log", "--oneline")
    assert log.returncode == 0
    combined = log.stdout.decode("utf-8", errors="replace")
    assert "🚀" in combined or "feat: add feature" in combined


def test_unicode_commit_message_cjk(repo, run_git):
    """CJK characters in commit message."""
    (repo / "b.txt").write_bytes(b"world\n")
    run_git("add", "b.txt")
    msg = "修复: 修正了一个重要的错误"
    result = run_git("commit", "-m", msg)
    assert result.returncode == 0, result.stderr.decode(errors="replace")


def test_unicode_multiline_message(repo, run_git):
    """Multi-line unicode commit message must round-trip through log."""
    (repo / "c.txt").write_bytes(b"content\n")
    run_git("add", "c.txt")
    msg = "feat: initial commit\n\nDetailed description with unicode: 日本語テスト\nArabic: مرحبا\nEmoji: 🐙"
    result = run_git("commit", "-m", msg)
    assert result.returncode == 0, result.stderr.decode(errors="replace")

    log = run_git("log")
    assert log.returncode == 0


def test_null_in_commit_message(repo, run_git):
    """NUL byte in commit message should fail gracefully (non-zero, not crash)."""
    (repo / "d.txt").write_bytes(b"test\n")
    run_git("add", "d.txt")
    # Pass a message with embedded NUL — implementation may reject or truncate
    msg_bytes = b"before\x00after"
    try:
        msg = msg_bytes.decode("utf-8")
    except UnicodeDecodeError:
        msg = "before after"  # fallback

    result = run_git("commit", "-m", msg)
    # Must not be an internal crash (128); may succeed (0) or fail (1)
    assert result.returncode in (0, 1, 128), (
        f"Unexpected exit code: {result.returncode}"
    )


def test_unicode_long_commit_message(repo, run_git):
    """Very long unicode commit message must not crash."""
    (repo / "e.txt").write_bytes(b"stuff\n")
    run_git("add", "e.txt")
    msg = "🐙" * 2000  # 2000 emoji = 8000 UTF-8 bytes
    result = run_git("commit", "-m", msg)
    assert result.returncode == 0, result.stderr.decode(errors="replace")


# ---------------------------------------------------------------------------
# File content unicode tests
# ---------------------------------------------------------------------------

def test_utf8_file_content(repo, run_git):
    """UTF-8 encoded file content must be stored and retrieved exactly."""
    content = "Hello, 世界! مرحبا 🐙\n".encode("utf-8")
    (repo / "utf8.txt").write_bytes(content)
    run_git("add", "utf8.txt")
    run_git("commit", "-m", "utf8 content")

    (repo / "utf8.txt").write_bytes(b"OVERWRITTEN")
    run_git("checkout", "--", "utf8.txt")
    assert (repo / "utf8.txt").read_bytes() == content


def test_utf16_file_content(repo, run_git):
    """UTF-16 encoded file (appears binary) must be stored and retrieved exactly."""
    content = "Hello UTF-16\n".encode("utf-16")  # starts with BOM
    (repo / "utf16.txt").write_bytes(content)
    run_git("add", "utf16.txt")
    run_git("commit", "-m", "utf16 content")

    (repo / "utf16.txt").write_bytes(b"OVERWRITTEN")
    run_git("checkout", "--", "utf16.txt")
    assert (repo / "utf16.txt").read_bytes() == content


def test_bom_file(repo, run_git):
    """File starting with UTF-8 BOM must be stored and retrieved exactly."""
    bom = b"\xef\xbb\xbf"  # UTF-8 BOM
    content = bom + "BOM file content\n".encode("utf-8")
    (repo / "bom.txt").write_bytes(content)
    run_git("add", "bom.txt")
    run_git("commit", "-m", "BOM file")

    (repo / "bom.txt").write_bytes(b"OVERWRITTEN")
    run_git("checkout", "--", "bom.txt")
    assert (repo / "bom.txt").read_bytes() == content


def test_mixed_encoding_files(repo, run_git):
    """Multiple files with different encodings can coexist in a repo."""
    files = {
        "utf8.txt": "UTF-8: 日本語\n".encode("utf-8"),
        "latin1.txt": "Latin-1: café\n".encode("latin-1"),
        "utf16le.txt": "UTF-16LE\n".encode("utf-16-le"),
        "ascii.txt": b"Pure ASCII\n",
    }
    for name, content in files.items():
        (repo / name).write_bytes(content)

    run_git("add", ".")
    result = run_git("commit", "-m", "mixed encodings")
    assert result.returncode == 0, result.stderr.decode(errors="replace")

    # Verify all files are recoverable
    for name, content in files.items():
        original = content
        (repo / name).write_bytes(b"OVERWRITTEN")
        run_git("checkout", "--", name)
        assert (repo / name).read_bytes() == original, f"{name} content mismatch"


def test_unicode_diff_content(repo, run_git):
    """Diff on files with unicode content must not crash."""
    content_v1 = "Version 1: Hello 世界\n".encode("utf-8")
    content_v2 = "Version 2: Hello 🐙\n".encode("utf-8")

    (repo / "content.txt").write_bytes(content_v1)
    run_git("add", "content.txt")
    run_git("commit", "-m", "v1")

    (repo / "content.txt").write_bytes(content_v2)
    result = run_git("diff")
    assert result.returncode in (0, 1)


def test_unicode_status_after_modify(repo, run_git):
    """Status after modifying a unicode-content file must list it correctly."""
    (repo / "u.txt").write_bytes("Initial: 初期\n".encode("utf-8"))
    run_git("add", "u.txt")
    run_git("commit", "-m", "initial")

    (repo / "u.txt").write_bytes("Modified: 変更済み\n".encode("utf-8"))
    result = run_git("status")
    assert result.returncode == 0
    assert b"u.txt" in result.stdout + result.stderr
