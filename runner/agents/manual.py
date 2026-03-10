"""Manual submission agent — for runs performed outside the automated runner."""

from __future__ import annotations

from pathlib import Path

from runner.agents.claude_code import AgentResult


class ManualAgent:
    """
    Represents a benchmark run submitted manually (e.g., from Cursor, Devin, GPT-4).

    When run(), it pauses and asks the user to copy their agent's output into the
    workspace directory, then continues to capture a submission.
    """

    def __init__(self, model: str, harness_path: Path) -> None:
        self.model = model
        self.harness_path = Path(harness_path)

    def run(self, workspace_path: Path) -> AgentResult:
        workspace_path = Path(workspace_path)
        workspace_path.mkdir(parents=True, exist_ok=True)

        print()
        print("=" * 60)
        print("MANUAL SUBMISSION MODE")
        print("=" * 60)
        print(f"\nWorkspace directory: {workspace_path}")
        print("\nSteps:")
        print("  1. Run your agent with the prompt at:")
        print(f"     {self.harness_path / 'prompt.md'}")
        print(f"  2. Copy all agent output files into: {workspace_path}/")
        print("  3. Press Enter when ready.\n")

        input("Press Enter to continue...")

        file_count = sum(1 for _ in workspace_path.rglob("*") if _.is_file())
        print(f"\nFound {file_count} files in workspace. Proceeding with scoring.\n")

        return AgentResult(
            output="[manual submission]",
            exit_code=0,
            tokens_input=0,
            tokens_output=0,
            cost_estimate_usd=0.0,
        )
