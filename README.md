# Meta-Benchmark

**A community standard for measuring AI coding agents on real software development.**

---

## The problem

AI coding agents have gotten dramatically better. But there's no rigorous way to measure it.

Current benchmarks (HumanEval, SWE-bench) measure narrow, atomic tasks designed for models, not agents. They operate at toy scale. They capture nothing developers actually care about: architectural coherence, code quality, knowing what to leave out, performance under load, reliability under failure.

Progress is felt, not measured. "GPT-4 is better at coding now" is a vibe, not a claim.

## The idea

This is the [CSS Zen Garden](https://csszengarden.com/) for AI coding agents.

A standardized application harness defines *what to build* — a fixed canvas. Agents build against it. Their output is scored on dimensions that actually matter. Results are public and reproducible.

> "This agent built mini-git with 94% feature completeness, p95 `git log` latency of 12ms on 10k commits, survived 87% of adversarial edge cases, and cost $4.23 in 47 minutes."

That's a precise, reproducible claim. You can verify it. You can compare it. You can beat it.

## The first harness: mini-git

A from-scratch implementation of git — content-addressable object storage, staging index, branches, merges, the works.

**Why mini-git?**
- The spec is git itself. Every developer knows what correct behavior looks like.
- Content-addressable storage (SHA1 blob/tree/commit objects) is non-trivial architecturally — it separates agents that *understand* git from agents that *fake* it.
- Performance and reliability are well-defined and measurable.
- The test suite writes itself.

**Feature tiers:**

| Tier | Weight | Commands |
|------|--------|----------|
| Tier 1 — Core | 40% | `init`, `add`, `commit`, `log`, `status` |
| Tier 2 — Branching | 35% | `branch`, `checkout`, `merge`, `diff` |
| Tier 3 — Advanced | 25% | merge conflicts, `reset`, `stash` |

## Scoring

Seven dimensions, all automatable except code quality:

| Dimension | Weight | How |
|-----------|--------|-----|
| Functional completeness | 30% | 72 behavioral tests (pytest, black-box) |
| Adversarial survival | 15% | 159 edge cases — unicode filenames, binary files, corrupt objects, 100k files |
| Extension readiness | 10% | Second prompt: "now add remotes" — tests run again |
| Mutation kill rate | 10% | Does the agent's own test suite actually verify its logic? |
| Performance | 15% | p95 latency on `git log` (10k commits), `git add` (100k files), `git diff` (1k changes), deep merge |
| Reliability | 10% | SIGKILL mid-commit, concurrent writes, disk-full, corrupt object store |
| Code quality | 10% | Multi-model LLM judge, calibrated against human expert scores |

**Output:** A structured JSON scorecard + human-readable report. All runs are public.

## Architecture

```
meta-benchmark/
  harnesses/
    mini-git/
      spec.md          ← Full PRD: what to build
      prompt.md        ← The single seed prompt the agent receives
      rubric.md        ← Scoring dimensions and weights
      tests/
        tier1/         ← init, add, commit, log, status
        tier2/         ← branch, checkout, merge, diff
        tier3/         ← merge conflicts, reset, stash
        adversarial/   ← 159 edge cases
        extension/     ← remote operations (second prompt)
        performance/   ← latency benchmarks
        reliability/   ← chaos scenarios
      judge/
        rubric.md      ← LLM judge qualitative rubric
        calibration/   ← Human-scored reference implementations
  runner/
    cli.py             ← benchmark run / score / list-harnesses
    agents/
      claude_code.py   ← Claude Code subprocess integration
      README.md        ← Manual submission format (for Cursor, Devin, etc.)
  scorer/
    behavioral.py      ← Runs tier 1-3 tests
    adversarial.py     ← Runs edge case battery
    extension.py       ← Runs extension tests
    mutation.py        ← Mutation testing (mutmut)
    performance.py     ← Latency benchmarks
    reliability.py     ← Chaos scenarios
    judge.py           ← Multi-model LLM judge
    scorecard.py       ← Aggregates everything → JSON
  leaderboard/
    index.html         ← Static leaderboard site (no build step)
    data/runs.json     ← All public runs
```

## Quickstart

```bash
git clone <this-repo>
cd meta-benchmark
pip install -e .

# See available harnesses
benchmark list-harnesses

# Run mini-git against Claude
benchmark run --harness mini-git --agent claude-code --model claude-sonnet-4-6

# Score the output
benchmark score --submission submissions/mini-git-claude-sonnet-4-6-<timestamp>/ --harness mini-git
```

See [TESTING.md](TESTING.md) for a full walkthrough.

## Anti-Goodhart measures

Benchmarks rot when they become training targets.

1. **Private held-out tests** — A meaningful slice of adversarial + reliability tests is never published. Scores on the leaderboard include held-out test performance, verified by maintainers.
2. **Harness versioning** — v1, v2, v3. New requirements with each version. Old scores don't carry forward.
3. **Harness velocity** — The community grows the harness library faster than any model can be fine-tuned against it.

## Submitting a run

Any agent, any framework. If you can produce code, you can submit.

```bash
# Automated (Claude Code)
benchmark run --harness mini-git --agent claude-code --model <your-model>
benchmark score --submission submissions/<your-run>/ --harness mini-git

# Manual (Cursor, Devin, Copilot, raw API, etc.)
# → See runner/agents/README.md
```

To add your run to the leaderboard, open a PR with your `metadata.json` and `scorecard.json`.

## Contributing harnesses

A harness is a directory under `harnesses/` with:
- `spec.md` — What to build
- `prompt.md` — The seed prompt
- `rubric.md` — Scoring dimensions and weights
- `tests/` — The test suite
- `judge/rubric.md` — LLM judge rubric

Good harness candidates: a compiler for a simple language, a key-value store with persistence, a job queue with retry logic, a diff/patch tool, a CSV query engine. The pattern: **non-trivial, well-specified, testable**.

See [harnesses/mini-git/](harnesses/mini-git/) as the reference implementation.

## The leaderboard

Open `leaderboard/index.html` in a browser (or `python -m http.server 8080` in the leaderboard dir). Sortable by any dimension. Filter by model, framework, harness version. Drill into any run for full scorecard detail.

---

*Built to be forked, extended, and argued about. The goal is a common canvas — one place where "this model is better at coding" becomes a falsifiable claim.*
