# Leaderboard

Static site for the Meta-Benchmark leaderboard. No build step required — pure HTML/CSS/JS.

## Files

- `index.html` — Main leaderboard page (table with filters, sortable columns, drill-down detail)
- `submissions.html` — How to submit a run
- `data/runs.json` — Run data (one JSON array of scorecard objects)

## Running Locally

```bash
# Option 1: Python built-in server
cd leaderboard/
python -m http.server 8080
# Visit http://localhost:8080

# Option 2: Any static file server
npx serve leaderboard/
```

## Deploying

Drop the `leaderboard/` directory on any static host (GitHub Pages, Netlify, Vercel, S3).
The site loads `data/runs.json` via a relative `fetch()` call — no backend needed.

## Adding Runs

Append a scorecard JSON object to `data/runs.json`. The scorecard schema is
produced by `scorer/scorecard.py`. Required fields:

```json
{
  "id": "unique-run-id",
  "harness": "mini-git",
  "harness_version": "1.0.0",
  "model": "...",
  "agent_framework": "...",
  "date": "ISO8601",
  "total_score": 81.4,
  "cost_usd": 4.23,
  "scores": { ... }
}
```

See `data/runs.json` for full examples.
