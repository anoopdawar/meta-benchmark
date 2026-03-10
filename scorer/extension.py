"""
Extension scorer — tests whether the initial implementation included remote operations.

Runs the extension test suite (remote add, push, pull, fetch) against the submission.
An agent that builds remote operations in its first response scores well here.

Note: The "second prompt → agent → re-test" flow described in the rubric is not yet
implemented. This scorer measures whether the first response included extension features,
which is a valid proxy for architectural extensibility.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

from scorer.behavioral import _find_mini_git_cmd, _run_pytest_tier


@dataclass
class ExtensionResult:
    passed: int
    failed: int
    total: int
    score: float  # 0-100
    phase: str  # "static" or "live_agent"
    failures: list[dict[str, str]] = field(default_factory=list)


def run_extension(
    submission_path: Path,
    harness_path: Path,
    python: str = sys.executable,
    timeout: int = 300,
    live_agent: bool = False,
) -> ExtensionResult:
    """
    Run extension tests against the submission.

    If live_agent=False (default), runs the extension test suite against
    the current state of the submission. If the submission hasn't implemented
    remote operations, all tests will fail (score = 0).

    If live_agent=True, the extension prompt would be fed to the agent,
    the agent would update the workspace, then tests run. (Not implemented
    in this version — requires runner integration.)
    """
    submission_path = Path(submission_path)
    harness_path = Path(harness_path)
    tests_root = harness_path / "tests"
    extension_path = tests_root / "extension"

    if not extension_path.exists():
        return ExtensionResult(
            passed=0, failed=0, total=0, score=0.0, phase="static",
        )

    if live_agent:
        raise NotImplementedError(
            "Live agent extension testing requires runner integration. "
            "Set live_agent=False to score the current submission state."
        )

    mini_git_cmd = _find_mini_git_cmd(submission_path / "workspace")
    tier_result = _run_pytest_tier(
        tier_path=extension_path,
        tests_root=tests_root,
        mini_git_cmd=mini_git_cmd,
        python=python,
        timeout=timeout,
    )

    # Agent-written tests bonus: if the submission has tests for remote operations,
    # multiply score by 1.1 (capped at 100)
    has_agent_remote_tests = _has_agent_remote_tests(submission_path / "workspace")
    score = tier_result.score
    if has_agent_remote_tests:
        score = min(100.0, score * 1.1)

    return ExtensionResult(
        passed=tier_result.passed,
        failed=tier_result.failed,
        total=tier_result.total,
        score=round(score, 2),
        phase="static",
        failures=tier_result.failures,
    )


def _has_agent_remote_tests(workspace: Path) -> bool:
    """Check if the agent wrote tests for remote operations."""
    for pattern in ["**/test_remote*.py", "**/test_push*.py", "**/test_pull*.py"]:
        if any(workspace.glob(pattern)):
            return True
    return False
