"""
Mutation scorer — measures how well the agent's own tests catch code mutations.

Uses mutmut (preferred) or cosmic-ray. Falls back gracefully if no tests exist.

Mutation kill rate = (mutations killed) / (total mutations) * 100
A high kill rate means the tests actually verify the implementation's logic.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass
class MutationResult:
    killed: int
    survived: int
    total: int
    kill_rate: float  # 0-100
    score: float  # 0-100
    method: str  # "mutmut", "cosmic_ray", or "unavailable"
    notes: str = ""


def run_mutation(
    submission_path: Path,
    python: str = sys.executable,
    timeout: int = 600,
    max_mutations: int = 200,
) -> MutationResult:
    """
    Run mutation testing against the agent's implementation and its own tests.

    Tries mutmut first, then cosmic-ray. Falls back to a no-op result if
    no tests are found in the submission.
    """
    submission_path = Path(submission_path)
    workspace = submission_path / "workspace"

    # Find agent tests
    agent_tests = list(workspace.rglob("test_*.py")) + list(workspace.rglob("*_test.py"))
    if not agent_tests:
        return MutationResult(
            killed=0, survived=0, total=0, kill_rate=0.0, score=0.0,
            method="unavailable",
            notes="No test files found in submission workspace. Mutation score is 0.",
        )

    # Try mutmut
    if shutil.which("mutmut"):
        return _run_mutmut(workspace, python, timeout, max_mutations)

    # Try cosmic-ray
    if shutil.which("cosmic-ray") or shutil.which("cr"):
        return _run_cosmic_ray(workspace, python, timeout, max_mutations)

    return MutationResult(
        killed=0, survived=0, total=0, kill_rate=0.0, score=0.0,
        method="unavailable",
        notes="Neither mutmut nor cosmic-ray found. Install one to enable mutation scoring.",
    )


def _run_mutmut(workspace: Path, python: str, timeout: int, max_mutations: int) -> MutationResult:
    """Run mutmut and parse results."""
    # Find source files (exclude tests)
    src_files = [
        str(p) for p in workspace.rglob("*.py")
        if "test" not in p.name.lower() and p.is_file()
    ]
    if not src_files:
        return MutationResult(
            killed=0, survived=0, total=0, kill_rate=0.0, score=0.0,
            method="mutmut",
            notes="No source files found (only test files present).",
        )

    try:
        # Run mutmut
        result = subprocess.run(
            ["mutmut", "run", f"--paths-to-mutate={','.join(src_files)}"],
            cwd=str(workspace),
            capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "PYTHONPATH": str(workspace)},
        )

        # Get results
        results_proc = subprocess.run(
            ["mutmut", "results"],
            cwd=str(workspace),
            capture_output=True, text=True, timeout=30,
        )

        killed = _count_in_output(results_proc.stdout, "killed")
        survived = _count_in_output(results_proc.stdout, "survived")
        total = killed + survived

        kill_rate = (killed / total * 100) if total > 0 else 0.0
        return MutationResult(
            killed=killed, survived=survived, total=total,
            kill_rate=round(kill_rate, 2), score=round(kill_rate, 2),
            method="mutmut",
        )
    except subprocess.TimeoutExpired:
        return MutationResult(
            killed=0, survived=0, total=0, kill_rate=0.0, score=0.0,
            method="mutmut", notes=f"mutmut timed out after {timeout}s",
        )
    except Exception as e:
        return MutationResult(
            killed=0, survived=0, total=0, kill_rate=0.0, score=0.0,
            method="mutmut", notes=f"mutmut error: {e}",
        )


def _run_cosmic_ray(workspace: Path, python: str, timeout: int, max_mutations: int) -> MutationResult:
    """Run cosmic-ray and parse results. Stub — returns unavailable if config not ready."""
    return MutationResult(
        killed=0, survived=0, total=0, kill_rate=0.0, score=0.0,
        method="cosmic_ray",
        notes="cosmic-ray integration not yet configured. Run mutmut for mutation scoring.",
    )


def _count_in_output(text: str, keyword: str) -> int:
    """Count occurrences of lines containing a keyword with a leading number."""
    import re
    total = 0
    for line in text.splitlines():
        if keyword in line.lower():
            match = re.search(r"(\d+)", line)
            if match:
                total += int(match.group(1))
    return total
