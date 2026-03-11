# mini-redis & mini-sqlite Harness Design

**Date:** 2026-03-11
**Status:** Approved

---

## Overview

Two new harnesses for meta-benchmark, following the mini-git pattern exactly:
- CLI as thin shell over a required internal library/core
- Discovered via env var (`MINI_REDIS_CMD`, `MINI_SQLITE_CMD`)
- Seven scoring dimensions identical to mini-git
- Subprocess-based test harness (pytest + env var)

---

## Harness 1: mini-redis

### What agents build

A Redis-like in-process key/value store backed by a JSON file on disk. CLI is a thin shell; all data structure logic lives in an internal `RedisStore` class (or equivalent). No networking required.

### Invocation

```
MINI_REDIS_CMD=python mini_redis.py
MINI_REDIS_DATA=/tmp/test123/mini_redis.json   # set by test fixtures

python mini_redis.py SET foo bar      → OK
python mini_redis.py GET foo          → "bar"
python mini_redis.py DEL foo          → (integer) 1
python mini_redis.py GET foo          → (nil)
```

### Data file

`mini_redis.json` — path controlled by `MINI_REDIS_DATA` env var.
- If `MINI_REDIS_DATA` is not set: use `./mini_redis.json` in the current working directory.
- Tests always set `MINI_REDIS_DATA` to a tmp path — no shared state between test runs.
- Agent chooses internal JSON schema.

### Durability

The store must be fully written to disk (fsync or equivalent) before the process exits on any successful mutation. Read-only commands never write disk.

### Trailing newline

All stdout output ends with exactly one `\n`. Tests strip trailing whitespace before comparison.

### Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Command error (wrong arity, wrong type, unknown command) |
| 2 | I/O / persistence error |

### stdout contract — general rules

The per-command table is authoritative. The general rules below apply only where no per-command contract is specified.

| Result type | Output |
|-------------|--------|
| Successful mutation (no other return value) | `OK` |
| String value | `"value"` (double-quoted) |
| Integer result | `(integer) N` |
| Float result | score formatted with `f"{score:g}"` then quoted, e.g. `"1"` or `"1.5"` |
| Missing key / member | `(nil)` |
| List / array of strings | `1) item\n2) item\n...` (1-indexed) |
| Empty list | `(empty list)` |
| Empty set | `(empty set)` |

**String quoting rules** (applies to GET, HGET, GETALL values, LPOP/RPOP, ZSCORE, etc.): values are wrapped in double quotes. Inside quotes: `"` → `\"`, `\` → `\\`, newline → `\n` (literal two chars).

**HGETALL exception:** field names and values are both printed unquoted, alternating lines. The general string-quoting rule does not apply to HGETALL output.

**stderr:** error message only on non-zero exit. stdout is empty on error.

### Per-command output contracts

#### Tier 1 — Strings

| Command | Success stdout | Notes |
|---------|---------------|-------|
| `SET key value` | `OK` | All `SET` options (`NX`, `XX`, `EX`, `PX`, `GET`) are **out of scope** |
| `GET key` | `"value"` or `(nil)` | |
| `DEL key [key ...]` | `(integer) N` | N = number of keys actually deleted |
| `EXISTS key` | `(integer) 1` or `(integer) 0` | |
| `MSET key value [key value ...]` | `OK` | |
| `MGET key [key ...]` | numbered list; missing keys print `(nil)` at their position. Example: `MGET a missing b` → `1) "val_a"\n2) (nil)\n3) "val_b"` | preserves argument order |

#### Tier 2 — Collections

**Lists:**

| Command | Success stdout | Notes |
|---------|---------------|-------|
| `LPUSH key value [value ...]` | `(integer) N` | N = new list length after push |
| `RPUSH key value [value ...]` | `(integer) N` | N = new list length after push |
| `LPOP key` | `"value"` or `(nil)` | |
| `RPOP key` | `"value"` or `(nil)` | |
| `LRANGE key start stop` | numbered list or `(empty list)` | Python-style: negative indices count from end; stop is inclusive |

**Hashes:**

| Command | Success stdout | Notes |
|---------|---------------|-------|
| `HSET key field value [field value ...]` | `(integer) N` | N = number of new fields added (updates don't count) |
| `HGET key field` | `"value"` or `(nil)` | |
| `HDEL key field [field ...]` | `(integer) N` | N = number of fields deleted |
| `HGETALL key` | alternating field/value lines, alphabetical by field: `field1\nvalue1\nfield2\nvalue2` or `(empty list)` | field names unquoted; values unquoted |
| `HKEYS key` | numbered list of field names (alphabetical) or `(empty list)` | |

#### Tier 3 — Advanced

**TTL / Expiry:**

| Command | Success stdout | Notes |
|---------|---------------|-------|
| `EXPIRE key seconds` | `(integer) 1` if key exists; `(integer) 0` if key does not exist | seconds must be a positive integer; if 0, negative, or non-integer: exit 1, stderr `ERR invalid expire time in 'EXPIRE' command` |
| `TTL key` | `(integer) N` (seconds remaining); `(integer) -1` (key exists, no TTL); `(integer) -2` (key does not exist) | |
| `PERSIST key` | `(integer) 1` if TTL removed; `(integer) 0` if key has no TTL or does not exist | |

**Sets:**

| Command | Success stdout | Notes |
|---------|---------------|-------|
| `SADD key member [member ...]` | `(integer) N` | N = number of new members added |
| `SREM key member [member ...]` | `(integer) N` | N = number of members removed |
| `SMEMBERS key` | numbered list (lexicographic order) or `(empty set)` | |
| `SISMEMBER key member` | `(integer) 1` or `(integer) 0` | |

**Counters:**

| Command | Success stdout | Notes |
|---------|---------------|-------|
| `INCR key` | `(integer) N` | Missing key treated as 0 before increment |
| `DECR key` | `(integer) N` | Missing key treated as 0 before decrement |

`INCR` / `DECR` on a non-integer value: exit 1, stderr: `ERR value is not an integer or out of range`

#### Extension — Sorted Sets (second prompt)

| Command | Success stdout | Notes |
|---------|---------------|-------|
| `ZADD key score member [score member ...]` | `(integer) N` | N = new members added; updating score of existing member counts as 0; scores are 64-bit floats |
| `ZRANGE key start stop` | numbered list by rank (ascending score) or `(empty list)` | 0-indexed; negative indices supported; ties in score broken lexicographically; `WITHSCORES` is **out of scope** |
| `ZRANK key member` | `(integer) N` (0-based rank, ascending) or `(nil)` | |
| `ZSCORE key member` | quoted score using `f"{score:g}"` format (e.g. `"1"` for 1.0, `"1.5"` for 1.5) or `(nil)` | |
| `ZREM key member [member ...]` | `(integer) N` | N = members removed |

### Ordering rules (test stability)

| Context | Order |
|---------|-------|
| `LRANGE` | left-to-right insertion order |
| `HKEYS`, `HGETALL` | alphabetical by field name |
| `SMEMBERS` | lexicographic |
| `ZRANGE` | ascending by score; ties broken lexicographically by member name |
| `MGET` | preserves argument order |

### TTL / EXPIRE semantics

Lazy eviction only — expiry checked at read time. No background thread required. An expired key behaves identically to a missing key at read time.

**TTL persistence:** deadlines are stored as absolute Unix epoch timestamps (float seconds). When the process restarts and reads the data file, elapsed time is accounted for — `TTL` returns the remaining seconds, and expired keys are treated as missing.

### Error message templates

| Error type | stderr format |
|-----------|--------------|
| Unknown command | `ERR unknown command '<cmd>'` |
| Wrong number of arguments | `ERR wrong number of arguments for '<cmd>' command` |
| Wrong type | `WRONGTYPE Operation against a key holding the wrong kind of value` |
| Non-integer on INCR/DECR | `ERR value is not an integer or out of range` |
| I/O error | `ERR persistence failure: <reason>` |

### Feature tiers

| Tier | Weight | Commands |
|------|--------|----------|
| Tier 1 — Strings | 40% | `SET`, `GET`, `DEL`, `EXISTS`, `MSET`, `MGET`, persistence |
| Tier 2 — Collections | 35% | Lists: `LPUSH`, `RPUSH`, `LPOP`, `RPOP`, `LRANGE`; Hashes: `HSET`, `HGET`, `HDEL`, `HGETALL`, `HKEYS` |
| Tier 3 — Advanced | 25% | `EXPIRE`, `TTL`, `PERSIST`; Sets: `SADD`, `SREM`, `SMEMBERS`, `SISMEMBER`; `INCR`, `DECR` |

**Extension round (second prompt, 15 min):** Sorted Sets — `ZADD`, `ZRANGE`, `ZRANK`, `ZSCORE`, `ZREM` — 16 tests.

### Out of scope

Pub/Sub, Lua scripting, MULTI/EXEC transactions, clustering, `KEYS` pattern matching, streams, `SET` options (NX/XX/EX/PX/GET), `WITHSCORES` on ZRANGE.

### Concurrent access

Tests do not run with `pytest-xdist`. Each test uses its own `MINI_REDIS_DATA` tmp path. No file locking is required.

---

## Harness 2: mini-sqlite

### What agents build

A SQL database engine with a custom on-disk storage format. CLI is a thin shell. The implementation must separate CLI, query processing, and storage concerns. High-quality designs typically factor parsing, execution, and storage into distinct components. `import sqlite3` is explicitly forbidden.

### Invocation

```
MINI_SQLITE_CMD=python mini_sqlite.py

python mini_sqlite.py mydb.db "CREATE TABLE users (id INTEGER, name TEXT)"
python mini_sqlite.py mydb.db "INSERT INTO users VALUES (1, 'Alice')"
python mini_sqlite.py mydb.db "SELECT * FROM users"
```

DB file is the first positional argument. Tests pass a tmp path. `MINI_SQLITE_CMD` is split with `shlex.split()` to form argv.

### Persistence guarantee

Data written by one process invocation must be readable by a subsequent invocation against the same file. Tests verify this (SELECT after process restart). Agent chooses storage format (binary pages, JSON, etc.).

### Trailing newline

All stdout output ends with exactly one `\n`. Tests strip trailing whitespace before comparison.

### Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | SQL error (syntax, type mismatch, unknown table/column, unsupported feature) |
| 2 | I/O error (can't open/write file) |

**stderr:** error message only on non-zero exit. stdout is empty on error.

### stdout contract — SELECT

- Header line **always** printed, even for zero rows: `id|name|age`
- Columns in schema-definition order (regardless of INSERT column order)
- Data rows: `1|Alice|30`
- `NULL` → empty field: `1||30`
- `|` in value → escaped as `\|`
- Newline in value → escaped as `\n`
- `\` in value → escaped as `\\` (must escape before applying other escapes)
- Whitespace → preserved as-is, no normalization
- Empty result: header line only, no data lines

### stdout contract — mutations

| Statement | stdout |
|-----------|--------|
| `CREATE TABLE` | `OK` |
| `DROP TABLE` | `OK` |
| `INSERT` | `1 row affected` |
| `UPDATE` | `N rows affected` (N = rows matched by WHERE clause, regardless of whether values changed; 0 if no rows matched) |
| `DELETE` (all rows) | `N rows affected` |
| `DELETE ... WHERE` | `N rows affected` |
| `BEGIN` | `OK` |
| `COMMIT` | `OK` |
| `ROLLBACK` | `OK` |
| `CREATE INDEX` *(extension)* | `OK` |

### Supported types

| Type | Semantics |
|------|-----------|
| `INTEGER` | 64-bit signed integer |
| `REAL` | 64-bit float |
| `TEXT` | UTF-8 string |
| `NULL` | First-class value. `NULL != NULL`. `NULL IS NULL` is true. |
| `BLOB` | Out of scope |
| `PRIMARY KEY` | Out of scope — exit 1: `Error: unsupported feature 'PRIMARY KEY'` |

### NULL semantics

- `NULL` sorts last in `ORDER BY ASC` and last in `ORDER BY DESC` (intentional, not standard SQL)
- `NULL` in aggregates: `COUNT(col)` ignores NULLs; `COUNT(*)` counts all rows; `SUM`/`AVG`/`MIN`/`MAX` ignore NULLs
- Inserting `NULL` for a column: write the word `NULL` (unquoted) as the value in the INSERT statement

### Supported SQL grammar by tier

**Tier 1 — Core SQL (40%)**
- `CREATE TABLE name (col type, col type, ...)`
- `DROP TABLE name` — exit 1 if table does not exist: `Error: no such table: <name>`
- `INSERT INTO name VALUES (v, ...)` — always inserts exactly one row; multi-row INSERT is out of scope; emits `1 row affected`
- `INSERT INTO name (col, ...) VALUES (v, ...)` — columns not listed default to NULL
- `SELECT * FROM name`
- `SELECT col, col FROM name`
- `DELETE FROM name` (all rows)

**Tier 2 — Queries (35%)**
- `WHERE` with: `=`, `!=`, `<`, `>`, `<=`, `>=`, `IS NULL`, `IS NOT NULL`, `AND`, `OR`, `NOT`
- `UPDATE name SET col=val [, col=val ...] [WHERE ...]`
- `DELETE FROM name WHERE ...`
- `ORDER BY col [ASC|DESC]` — stable sort for ties
- `LIMIT N [OFFSET N]`

**Tier 3 — Advanced (25%)**
- `INNER JOIN name ON condition`
- `LEFT JOIN name ON condition`
- `GROUP BY col [HAVING condition]`
- Aggregates: `COUNT(*)`, `COUNT(col)`, `SUM(col)`, `AVG(col)`, `MIN(col)`, `MAX(col)`
- `BEGIN` / `COMMIT` / `ROLLBACK` — ROLLBACK must undo all writes since BEGIN

**Extension round (second prompt, 15 min):**
- `CREATE INDEX name ON table(col)` — creates an index; response: `OK`
- `EXPLAIN query` — when the query uses an index, output must contain the string `index` (case-insensitive, anywhere in stdout); when no index is used, output must NOT contain the word `index`. Tests check both the positive case (index present and used) and the negative case (no index). 16 tests total.

### Transaction semantics

- `ROLLBACK` undoes all writes (INSERT, UPDATE, DELETE, CREATE TABLE, DROP TABLE) since the most recent `BEGIN`
- Calling `BEGIN` when a transaction is already open: exit 1, stderr `Error: transaction already active`
- Calling `COMMIT` or `ROLLBACK` with no active transaction: exit 1, stderr `Error: no active transaction`
- Nested transactions are out of scope

### Ordering semantics

- `SELECT` without `ORDER BY` → insertion order
- Ties in `ORDER BY` → stable (insertion order preserved within tied values)
- `NULL` → sorts last in both `ASC` and `DESC`

### SELECT column order

`SELECT *` always returns columns in schema-definition order, regardless of the order columns were named in `INSERT INTO ... (col, ...) VALUES ...`.

For `SELECT *` with JOINs: left-table columns first (schema order), then right-table columns (schema order). Ambiguous column names (same name in both tables) are disambiguated by prefixing with `table.column` in the header.

### Error message templates

| Error | stderr format |
|-------|--------------|
| Unknown table | `Error: no such table: <name>` |
| Unknown column | `Error: no such column: <name>` |
| Syntax error | `Error: syntax error near '<token>'` |
| Type mismatch | `Error: type mismatch` |
| Unsupported feature | `Error: unsupported feature '<feature>'` |
| I/O error | `Error: cannot open database '<path>'` |

### Unsupported features

Exit `1`, stderr: `Error: unsupported feature '<feature>'`. Applies to: subqueries, window functions, foreign keys, triggers, views, `ALTER TABLE`, `UNIQUE`, `CHECK`, `DEFAULT`, `AUTO_INCREMENT`/`ROWID`, `PRIMARY KEY`.

### Out of scope

Subqueries, window functions, foreign keys, triggers, views, `ALTER TABLE`, `UNIQUE` constraints, `CHECK` constraints, `DEFAULT` values, `AUTO_INCREMENT` / `ROWID`, `PRIMARY KEY`.

### Concurrent access

Tests do not run with `pytest-xdist`. Each test uses its own tmp db file path. No file locking is required.

---

## Shared harness structure (both)

```
harnesses/<name>/
  prompt.md          ← seed prompt (agent receives only this)
  spec.md            ← formal PRD
  rubric.md          ← 7 scoring dimensions
  judge/
    rubric.md        ← 5 qualitative dimensions with anchors
    calibration/     ← reference implementations for judge
  tests/
    conftest.py
    tier1/           ← ~20 tests
    tier2/           ← ~15 tests
    tier3/           ← ~12 tests
    adversarial/     ← ~150 tests (not disclosed to agent)
    extension/       ← 16 tests
    held-out/        ← gitignored private suite
    reliability/     ← 7 chaos scenarios
    performance/     ← p95 latency benchmarks + thresholds.json
```

## Scoring (same 7 dimensions as mini-git)

| Dimension | Weight |
|-----------|--------|
| Functional completeness | 30% |
| Adversarial survival | 15% |
| Extension readiness | 10% |
| Mutation kill rate | 10% |
| Performance | 15% |
| Reliability | 10% |
| Code quality | 10% |

N/A weight redistribution (e.g. if mutation can't run) → proportional to functional + adversarial + extension.

## Judge rubric dimensions (both harnesses)

1. **Separation of concerns** — CLI vs core library vs storage. Score 0 if all logic is in main(). Score 100 if layers have clean interfaces independently testable.
2. **Data structure / storage abstraction quality** — clean model for the domain (RedisStore / SQLEngine class hierarchies). Score 0 if raw dicts scattered everywhere.
3. **Naming & pattern consistency** — variable names, function patterns consistent across files.
4. **Test quality & coverage** — substantive assertions (not just exit 0), edge cases covered.
5. **Scope discipline** — built exactly what was asked, no unrequested features, missing features documented.
