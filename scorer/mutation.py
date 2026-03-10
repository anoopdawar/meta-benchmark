"""
Mutation scorer — measures how well the agent's own tests catch code mutations.

Uses mutmut 2.5+. Falls back gracefully if mutmut is not installed or no tests exist.

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
    method: str  # "mutmut" or "unavailable"
    notes: str = ""


def run_mutation(
    submission_path: Path,
    python: str = sys.executable,
    timeout: int = 600,
    max_mutations: int = 200,
) -> MutationResult:
    """
    Run mutation testing against the agent's implementation and its own tests.

    Uses mutmut 2.5+. Falls back to a zero result if mutmut is not installed
    or no test files are found in the submission.
    """
    submission_path = Path(submission_path)
    workspace = submission_path / "workspace"

    # Find agent tests
    agent_tests = list(workspace.rglob("test_*.py")) + list(workspace.rglob("*_test.py"))
    if not agent_tests:
        return MutationResult(
            killed=0, survived=0, total=0, kill_rate=0.0, score=0.0,
            method="unavailable",
            notes="No test files found in submission workspace.",
        )

    if not shutil.which("mutmut"):
        return MutationResult(
            killed=0, survived=0, total=0, kill_rate=0.0, score=0.0,
            method="unavailable",
            notes="mutmut not installed. Run: pip install 'mutmut<3'",
        )

    return _run_mutmut(workspace, python, timeout, max_mutations)


def _run_mutmut(workspace: Path, python: str, timeout: int, max_mutations: int) -> MutationResult:
    """Run mutmut 2.5+ and parse results from mutants/*.meta files."""
    # Find source files (exclude tests)
    src_files = [
        p.name for p in workspace.glob("*.py")
        if "test" not in p.name.lower()
    ]
    # Also handle package layouts
    for pkg in workspace.iterdir():
        if pkg.is_dir() and (pkg / "__init__.py").exists() and "test" not in pkg.name.lower():
            src_files.append(pkg.name)

    if not src_files:
        return MutationResult(
            killed=0, survived=0, total=0, kill_rate=0.0, score=0.0,
            method="mutmut",
            notes="No source files found to mutate.",
        )

    paths_to_mutate = ",".join(src_files)

    # Write setup.cfg for mutmut config (mutmut 2.5 reads from setup.cfg)
    setup_cfg = workspace / "setup.cfg"
    wrote_config = False
    if not setup_cfg.exists():
        setup_cfg.write_text(
            f"[mutmut]\npaths_to_mutate={paths_to_mutate}\ntests_dir=.\n",
            encoding="utf-8",
        )
        wrote_config = True

    try:
        result = subprocess.run(
            ["mutmut", "run"],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "PYTHONPATH": str(workspace)},
        )

        killed, survived = _parse_mutmut_results(workspace)
        total = killed + survived

        kill_rate = (killed / total * 100) if total > 0 else 0.0
        return MutationResult(
            killed=killed, survived=survived, total=total,
            kill_rate=round(kill_rate, 2),
            score=round(kill_rate, 2),
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
    finally:
        if wrote_config and setup_cfg.exists():
            setup_cfg.unlink()


def _parse_mutmut_results(workspace: Path) -> tuple[int, int]:
    """
    Parse mutmut 2.5+ results from mutants/*.meta JSON files.

    In mutmut 2.5+, each source file gets a .meta file under mutants/ with:
      exit_code_by_key: {mutant_key: exit_code}
    exit_code = 1 → test suite caught the mutation (killed ✅)
    exit_code = 0 → mutation survived (test suite missed it ❌)
    """
    mutants_dir = workspace / "mutants"
    if not mutants_dir.exists():
        return 0, 0

    killed = 0
    survived = 0

    for meta_file in mutants_dir.rglob("*.meta"):
        try:
            data = json.loads(meta_file.read_text(encoding="utf-8"))
            exit_codes = data.get("exit_code_by_key", {})
            for key, code in exit_codes.items():
                if code != 0:
                    killed += 1
                else:
                    survived += 1
        except (json.JSONDecodeError, OSError):
            continue

    return killed, survived
