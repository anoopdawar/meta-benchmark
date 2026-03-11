# mini-redis

Build me a Redis-compatible key-value store in a single Python file called `mini_redis.py`.

## What I need

A command-line tool that stores data persistently and supports the following commands.

### Strings (implement first)

- `SET key value` — store a string value; print `OK`
- `GET key` — retrieve a value; print `"value"` or `(nil)` if missing
- `DEL key [key ...]` — delete keys; print `(integer) N` (count deleted)
- `EXISTS key` — print `(integer) 1` if present, `(integer) 0` if not
- `MSET key value [key value ...]` — set multiple keys; print `OK`
- `MGET key [key ...]` — get multiple values in order; missing keys print `(nil)` at position

### Lists

- `LPUSH key value [value ...]` — push to left; print `(integer) N` (new length)
- `RPUSH key value [value ...]` — push to right; print `(integer) N` (new length)
- `LPOP key` — pop from left; print `"value"` or `(nil)` if empty/missing
- `RPOP key` — pop from right; print `"value"` or `(nil)` if empty/missing
- `LRANGE key start stop` — get elements by index; 0-indexed, negatives count from end, stop inclusive

### Hashes

- `HSET key field value [field value ...]` — set fields; print `(integer) N` (new fields added, updates don't count)
- `HGET key field` — get one field; print `"value"` or `(nil)`
- `HDEL key field [field ...]` — delete fields; print `(integer) N` deleted
- `HGETALL key` — print alternating unquoted field/value lines, alphabetical by field name
- `HKEYS key` — print numbered list of field names, alphabetical

### TTL and expiry

- `EXPIRE key seconds` — set expiry in seconds; print `(integer) 1` if key exists, `(integer) 0` if not
- `TTL key` — print `(integer) N` remaining, `(integer) -1` (no TTL), `(integer) -2` (missing)
- `PERSIST key` — remove TTL; print `(integer) 1` if removed, `(integer) 0` otherwise

### Sets

- `SADD key member [member ...]` — add members; print `(integer) N` (new members added)
- `SREM key member [member ...]` — remove members; print `(integer) N` removed
- `SMEMBERS key` — list all members in lexicographic order; print `(empty set)` if empty
- `SISMEMBER key member` — print `(integer) 1` or `(integer) 0`

### Counters

- `INCR key` — increment integer value; print `(integer) N`; missing key starts at 0
- `DECR key` — decrement; print `(integer) N`; missing key starts at 0

## Architecture requirement

The CLI must be a thin shell. All data structure logic must live in a `RedisStore` class (or equivalent). The CLI layer parses arguments and delegates — no business logic in `if __name__ == "__main__"`.

## Data persistence

Store data in a JSON file. Use the `MINI_REDIS_DATA` environment variable for the path; if unset, use `./mini_redis.json` in the current working directory.

After every successful write operation, the store must be fully written to disk (call `fsync` or equivalent) before the process exits. Reads never write to disk.

TTL deadlines are stored as absolute Unix epoch timestamps so they survive process restarts.

## Output format

All output ends with a newline. Exact rules:

- String values: `"value"` — double-quoted. Special chars inside quotes: `"` → `\"`, `\` → `\\`, newline → `\n`
- Integer results: `(integer) N`
- Float scores (ZSCORE): use Python `f"{score:g}"` formatting, then quote: `"1"` or `"1.5"`
- Missing key/member: `(nil)`
- Numbered list: `1) item\n2) item\n...`
- Empty list: `(empty list)`, empty set: `(empty set)`
- HGETALL: alternating unquoted `field\nvalue\nfield\nvalue` lines

## Exit codes and errors

- Exit 0: success
- Exit 1: command error. Print error to stderr, nothing to stdout.
- Exit 2: I/O error

Error messages:
- Unknown command: `ERR unknown command '<cmd>'`
- Wrong arity: `ERR wrong number of arguments for '<cmd>' command`
- Wrong type: `WRONGTYPE Operation against a key holding the wrong kind of value`
- Non-integer INCR/DECR: `ERR value is not an integer or out of range`
- Invalid EXPIRE time: `ERR invalid expire time in 'EXPIRE' command`

## Example session

```
$ python mini_redis.py SET greeting "hello world"
OK
$ python mini_redis.py GET greeting
"hello world"
$ python mini_redis.py LPUSH mylist a b c
(integer) 3
$ python mini_redis.py LRANGE mylist 0 -1
1) "c"
2) "b"
3) "a"
$ python mini_redis.py HSET user name Alice age 30
(integer) 2
$ python mini_redis.py HGETALL user
age
30
name
Alice
$ python mini_redis.py EXPIRE greeting 60
(integer) 1
$ python mini_redis.py TTL greeting
(integer) 59
$ python mini_redis.py SADD tags python redis
(integer) 2
$ python mini_redis.py SMEMBERS tags
1) "python"
2) "redis"
```

## Tests

Write a pytest test suite covering every command's happy path, error conditions, persistence across restarts, and edge cases (empty values, unicode, type errors).
