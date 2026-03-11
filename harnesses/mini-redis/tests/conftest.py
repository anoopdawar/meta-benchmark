"""
conftest.py — shared fixtures and helpers for mini-redis tests.

Environment variables:
    MINI_REDIS_CMD  — command to invoke the mini-redis implementation.
    MINI_REDIS_DATA — path to the JSON data file (set per-test via tmp_path).
"""

import os
import shlex
import subprocess
from pathlib import Path
from typing import List, Optional

import pytest


def _discover_cmd() -> Optional[List[str]]:
    env_cmd = os.environ.get("MINI_REDIS_CMD")
    if env_cmd:
        return shlex.split(env_cmd)
    return None


_CMD: Optional[List[str]] = _discover_cmd()
CMD_NOT_FOUND: bool = _CMD is None


def run_redis(args: list, data_path=None) -> subprocess.CompletedProcess:
    """Run mini-redis CLI with args. Returns CompletedProcess (no exit code check)."""
    if _CMD is None:
        pytest.skip("MINI_REDIS_CMD not set")
    env = os.environ.copy()
    if data_path is not None:
        env["MINI_REDIS_DATA"] = str(data_path)
    return subprocess.run(
        _CMD + [str(a) for a in args],
        capture_output=True,
        text=True,
        env=env,
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


@pytest.fixture
def db(tmp_path: Path) -> Path:
    """Path to a fresh mini-redis data file (does not exist yet)."""
    return tmp_path / "mini_redis.json"


@pytest.fixture
def r(db):
    """Shorthand: run a redis command against the tmp db."""
    def _run(*args):
        return run_redis(list(args), data_path=db)
    return _run
