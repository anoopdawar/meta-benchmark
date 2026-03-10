"""Adversarial scorer — runs edge case battery against a submission."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from scorer.behavioral import _find_mini_git_cmd, _run_pytest_tier, TierResult


@dataclass
class AdversarialResult:
    passed: int
    failed: int
    total: int
    survival_rate: float  # 0-100
    score: float  # 0-100 (same as survival_rate)
    failures: list[dict[str, str]] = field(default_factory=list)


def run_adversarial(
    submission_path: Path,
    harness_path: Path,
    python: str = sys.executable,
    timeout: int = 300,
) -> AdversarialResult:
    """Run adversarial edge case tests against the submission."""
    submission_path = Path(submission_path)
    harness_path = Path(harness_path)
    tests_root = harness_path / "tests"
    adversarial_path = tests_root / "adversarial"

    if not adversarial_path.exists():
        return AdversarialResult(
            passed=0, failed=0, total=0, survival_rate=0.0, score=0.0,
        )

    mini_git_cmd = _find_mini_git_cmd(submission_path / "workspace")
    tier_result: TierResult = _run_pytest_tier(
        tier_path=adversarial_path,
        tests_root=tests_root,
        mini_git_cmd=mini_git_cmd,
        python=python,
        timeout=timeout,
    )

    survival_rate = tier_result.score  # Already 0-100
    return AdversarialResult(
        passed=tier_result.passed,
        failed=tier_result.failed,
        total=tier_result.total,
        survival_rate=round(survival_rate, 2),
        score=round(survival_rate, 2),
        failures=tier_result.failures,
    )
