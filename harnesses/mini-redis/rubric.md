# mini-redis Scoring Rubric

**Harness version:** 1.0.0

All scores are in [0, 100]. Weights sum to 1.0.

---

## Dimension Weights

| Dimension | Weight |
|-----------|--------|
| Functional completeness | 0.30 |
| Adversarial survival | 0.15 |
| Extension readiness | 0.10 |
| Mutation kill rate | 0.10 |
| Performance | 0.15 |
| Reliability | 0.10 |
| Code quality | 0.10 |

**N/A redistribution:** If mutation has no tests to run (agent produced no test files), its 0.10 weight is redistributed proportionally to functional (0.30), adversarial (0.15), and extension (0.10). All other dimensions remain unchanged.

---

## D1: Functional Completeness (weight 0.30)

**Test tiers:**

| Tier | Weight within D1 | Commands |
|------|-----------------|---------|
| Tier 1 — Strings | 0.40 | SET, GET, DEL, EXISTS, MSET, MGET |
| Tier 2 — Collections | 0.35 | LPUSH, RPUSH, LPOP, RPOP, LRANGE, HSET, HGET, HDEL, HGETALL, HKEYS |
| Tier 3 — Advanced | 0.25 | EXPIRE, TTL, PERSIST, SADD, SREM, SMEMBERS, SISMEMBER, INCR, DECR |

**Formula:**
```
tier_score_i = (passed_i / total_i) * 100
D1 = 0.40 * tier1_score + 0.35 * tier2_score + 0.25 * tier3_score
```

**Not Applicable:** Never — if no tests run, score is 0.

---

## D2: Adversarial Survival (weight 0.15)

Tests ~150 public edge cases not disclosed to the agent: type errors, unicode keys/values, special characters in values, wrong-arity calls, unknown commands, boundary conditions on LRANGE/EXPIRE/TTL, and large datasets.

**Formula:**
```
D2 = (passed / total_adversarial_tests) * 100
total_adversarial_tests = public_count + held_out_count
```

Entries scored with held-out tests are marked `"verified": true`.

---

## D3: Extension Readiness (weight 0.10)

Second-prompt round: agent given 15 minutes to add Sorted Set support (ZADD, ZRANGE, ZRANK, ZSCORE, ZREM). 16 tests.

**Formula:**
```
D3 = (passed / 16) * 100
```

**Not Applicable:** If tier1 score < 40%, extension is skipped and weight redistributed. Score is 0 for static submissions (no live agent).

---

## D4: Mutation Kill Rate (weight 0.10)

Automated mutation testing of the agent's own test suite using mutmut.

**Formula:**
```
D4 = (killed / total_mutants) * 100
```

**Not Applicable:** If agent produced < 5 test functions, weight redistributed to D1+D2+D3.

---

## D5: Performance (weight 0.15)

Three benchmarks. Each scored piecewise linear:
- p95 ≤ target → 100
- p95 ≥ fail → 0
- Between → `100 * (fail - p95) / (fail - target)`

| Benchmark | Target p95 | Fail p95 | Weight |
|-----------|-----------|---------|--------|
| get_10k_keys | 1.0s | 5.0s | 0.40 |
| lrange_10k_list | 2.0s | 10.0s | 0.35 |
| hgetall_1k_fields | 1.0s | 5.0s | 0.25 |

**D5 = weighted average of benchmark scores.**

---

## D6: Reliability (weight 0.10)

7 chaos scenarios, each pass/fail:

1. Data survives clean process exit
2. Second read after write returns correct value
3. Corrupt JSON file → non-zero exit with stderr (no traceback)
4. Missing data file → empty store (no crash)
5. EXPIRE deadline survives process restart
6. TTL expired key → (nil) on read (lazy eviction)
7. Large value (1MB string) stored and retrieved correctly

**Formula:**
```
D6 = (passed / 7) * 100
```

---

## D7: Code Quality (weight 0.10)

Multi-model LLM judge evaluates 5 qualitative dimensions (see `judge/rubric.md`). Score is average across judge instances and dimensions.

**Dry run:** If `--dry-run` is used, D7 = 0 and is noted as `dry_run: true` in the scorecard. Leaderboard shows `—` not 0 for dry-run entries.

---

## Score Report Schema

```json
{
  "harness": "mini-redis",
  "harness_version": "1.0.0",
  "submission_id": "...",
  "model": "...",
  "agent_framework": "...",
  "date": "...",
  "scores": {
    "functional": {"score": 85.0, "weight": 0.30, "detail": {}},
    "adversarial": {"score": 72.0, "weight": 0.15, "detail": {}},
    "extension":   {"score": 25.0, "weight": 0.10, "detail": {}},
    "mutation":    {"score": 80.0, "weight": 0.10, "detail": {}},
    "performance": {"score": 90.0, "weight": 0.15, "detail": {}},
    "reliability": {"score": 85.7, "weight": 0.10, "detail": {}},
    "quality":     {"score": 70.0, "weight": 0.10, "detail": {}}
  },
  "total_score": 81.2,
  "metadata": {}
}
```
