"""
benchmark CLI — run and score meta-benchmark harnesses.

Usage:
    python -m runner.cli run --harness mini-git --agent claude-code --model claude-sonnet-4-6
    python -m runner.cli score --submission submissions/mini-git-... --harness mini-git
    python -m runner.cli list-harnesses
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path


def _find_project_root() -> Path:
    """Walk up from this file to find the project root (contains harnesses/)."""
    here = Path(__file__).resolve().parent
    for candidate in [here, here.parent, here.parent.parent]:
        if (candidate / "harnesses").exists():
            return candidate
    return here.parent


PROJECT_ROOT = _find_project_root()


# ---------------------------------------------------------------------------
# Sub-commands
# ---------------------------------------------------------------------------

def cmd_run(args: argparse.Namespace) -> int:
    harness_path = PROJECT_ROOT / "harnesses" / args.harness
    if not harness_path.exists():
        print(f"error: harness '{args.harness}' not found at {harness_path}", file=sys.stderr)
        return 1

    prompt_path = harness_path / "prompt.md"
    if not prompt_path.exists():
        print(f"error: harness '{args.harness}' is missing prompt.md", file=sys.stderr)
        return 1

    from runner.agents import get_agent, AGENTS
    if args.agent not in AGENTS:
        print(f"error: unknown agent '{args.agent}'. Available: {list(AGENTS)}", file=sys.stderr)
        return 1

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    model_slug = args.model.replace("/", "-").replace(":", "-")
    output_dir = Path(args.output_dir) if args.output_dir else (
        PROJECT_ROOT / "submissions" / f"{args.harness}-{model_slug}-{timestamp}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    from runner.environment import Environment
    env = Environment(harness_path=harness_path, output_dir=output_dir)
    workspace_path = env.prepare()

    print(f"Running harness '{args.harness}' with agent '{args.agent}' (model: {args.model})")
    print(f"Workspace: {workspace_path}")

    agent = get_agent(args.agent, model=args.model, harness_path=harness_path)
    agent_result = agent.run(workspace_path)

    env_result = env.capture_result(workspace_path)

    from runner.submission import Submission
    submission = Submission(submissions_root=PROJECT_ROOT / "submissions")
    submission_path = submission.create(
        harness=args.harness,
        model=args.model,
        agent_framework=args.agent,
        workspace_path=workspace_path,
        agent_result=agent_result,
        env_result=env_result,
    )

    print(f"\nSubmission created: {submission_path}")
    print(f"Duration: {env_result.duration_seconds:.1f}s")
    print(f"Files: {env_result.file_count}")
    if agent_result.tokens_input or agent_result.tokens_output:
        print(f"Tokens: {agent_result.tokens_input:,} in / {agent_result.tokens_output:,} out")
        print(f"Est. cost: ${agent_result.cost_estimate_usd:.4f}")
    print(f"\nTo score: benchmark score --submission {submission_path} --harness {args.harness}")
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    from runner.submission import Submission
    submission = Submission()
    result = submission.validate(Path(args.submission))

    if not result.valid:
        print("Submission validation failed:", file=sys.stderr)
        for err in result.errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print(f"Submission valid: {args.submission}")
    print("\nScorer not yet integrated in this release.")
    print("Run the scorer directly:")
    print(f"  python -m scorer.scorecard --submission {args.submission} --harness {args.harness}")
    return 0


def cmd_list_harnesses(args: argparse.Namespace) -> int:
    harnesses_dir = PROJECT_ROOT / "harnesses"
    if not harnesses_dir.exists():
        print("No harnesses directory found.", file=sys.stderr)
        return 1

    harnesses = sorted(p for p in harnesses_dir.iterdir() if p.is_dir())
    if not harnesses:
        print("No harnesses found.")
        return 0

    print(f"Available harnesses ({len(harnesses)}):\n")
    for h in harnesses:
        spec = h / "spec.md"
        description = "(no spec.md)"
        if spec.exists():
            first_line = spec.read_text(encoding="utf-8").splitlines()
            # Find first non-empty, non-# line for description
            for line in first_line:
                stripped = line.strip().lstrip("#").strip()
                if stripped:
                    description = stripped[:80]
                    break
        print(f"  {h.name:<20} {description}")
    return 0


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="benchmark",
        description="Meta-Benchmark: run and score AI coding agent harnesses.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # benchmark run
    run_p = sub.add_parser("run", help="Run a harness against an agent")
    run_p.add_argument("--harness", required=True, help="Harness name (e.g. mini-git)")
    run_p.add_argument("--agent", required=True, help="Agent name (claude-code, manual)")
    run_p.add_argument("--model", required=True, help="Model ID (e.g. claude-sonnet-4-6)")
    run_p.add_argument("--output-dir", default=None, help="Override submission output directory")

    # benchmark score
    score_p = sub.add_parser("score", help="Score a submission")
    score_p.add_argument("--submission", required=True, help="Path to submission directory")
    score_p.add_argument("--harness", required=True, help="Harness name")
    score_p.add_argument("--output", default=None, help="Output path for JSON scorecard")

    # benchmark list-harnesses
    sub.add_parser("list-harnesses", help="List available harnesses")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    handlers = {
        "run": cmd_run,
        "score": cmd_score,
        "list-harnesses": cmd_list_harnesses,
    }

    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    sys.exit(handler(args))


if __name__ == "__main__":
    main()
