# mini-redis: Product Requirements Document

**Version:** 1.0.0
**Harness:** mini-redis

---

## 1. Overview

Agents implement a Redis-compatible key-value store as a single Python CLI. The CLI is a thin shell over a `RedisStore` class. Data is persisted to a JSON file. No networking required.

**Success criterion:** A fresh implementation produced from `prompt.md` alone passes ≥ 70% of the behavioral test suite and handles common adversarial inputs gracefully.

---

## 2. Scope

**In scope:** SET/GET/DEL/EXISTS/MSET/MGET, Lists (LPUSH/RPUSH/LPOP/RPOP/LRANGE), Hashes (HSET/HGET/HDEL/HGETALL/HKEYS), TTL (EXPIRE/TTL/PERSIST), Sets (SADD/SREM/SMEMBERS/SISMEMBER), Counters (INCR/DECR), JSON persistence, lazy TTL eviction.

**Out of scope:** Networking, RESP protocol, Pub/Sub, Lua, MULTI/EXEC transactions, `KEYS` glob patterns, streams, `SET` options (NX/XX/EX/PX/GET), `WITHSCORES`.

---

## 3. Interface Contract

### CLI invocation

```
python mini_redis.py COMMAND [arg ...]
```

Arguments are whitespace-delimited shell tokens. Values containing spaces must be quoted by the shell. The implementation receives them as `sys.argv[1:]`.

### Environment variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `MINI_REDIS_DATA` | Path to JSON data file | `./mini_redis.json` |

### Data file

Agent chooses internal JSON schema. File must be valid JSON on every read. If the file does not exist, the store is empty. Partial writes (crash before fsync) are not tested.

### Durability

Every successful mutation must call `os.fsync()` (or equivalent) on the data file before the process exits. Read-only commands must not write the file.

### TTL storage

Deadlines are stored as absolute Unix epoch timestamps (float). On load, expired keys are silently evicted before any command runs.

---

## 4. Output Format Specification

### Global rules

- All stdout ends with exactly one `\n`.
- Tests strip trailing whitespace before comparison.
- On error (exit ≠ 0): stderr contains the error message; stdout is empty.

### Result type → stdout

| Result | stdout |
|--------|--------|
| Successful mutation (no other value) | `OK` |
| String value | `"value"` — double-quoted |
| Integer | `(integer) N` |
| Float score | `f"{score:g}"` formatted, then quoted: `"1"` or `"1.5"` |
| Missing key/member | `(nil)` |
| Non-empty list/array | `1) item\n2) item\n...` (1-indexed) |
| Empty list | `(empty list)` |
| Empty set | `(empty set)` |

**String quoting:** inside double quotes, escape `"` → `\"`, `\` → `\\`, newline → `\n` (two chars).

**HGETALL exception:** alternating unquoted lines: `field1\nvalue1\nfield2\nvalue2\n...`. Alphabetical by field name. If hash is empty or key missing: `(empty list)`.

---

## 5. Command Reference

### Tier 1 — Strings

| Command | stdout on success | Error conditions |
|---------|------------------|-----------------|
| `SET key value` | `OK` | Wrong arity → exit 1 |
| `GET key` | `"value"` or `(nil)` | Wrong arity → exit 1 |
| `DEL key [key ...]` | `(integer) N` (deleted count) | No args → exit 1 |
| `EXISTS key` | `(integer) 1` or `(integer) 0` | Wrong arity → exit 1 |
| `MSET key value [key value ...]` | `OK` | Odd number of args → exit 1 |
| `MGET key [key ...]` | numbered list; `(nil)` at position of missing keys | No args → exit 1 |

### Tier 2 — Lists

| Command | stdout | Notes |
|---------|--------|-------|
| `LPUSH key value [value ...]` | `(integer) N` (new length) | Wrong type → exit 1, WRONGTYPE |
| `RPUSH key value [value ...]` | `(integer) N` | Wrong type → exit 1, WRONGTYPE |
| `LPOP key` | `"value"` or `(nil)` | Wrong type → exit 1 |
| `RPOP key` | `"value"` or `(nil)` | Wrong type → exit 1 |
| `LRANGE key start stop` | numbered list or `(empty list)` | Negative indices from end; stop inclusive; wrong type → exit 1 |

### Tier 2 — Hashes

| Command | stdout | Notes |
|---------|--------|-------|
| `HSET key field value [field value ...]` | `(integer) N` (new fields only) | Wrong type → exit 1 |
| `HGET key field` | `"value"` or `(nil)` | Wrong type → exit 1 |
| `HDEL key field [field ...]` | `(integer) N` deleted | Wrong type → exit 1 |
| `HGETALL key` | alternating field/value lines (alphabetical) or `(empty list)` | Wrong type → exit 1 |
| `HKEYS key` | numbered list of quoted field names (alphabetical) or `(empty list)` | Wrong type → exit 1. Note: field names are string-quoted per the standard list format (`1) "field"`); only `HGETALL` output has unquoted field names. |

### Tier 3 — TTL/Expiry

| Command | stdout | Notes |
|---------|--------|-------|
| `EXPIRE key seconds` | `(integer) 1` or `(integer) 0` | seconds ≤ 0 or non-integer → exit 1, `ERR invalid expire time in 'EXPIRE' command` |
| `TTL key` | `(integer) N` remaining / `(integer) -1` (no TTL) / `(integer) -2` (missing) | |
| `PERSIST key` | `(integer) 1` (TTL removed) / `(integer) 0` (no TTL or missing) | |

### Tier 3 — Sets

| Command | stdout | Notes |
|---------|--------|-------|
| `SADD key member [member ...]` | `(integer) N` (new members) | Wrong type → exit 1 |
| `SREM key member [member ...]` | `(integer) N` removed | Wrong type → exit 1 |
| `SMEMBERS key` | numbered list (lexicographic) or `(empty set)` | Wrong type → exit 1 |
| `SISMEMBER key member` | `(integer) 1` or `(integer) 0` | Wrong type → exit 1 |

### Tier 3 — Counters

| Command | stdout | Notes |
|---------|--------|-------|
| `INCR key` | `(integer) N` | Missing key starts at 0; non-integer value → exit 1 |
| `DECR key` | `(integer) N` | Missing key starts at 0; non-integer value → exit 1 |

---

## 6. Ordering Rules

| Operation | Order |
|-----------|-------|
| LRANGE | Left-to-right insertion order |
| HGETALL, HKEYS | Alphabetical by field name |
| SMEMBERS | Lexicographic |
| MGET | Preserves argument order; missing → `(nil)` |

---

## 7. Error Message Templates

| Condition | stderr |
|-----------|--------|
| Unknown command | `ERR unknown command '<cmd>'` |
| Wrong arity | `ERR wrong number of arguments for '<cmd>' command` |
| Wrong type | `WRONGTYPE Operation against a key holding the wrong kind of value` |
| Non-integer INCR/DECR | `ERR value is not an integer or out of range` |
| Invalid EXPIRE time | `ERR invalid expire time in 'EXPIRE' command` |
| I/O failure | `ERR persistence failure: <reason>` |

---

## 8. Performance Targets

| Benchmark | Target p95 | Fail p95 |
|-----------|-----------|---------|
| GET from 10k-key store | 1.0s | 5.0s |
| LRANGE on 10k-element list | 2.0s | 10.0s |
| HGETALL on 1k-field hash | 1.0s | 5.0s |

---

## 9. Reliability Requirements

1. Data survives a clean process exit (confirmed by subsequent read)
2. Corrupt JSON file: process must exit non-zero with stderr message, not crash with traceback
3. Missing data file: treat as empty store, do not crash
4. EXPIRE deadline persists across process restarts (stored as epoch timestamp)

---

## 10. Architecture Requirement

The implementation must have a clear `RedisStore` class (or equivalent) that owns all data structure and persistence logic. The CLI layer (argument parsing, stdout printing) must not contain data structure logic. This is evaluated by the LLM judge.
