# Manual Submission Format

To submit a benchmark run from any agent (Cursor, Devin, GPT-4, Gemini, etc.),
you don't need the automated runner. Package your output using the format below.

---

## Required Directory Structure

```
submissions/
  <harness-name>-<model>-<date>/
    metadata.json        ← Required. See schema below.
    workspace/           ← Required. Agent's output files.
      <all agent files>
```

Example:
```
submissions/
  mini-git-gpt-4o-20260310T142300Z/
    metadata.json
    workspace/
      mini_git.py
      test_mini_git.py
      README.md
```

---

## metadata.json Schema

```json
{
  "model": "gpt-4o-2024-11-20",
  "agent_framework": "cursor",
  "agent_framework_version": "0.43.0",
  "scaffolding_config": {},
  "date": "2026-03-10T14:23:00Z",
  "harness": "mini-git",
  "harness_version": "1.0.0",
  "wall_clock_seconds": 847,
  "tokens_input": 45000,
  "tokens_output": 12000,
  "cost_usd": 4.23,
  "notes": "Optional: any context about this run"
}
```

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `model` | string | Full model identifier including version |
| `agent_framework` | string | Tool/framework used (cursor, devin, aider, raw-api, etc.) |
| `date` | ISO 8601 | When the run was performed |
| `harness` | string | Harness name (must match a directory in `harnesses/`) |
| `harness_version` | string | Semver version of the harness used |

### Optional Fields

| Field | Type | Description |
|-------|------|-------------|
| `agent_framework_version` | string | Version of the agent framework |
| `scaffolding_config` | object | Any non-default settings used |
| `wall_clock_seconds` | number | Total elapsed time |
| `tokens_input` | integer | Input tokens consumed |
| `tokens_output` | integer | Output tokens generated |
| `cost_usd` | number | Total cost in USD |
| `notes` | string | Free-form notes about the run |

---

## How to Score Your Submission

1. Create the directory structure above
2. Run the scorer:
   ```bash
   python -m runner.cli score --submission submissions/my-run/ --harness mini-git
   ```
3. The scorer will validate your submission and output a JSON scorecard.

---

## Leaderboard Submissions

To add your run to the public leaderboard:
1. Score your submission and get the JSON scorecard
2. Open an issue or PR at the repository
3. Include your `metadata.json` and `scorecard.json`

All submissions are public. Model providers are encouraged to submit.

---

## Notes on Reproducibility

For a run to be accepted on the leaderboard:
- The agent must have received **only** the seed prompt (`harnesses/<name>/prompt.md`)
- No additional context, examples, or partial implementations
- The `harness_version` must match a published, tagged harness version
- Human edits to agent output are not permitted

Runs that don't meet reproducibility criteria can still be submitted as "unofficial."
