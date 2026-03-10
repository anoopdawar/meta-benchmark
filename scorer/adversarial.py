"""Adversarial scorer — runs edge case battery against a submission.

Includes held-out tests if harnesses/*/tests/held-out/ exists locally.
Held-out tests are never committed to the public repo — they exist only on
the maintainer's machine and run automatically when present.
"""

from __future__ import annotations

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
    held_out_passed: int = 0
    held_out_total: int = 0
    verified: bool = False  # True when held-out tests were run
    failures: list[dict[str, str]] = field(default_factory=list)


def run_adversarial(
    submission_path: Path,
    harness_path: Path,
    python: str = sys.executable,
    timeout: int = 300,
) -> AdversarialResult:
    """
    Run adversarial edge case tests against the submission.

    Runs the public adversarial suite. If harnesses/*/tests/held-out/ exists
    locally (never committed to the public repo), those tests are also run and
    their results are included in the score. Leaderboard entries scored with
    held-out tests are marked as verified.
    """
    submission_path = Path(submission_path)
    harness_path = Path(harness_path)
    tests_root = harness_path / "tests"
    adversarial_path = tests_root / "adversarial"

    if not adversarial_path.exists():
        return AdversarialResult(
            passed=0, failed=0, total=0, survival_rate=0.0, score=0.0,
        )

    mini_git_cmd = _find_mini_git_cmd(submission_path / "workspace")

    # Public adversarial tests
    public_result: TierResult = _run_pytest_tier(
        tier_path=adversarial_path,
        tests_root=tests_root,
        mini_git_cmd=mini_git_cmd,
        python=python,
        timeout=timeout,
    )

    passed = public_result.passed
    total = public_result.total
    failures = public_result.failures
    held_out_passed = 0
    held_out_total = 0
    verified = False

    # Held-out tests — present only on maintainer machines, never in the public repo
    held_out_path = tests_root / "held-out"
    if held_out_path.exists() and any(held_out_path.glob("test_*.py")):
        ho_result: TierResult = _run_pytest_tier(
            tier_path=held_out_path,
            tests_root=tests_root,
            mini_git_cmd=mini_git_cmd,
            python=python,
            timeout=timeout,
        )
        held_out_passed = ho_result.passed
        held_out_total = ho_result.total
        passed += ho_result.passed
        total += ho_result.total
        failures = failures + ho_result.failures
        verified = True
        print(f"  [held-out] {ho_result.passed}/{ho_result.total} additional adversarial tests passed")

    survival_rate = (passed / total * 100) if total > 0 else 0.0

    return AdversarialResult(
        passed=passed,
        failed=total - passed,
        total=total,
        survival_rate=round(survival_rate, 2),
        score=round(survival_rate, 2),
        held_out_passed=held_out_passed,
        held_out_total=held_out_total,
        verified=verified,
        failures=failures,
    )
