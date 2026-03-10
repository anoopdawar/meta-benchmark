"""
conftest.py — shared fixtures and helpers for mini-git behavioral tests.

Environment variable:
    MINI_GIT_CMD — path/command for the mini-git implementation.
                   Defaults to discovering mini_git.py or mini_git binary
                   in the current working directory.

All tests skip gracefully when no implementation is found.
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Sequence, Union

import pytest

# ---------------------------------------------------------------------------
# Implementation discovery
# ---------------------------------------------------------------------------

def _discover_mini_git_cmd() -> Optional[List[str]]:
    """Return the command list to invoke mini-git, or None if not found."""
    env_cmd = os.environ.get("MINI_GIT_CMD")
    if env_cmd:
        return env_cmd.split()

    # Try common locations relative to the repo root.
    candidates = [
        Path("mini_git.py"),
        Path("mini_git"),
        Path("harnesses/mini-git/mini_git.py"),
        Path("harnesses/mini-git/mini_git"),
    ]
    for candidate in candidates:
        if candidate.exists():
            if candidate.suffix == ".py":
                return ["python", str(candidate.resolve())]
            return [str(candidate.resolve())]

    return None


_MINI_GIT_CMD: Optional[List[str]] = _discover_mini_git_cmd()


# ---------------------------------------------------------------------------
# Session-scoped skip marker
# ---------------------------------------------------------------------------

def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "requires_impl: skip if no mini-git implementation is found",
    )


# ---------------------------------------------------------------------------
# Public helpers (importable by test modules)
# ---------------------------------------------------------------------------

def run_git(
    cmd: Union[str, Sequence[str]],
    cwd: Union[str, Path],
    input: Optional[str] = None,
    env: Optional[dict] = None,
) -> subprocess.CompletedProcess:
    """
    Run the mini-git command with *cmd* appended, in directory *cwd*.

    ``cmd`` may be a string (split on spaces) or a list of strings.

    Returns a CompletedProcess regardless of exit code — callers must assert
    on result.returncode themselves (or use assert_success / assert_failure).
    """
    if _MINI_GIT_CMD is None:
        pytest.skip("No mini-git implementation found (set MINI_GIT_CMD)")

    if isinstance(cmd, str):
        args = cmd.split()
    else:
        args = list(cmd)

    full_cmd = _MINI_GIT_CMD + args
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)

    return subprocess.run(
        full_cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        input=input,
        env=merged_env,
    )


def assert_success(result: subprocess.CompletedProcess) -> None:
    """Assert that *result* exited with code 0."""
    assert result.returncode == 0, (
        f"Expected success (exit 0) but got exit {result.returncode}.\n"
        f"stdout: {result.stdout!r}\n"
        f"stderr: {result.stderr!r}"
    )


def assert_failure(result: subprocess.CompletedProcess) -> None:
    """Assert that *result* exited with a non-zero code."""
    assert result.returncode != 0, (
        f"Expected failure (non-zero exit) but got exit 0.\n"
        f"stdout: {result.stdout!r}\n"
        f"stderr: {result.stderr!r}"
    )


def make_commit(
    repo: Path,
    message: str,
    files: dict,
) -> str:
    """
    Write *files* (mapping path→content), stage them, and commit with *message*.

    Returns the combined stdout+stderr of the commit command for inspection.
    """
    for rel_path, content in files.items():
        target = repo / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content)

    paths = list(files.keys())
    add_result = run_git(["add"] + paths, cwd=repo)
    assert_success(add_result)

    commit_result = run_git(["commit", "-m", message], cwd=repo)
    assert_success(commit_result)

    return commit_result.stdout + commit_result.stderr


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """
    Yield a temporary directory that has been initialised with ``mini-git init``.

    The directory is automatically removed after the test.
    """
    if _MINI_GIT_CMD is None:
        pytest.skip("No mini-git implementation found (set MINI_GIT_CMD)")

    result = run_git("init", cwd=tmp_path)
    assert_success(result)
    yield tmp_path
