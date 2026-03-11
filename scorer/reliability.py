"""Reliability scorer — runs chaos scenario tests against a submission."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

from scorer.behavioral import _find_cmd, _harness_cmd_var, _run_pytest_tier


@dataclass
class ReliabilityResult:
    passed: int
    failed: int
    total: int
    score: float  # 0-100
    failures: list[dict[str, str]] = field(default_factory=list)
    notes: str = ""


def run_reliability(
    submission_path: Path,
    harness_path: Path,
    python: str = sys.executable,
    timeout: int = 300,
) -> ReliabilityResult:
    """Run reliability/chaos tests against the submission."""
    submission_path = Path(submission_path)
    harness_path = Path(harness_path)
    tests_root = harness_path / "tests"
    reliability_path = tests_root / "reliability"

    if not reliability_path.exists():
        return ReliabilityResult(
            passed=0, failed=0, total=0, score=0.0,
            notes="Reliability test directory not found.",
        )

    harness_name = harness_path.name
    cmd_var = _harness_cmd_var(harness_name)
    impl_cmd = _find_cmd(submission_path / "workspace", harness_name)
    tier_result = _run_pytest_tier(
        tier_path=reliability_path,
        tests_root=tests_root,
        impl_cmd=impl_cmd,
        cmd_var=cmd_var,
        python=python,
        timeout=timeout,
    )

    return ReliabilityResult(
        passed=tier_result.passed,
        failed=tier_result.failed,
        total=tier_result.total,
        score=tier_result.score,
        failures=tier_result.failures,
    )
