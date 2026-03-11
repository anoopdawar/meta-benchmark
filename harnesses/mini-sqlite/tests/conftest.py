"""
conftest.py — shared fixtures and helpers for mini-sqlite tests.

Environment:
    MINI_SQLITE_CMD — command to invoke mini-sqlite (split with shlex).

Usage in tests:
    def test_something(db, sql):
        r = sql("SELECT * FROM users")
        assert r.returncode == 0
"""

import os
import shlex
import subprocess
from pathlib import Path
from typing import List, Optional

import pytest


def _discover_cmd() -> Optional[List[str]]:
    env_cmd = os.environ.get("MINI_SQLITE_CMD")
    if env_cmd:
        return shlex.split(env_cmd)
    return None


_CMD: Optional[List[str]] = _discover_cmd()
CMD_NOT_FOUND: bool = _CMD is None


def run_sql(db_path: Path, statement: str) -> subprocess.CompletedProcess:
    """Run mini-sqlite with db_path and statement. Returns CompletedProcess."""
    if _CMD is None:
        pytest.skip("MINI_SQLITE_CMD not set")
    return subprocess.run(
        _CMD + [str(db_path), statement],
        capture_output=True,
        text=True,
    )


def assert_success(result: subprocess.CompletedProcess) -> None:
    assert result.returncode == 0, (
        f"Expected exit 0 but got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )


def assert_failure(result: subprocess.CompletedProcess, code: int = 1) -> None:
    assert result.returncode == code, (
        f"Expected exit {code} but got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )


def assert_stdout(result: subprocess.CompletedProcess, expected: str) -> None:
    assert result.stdout.strip() == expected.strip(), (
        f"stdout mismatch.\nExpected: {expected!r}\nGot:      {result.stdout!r}"
    )


def _unescape_pipe(s: str) -> str:
    """Unescape \\| back to | for post-parse processing."""
    return s.replace("\\|", "|")


def parse_rows(result: subprocess.CompletedProcess) -> tuple[list[str], list[list[str]]]:
    """Parse pipe-separated SELECT output. Returns (header_cols, data_rows).

    Splits on unescaped | only. Values containing literal pipes are escaped as
    \\| in the output per the spec; callers receive unescaped values.
    """
    import re
    lines = result.stdout.strip().splitlines()
    if not lines:
        return [], []

    def split_row(line: str) -> list[str]:
        # Split on | not preceded by backslash, then unescape
        parts = re.split(r'(?<!\\)\|', line)
        return [_unescape_pipe(p) for p in parts]

    header = split_row(lines[0])
    rows = [split_row(line) for line in lines[1:]]
    return header, rows


@pytest.fixture
def db(tmp_path: Path) -> Path:
    """Path to a fresh database file (does not exist yet)."""
    return tmp_path / "test.db"


@pytest.fixture
def sql(db):
    """Shorthand: run SQL against the tmp db."""
    def _run(statement: str) -> subprocess.CompletedProcess:
        return run_sql(db, statement)
    return _run
