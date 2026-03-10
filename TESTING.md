# Testing Guide

Everything you need to try out the Meta-Benchmark system end-to-end.

**Time required:** ~15 minutes (without running a live agent). ~45–90 minutes with a live agent.

---

## Prerequisites

```bash
# Python 3.10+
python --version

# Clone and install
cd /Users/anoopdawar/meta-benchmark   # or wherever you cloned it
pip install -e .

# Verify the CLI is working
benchmark list-harnesses
# Expected output:
#   Available harnesses (1):
#     mini-git             Mini-Git: Product Requirements Document
```

---

## Part 1: Explore the harness

### 1.1 Read what agents are asked to build

```bash
cat harnesses/mini-git/prompt.md
```

This is the exact prompt the agent receives. Nothing else.

### 1.2 Read the full spec

```bash
cat harnesses/mini-git/spec.md
```

The object model, all commands, edge cases, performance targets, reliability requirements.

### 1.3 Read the scoring rubric

```bash
cat harnesses/mini-git/rubric.md
```

Seven dimensions, weights, and formulas.

---

## Part 2: Run the test suite against a real mini-git

To actually run the tests, you need a mini-git implementation. You have two options:

### Option A: Use a reference implementation (fastest)

Build a quick mini-git to see the tests exercise it. Here's a minimal one — save it as `/tmp/mini_git.py`:

```bash
cat > /tmp/mini_git.py << 'IMPL'
#!/usr/bin/env python3
"""Minimal mini-git stub — just enough to pass Tier 1 init/status tests."""
import sys, os, hashlib, zlib, json
from pathlib import Path

def git_dir(): return Path(".git")

def cmd_init():
    for d in [".git/objects", ".git/refs/heads"]:
        os.makedirs(d, exist_ok=True)
    Path(".git/HEAD").write_text("ref: refs/heads/main\n")
    print("Initialized empty repository")

def cmd_status():
    if not git_dir().exists():
        print("fatal: not a git repository"); sys.exit(1)
    print("On branch main\nnothing to commit, working tree clean")

if __name__ == "__main__":
    cmds = {"init": cmd_init, "status": cmd_status}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print(f"usage: mini_git <{'|'.join(cmds)}>"); sys.exit(1)
    cmds[sys.argv[1]]()
IMPL
```

Point the test suite at it:

```bash
export MINI_GIT_CMD="python /tmp/mini_git.py"

# Run just the init tests
python -m pytest harnesses/mini-git/tests/tier1/test_init.py -v

# Expected: some pass, many skip/fail (stub is minimal)
```

### Option B: Run an agent to build it (see Part 3)

---

## Part 3: Run a live agent (requires API key)

### 3.1 Set up your API key

```bash
export ANTHROPIC_API_KEY=sk-ant-...    # for claude-code agent
```

### 3.2 Run the harness

```bash
benchmark run \
  --harness mini-git \
  --agent claude-code \
  --model claude-sonnet-4-6
```

This will:
1. Create an isolated workspace in `submissions/`
2. Feed `harnesses/mini-git/prompt.md` to Claude Code
3. Wait for the agent to write its implementation
4. Capture the output and record timing/cost metadata

The agent typically takes 20–60 minutes. You'll see the submission path when it finishes:

```
Submission created: submissions/mini-git-claude-sonnet-4-6-20260310T140000Z/
Duration: 2847.3s
Files: 12
Est. cost: $4.23

To score: benchmark score --submission submissions/mini-git-... --harness mini-git
```

### 3.3 Inspect the submission

```bash
ls submissions/mini-git-*/workspace/    # what the agent built
cat submissions/mini-git-*/metadata.json
```

---

## Part 4: Score a submission

### 4.1 Score the submission

```bash
benchmark score \
  --submission submissions/mini-git-claude-sonnet-4-6-20260310T140000Z/ \
  --harness mini-git
```

This runs all 7 scoring dimensions and produces a report:

```
Scoring submission: submissions/mini-git-...
Harness: harnesses/mini-git

Running behavioral tests...
  Functional: 88.5/100 (62/72 tests)
Running adversarial tests...
  Adversarial: 74.2/100 (118/159 survived)
Running extension tests...
  Extension: 75.0/100 (12/16)
Running mutation testing...
  Mutation: 62.0/100 (mutmut)
Running performance benchmarks...
  Performance: 91.0/100
Running reliability tests...
  Reliability: 72.7/100 (8/11)
Running LLM judge...
  Quality: 83.0/100

Total score: 81.4/100

# Dimension Scores
Dimension                  Score    Weight  Weighted
───────────────────────── ──────   ──────  ────────
functional                  88.5     30%      26.6
adversarial                 74.2     15%      11.1
extension                   75.0     10%       7.5
...
```

The scorecard JSON is saved to `submissions/<run>/scorecard.json`.

### 4.2 Score without a live agent (dry run)

To test the scoring pipeline without a real submission:

```bash
# Create a fake submission
mkdir -p /tmp/test-submission/workspace
echo '{"model":"test","agent_framework":"manual","date":"2026-03-10T00:00:00Z","harness":"mini-git","harness_version":"1.0.0"}' \
  > /tmp/test-submission/metadata.json
cp /tmp/mini_git.py /tmp/test-submission/workspace/mini_git.py

# Score it (--dry-run skips the LLM judge API call)
python -m scorer.scorecard \
  --submission /tmp/test-submission \
  --harness mini-git \
  --dry-run \
  --output /tmp/scorecard.json

cat /tmp/scorecard.json | python -m json.tool | head -60
```

---

## Part 5: Run the tests directly

You can run any subset of the test suite standalone:

```bash
export MINI_GIT_CMD="python /path/to/your/mini_git.py"

# Tier 1 only (init, add, commit, log, status)
python -m pytest harnesses/mini-git/tests/tier1/ -v

# Tier 2 (branching)
python -m pytest harnesses/mini-git/tests/tier2/ -v

# Tier 3 (advanced)
python -m pytest harnesses/mini-git/tests/tier3/ -v

# Adversarial only
python -m pytest harnesses/mini-git/tests/adversarial/ -v

# Extension (remote operations)
python -m pytest harnesses/mini-git/tests/extension/ -v

# Reliability (chaos scenarios — runs fast, implementation just needs to not crash)
python -m pytest harnesses/mini-git/tests/reliability/ -v

# Everything
python -m pytest harnesses/mini-git/tests/ -v --tb=short

# Count total collectible tests
python -m pytest harnesses/mini-git/tests/ --collect-only -q | tail -1
# Should show: 257 tests collected
```

**Tests skip gracefully** when no implementation is found — you won't get 257 failures, just 257 skips.

---

## Part 6: Open the leaderboard

```bash
cd leaderboard/
python -m http.server 8080
# Open http://localhost:8080 in your browser
```

You'll see two pre-loaded sample runs: `claude-sonnet-4-6` (81.4) and `gemini-2.0-pro` (61.7).

Click any row to drill down into tier-by-tier scores, performance latency, and judge dimension details.

---

## Part 7: Manual submission (any agent)

To score output from Cursor, Devin, Copilot, raw API, etc.:

```bash
# 1. Create the submission directory
mkdir -p submissions/my-run/workspace

# 2. Copy your agent's output into workspace/
cp -r /path/to/agent/output/* submissions/my-run/workspace/

# 3. Write metadata.json
cat > submissions/my-run/metadata.json << 'EOF'
{
  "model": "gpt-4o-2024-11-20",
  "agent_framework": "cursor",
  "agent_framework_version": "0.43.0",
  "scaffolding_config": {},
  "date": "2026-03-10T14:23:00Z",
  "harness": "mini-git",
  "harness_version": "1.0.0",
  "wall_clock_seconds": 1200,
  "tokens_input": 50000,
  "tokens_output": 15000,
  "cost_usd": 3.50,
  "notes": ""
}
EOF

# 4. Score it
benchmark score --submission submissions/my-run/ --harness mini-git
```

See [runner/agents/README.md](runner/agents/README.md) for the full schema.

---

## Part 8: Verify the judge calibration

The LLM judge is calibrated against human expert scores. To inspect:

```bash
# Read the calibration samples
cat harnesses/mini-git/judge/calibration/sample_good/notes.md
cat harnesses/mini-git/judge/calibration/sample_bad/notes.md

# See the ground truth scores
cat harnesses/mini-git/judge/calibration/scores.json | python -m json.tool
```

To run the judge standalone (requires `ANTHROPIC_API_KEY`):

```python
from pathlib import Path
from scorer.judge import run_judge

result = run_judge(
    submission_path=Path("submissions/my-run/"),
    harness_path=Path("harnesses/mini-git/"),
)

for dim, score in result.dimension_scores.items():
    print(f"{dim}: {score.score}/100 — {score.reasoning}")
```

---

## Troubleshooting

**`benchmark: command not found`**
```bash
pip install -e .   # re-run from project root
# or
python -m runner.cli list-harnesses
```

**Tests all skipping**
```bash
# Make sure MINI_GIT_CMD is set
echo $MINI_GIT_CMD
export MINI_GIT_CMD="python /path/to/mini_git.py"
```

**`claude: command not found`** (when using `--agent claude-code`)
```bash
# Install Claude Code: https://claude.ai/code
which claude   # should show a path
```

**Scorer import errors**
```bash
# Run from the project root, not a subdirectory
cd /Users/anoopdawar/meta-benchmark
python -m scorer.scorecard --help
```

**Leaderboard shows "Failed to load data"**
```bash
# Must be served via HTTP, not opened as a file
cd leaderboard && python -m http.server 8080
# Then open http://localhost:8080 (not file:///...)
```

---

## What to expect from scoring

A rough guide to what scores mean in practice:

| Score | What it means |
|-------|---------------|
| 90–100 | Near-perfect. All tiers pass, handles edge cases, clean architecture. Rare. |
| 75–90 | Strong. Tier 1–2 solid, most adversarial cases handled, some Tier 3 gaps. |
| 60–75 | Competent. Core commands work, branching mostly works, edge cases patchy. |
| 40–60 | Partial. Tier 1 works, Tier 2 rough, Tier 3 missing or broken. |
| < 40 | Early draft. Basic init/commit/log, not much else. |

Current best on the sample leaderboard: `claude-sonnet-4-6` at **81.4**.
