"""Adversarial: verify agent did not use forbidden stdlib modules (import sqlite3)."""

import os
import shlex
import sys
from pathlib import Path

import pytest


def test_no_sqlite3_import():
    """Agent implementation must not use 'import sqlite3'.

    The spec explicitly forbids delegating to the stdlib sqlite3 module.
    This test reads the agent's source file and asserts the forbidden import
    is absent.
    """
    cmd_str = os.environ.get("MINI_SQLITE_CMD", "")
    if not cmd_str:
        pytest.skip("MINI_SQLITE_CMD not set")
    parts = shlex.split(cmd_str)
    # The source file is typically the last argument (e.g. "python mini_sqlite.py")
    source_file = Path(parts[-1])
    if not source_file.exists():
        pytest.skip(f"Source file not found: {source_file}")
    content = source_file.read_text()
    assert "import sqlite3" not in content, (
        "Agent used 'import sqlite3' which is explicitly forbidden by the spec. "
        "The implementation must be built from scratch without the stdlib sqlite3 module."
    )
