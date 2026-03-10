"""Claude Code agent integration for the meta-benchmark runner."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


# Rough cost estimates (USD per million tokens) for claude-sonnet-4-6
_COST_PER_MTOK_INPUT = 3.0
_COST_PER_MTOK_OUTPUT = 15.0


@dataclass
class AgentResult:
    output: str
    exit_code: int
    tokens_input: int = 0
    tokens_output: int = 0
    cost_estimate_usd: float = 0.0
    stderr: str = ""
    raw_response: str = ""


class ClaudeCodeAgent:
    """Runs a harness prompt via the `claude` CLI (Claude Code)."""

    def __init__(self, model: str, harness_path: Path) -> None:
        self.model = model
        self.harness_path = Path(harness_path)

    def run(self, workspace_path: Path) -> AgentResult:
        workspace_path = Path(workspace_path)
        workspace_path.mkdir(parents=True, exist_ok=True)

        prompt_src = self.harness_path / "prompt.md"
        if not prompt_src.exists():
            raise FileNotFoundError(f"prompt.md not found at {prompt_src}")

        prompt_text = prompt_src.read_text(encoding="utf-8")

        # Write a copy of the prompt into the workspace for reference
        (workspace_path / "PROMPT.md").write_text(prompt_text, encoding="utf-8")

        # Locate the claude binary
        claude_bin = shutil.which("claude")
        if not claude_bin:
            raise RuntimeError(
                "claude CLI not found in PATH. "
                "Install Claude Code: https://claude.ai/code"
            )

        cmd = [
            claude_bin,
            "--print",
            "--model", self.model,
            "--output-format", "json",
        ]

        result = subprocess.run(
            cmd,
            input=prompt_text,
            capture_output=True,
            text=True,
            cwd=str(workspace_path),
        )

        tokens_input = 0
        tokens_output = 0
        output_text = result.stdout

        # Try to parse JSON usage metadata from Claude's --output-format json
        try:
            data = json.loads(result.stdout)
            output_text = data.get("result", result.stdout)
            usage = data.get("usage", {})
            tokens_input = usage.get("input_tokens", 0)
            tokens_output = usage.get("output_tokens", 0)
        except (json.JSONDecodeError, AttributeError):
            pass

        cost = (
            tokens_input / 1_000_000 * _COST_PER_MTOK_INPUT
            + tokens_output / 1_000_000 * _COST_PER_MTOK_OUTPUT
        )

        return AgentResult(
            output=output_text,
            exit_code=result.returncode,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            cost_estimate_usd=round(cost, 4),
            stderr=result.stderr,
            raw_response=result.stdout,
        )
