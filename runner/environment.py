"""Environment provisioning for benchmark runs."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class EnvironmentResult:
    workspace_path: Path
    duration_seconds: float
    file_count: int
    start_time: float
    end_time: float


class Environment:
    """
    Manages the isolated workspace directory for a single benchmark run.

    Each run gets a fresh directory. No state is carried over between runs.
    Git environment variables are cleared so the agent starts with a clean slate.
    """

    # Git env vars we strip to prevent interference from the host git config
    _GIT_ENV_VARS = [
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
        "GIT_CONFIG_GLOBAL",
        "GIT_CONFIG_SYSTEM",
        "GIT_CONFIG_NOSYSTEM",
    ]

    def __init__(self, harness_path: Path, output_dir: Path) -> None:
        self.harness_path = Path(harness_path)
        self.output_dir = Path(output_dir)
        self._start_time: float | None = None

    def prepare(self) -> Path:
        """
        Create a clean workspace directory and record start time.

        Returns the workspace_path where the agent should write its output.
        """
        workspace_path = self.output_dir / "workspace"
        workspace_path.mkdir(parents=True, exist_ok=True)

        # Clear git environment variables in the current process so any
        # subprocess launched from here starts clean.
        for var in self._GIT_ENV_VARS:
            os.environ.pop(var, None)

        self._start_time = time.monotonic()
        return workspace_path

    def capture_result(self, workspace_path: Path) -> EnvironmentResult:
        """
        Record end time and count output files.

        Call this after the agent has finished writing to workspace_path.
        """
        end_time = time.monotonic()
        start_time = self._start_time if self._start_time is not None else end_time

        workspace_path = Path(workspace_path)
        file_count = sum(1 for p in workspace_path.rglob("*") if p.is_file())

        return EnvironmentResult(
            workspace_path=workspace_path,
            duration_seconds=round(end_time - start_time, 3),
            file_count=file_count,
            start_time=start_time,
            end_time=end_time,
        )
