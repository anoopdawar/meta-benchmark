import json
import os
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional


class RedisError(Exception):
    pass


class UnknownCommandError(RedisError):
    def __init__(self, cmd: str):
        super().__init__(f"ERR unknown command '{cmd}'")


class ArityError(RedisError):
    def __init__(self, cmd: str):
        super().__init__(f"ERR wrong number of arguments for '{cmd}' command")


class WrongTypeError(RedisError):
    def __init__(self):
        super().__init__("WRONGTYPE Operation against a key holding the wrong kind of value")


class IntegerValueError(RedisError):
    def __init__(self):
        super().__init__("ERR value is not an integer or out of range")


class InvalidExpireError(RedisError):
    def __init__(self):
        super().__init__("ERR invalid expire time in 'EXPIRE' command")


def quote_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def format_integer(value: int) -> str:
    return f"(integer) {value}"


def format_nil() -> str:
    return "(nil)"


def format_numbered_list(items: List[str], quoted: bool = True, empty_label: str = "(empty list)") -> str:
    if not items:
        return empty_label
    lines = []
    for idx, item in enumerate(items, start=1):
        rendered = quote_string(item) if quoted else item
        lines.append(f"{idx}) {rendered}")
    return "\n".join(lines)


class RedisStore:
    def __init__(self, path: Optional[str] = None):
        self.path = path or os.environ.get("MINI_REDIS_DATA", os.path.join(os.getcwd(), "mini_redis.json"))
        self._data: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.path):
            self._data = {}
            return
        with open(self.path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            self._data = {}
            return
        self._data = raw
        self._cleanup_expired()

    def _save(self) -> None:
        directory = os.path.dirname(os.path.abspath(self.path)) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".mini_redis_", dir=directory, text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.path)
            dir_fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except Exception:
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except Exception:
                pass
            raise

    def _now(self) -> float:
        return time.time()

    def _is_expired_entry(self, entry: Dict[str, Any]) -> bool:
        expire_at = entry.get("expire_at")
        return expire_at is not None and expire_at <= self._now()

    def _cleanup_expired(self) -> bool:
        expired = [k for k, v in self._data.items() if self._is_expired_entry(v)]
        for k in expired:
            del self._data[k]
        return bool(expired)

    def _expire_if_needed(self, key: str) -> bool:
        entry = self._data.get(key)
        if entry is None:
            return False
        if self._is_expired_entry(entry):
            del self._data[key]
            return True
        return False

    def _get_entry(self, key: str) -> Optional[Dict[str, Any]]:
        self._expire_if_needed(key)
        return self._data.get(key)

    def _require_type(self, key: str, expected: str) -> Optional[Dict[str, Any]]:
        entry = self._get_entry(key)
        if entry is None:
            return None
        if entry["type"] != expected:
            raise WrongTypeError()
        return entry

    def _set_entry(self, key: str, typ: str, value: Any, expire_at: Optional[float] = None) -> None:
        self._data[key] = {"type": typ, "value": value, "expire_at": expire_at}

    def _delete_key_if_empty_collection(self, key: str) -> None:
        entry = self._data.get(key)
        if entry is None:
            return
        if entry["type"] in {"list", "hash", "set"} and not entry["value"]:
            del self._data[key]

    # Strings
    def set(self, key: str, value: str) -> str:
        self._set_entry(key, "string", value, None)
        self._save()
        return "OK"

    def get(self, key: str) -> Optional[str]:
        entry = self._get_entry(key)
        if entry is None:
            return None
        if entry["type"] != "string":
            raise WrongTypeError()
        return entry["value"]

    def delete(self, keys: List[str]) -> int:
        deleted = 0
        changed = False
        for key in keys:
            self._expire_if_needed(key)
            if key in self._data:
                del self._data[key]
                deleted += 1
                changed = True
        if changed:
            self._save()
        return deleted

    def exists(self, key: str) -> int:
        return 1 if self._get_entry(key) is not None else 0

    def mset(self, pairs: List[str]) -> str:
        for i in range(0, len(pairs), 2):
            key = pairs[i]
            value = pairs[i + 1]
            self._set_entry(key, "string", value, None)
        self._save()
        return "OK"

    def mget(self, keys: List[str]) -> List[Optional[str]]:
        result = []
        for key in keys:
            entry = self._get_entry(key)
            if entry is None:
                result.append(None)
            elif entry["type"] != "string":
                raise WrongTypeError()
            else:
                result.append(entry["value"])
        return result

    # Lists
    def lpush(self, key: str, values: List[str]) -> int:
        entry = self._require_type(key, "list")
        expire_at = entry["expire_at"] if entry else None
        current = list(entry["value"]) if entry else []
        for value in values:
            current.insert(0, value)
        self._set_entry(key, "list", current, expire_at)
        self._save()
        return len(current)

    def rpush(self, key: str, values: List[str]) -> int:
        entry = self._require_type(key, "list")
        expire_at = entry["expire_at"] if entry else None
        current = list(entry["value"]) if entry else []
        current.extend(values)
        self._set_entry(key, "list", current, expire_at)
        self._save()
        return len(current)

    def lpop(self, key: str) -> Optional[str]:
        entry = self._require_type(key, "list")
        if entry is None or not entry["value"]:
            return None
        value = entry["value"].pop(0)
        self._delete_key_if_empty_collection(key)
        self._save()
        return value

    def rpop(self, key: str) -> Optional[str]:
        entry = self._require_type(key, "list")
        if entry is None or not entry["value"]:
            return None
        value = entry["value"].pop()
        self._delete_key_if_empty_collection(key)
        self._save()
        return value

    def lrange(self, key: str, start: int, stop: int) -> List[str]:
        entry = self._require_type(key, "list")
        if entry is None:
            return []
        values = entry["value"]
        n = len(values)
        if n == 0:
            return []
        if start < 0:
            start += n
        if stop < 0:
            stop += n
        if start < 0:
            start = 0
        if stop < 0:
            return []
        if start >= n:
            return []
        if stop >= n:
            stop = n - 1
        if start > stop:
            return []
        return values[start:stop + 1]

    # Hashes
    def hset(self, key: str, pairs: List[str]) -> int:
        entry = self._require_type(key, "hash")
        expire_at = entry["expire_at"] if entry else None
        current = dict(entry["value"]) if entry else {}
        added = 0
        for i in range(0, len(pairs), 2):
            field = pairs[i]
            value = pairs[i + 1]
            if field not in current:
                added += 1
            current[field] = value
        self._set_entry(key, "hash", current, expire_at)
        self._save()
        return added

    def hget(self, key: str, field: str) -> Optional[str]:
        entry = self._require_type(key, "hash")
        if entry is None:
            return None
        return entry["value"].get(field)

    def hdel(self, key: str, fields: List[str]) -> int:
        entry = self._require_type(key, "hash")
        if entry is None:
            return 0
        deleted = 0
        for field in fields:
            if field in entry["value"]:
                del entry["value"][field]
                deleted += 1
        if deleted:
            self._delete_key_if_empty_collection(key)
            self._save()
        return deleted

    def hgetall(self, key: str) -> List[str]:
        entry = self._require_type(key, "hash")
        if entry is None:
            return []
        result = []
        for field in sorted(entry["value"].keys()):
            result.append(field)
            result.append(entry["value"][field])
        return result

    def hkeys(self, key: str) -> List[str]:
        entry = self._require_type(key, "hash")
        if entry is None:
            return []
        return sorted(entry["value"].keys())

    # TTL
    def expire(self, key: str, seconds: int) -> int:
        if seconds <= 0:
            raise InvalidExpireError()
        entry = self._get_entry(key)
        if entry is None:
            return 0
        entry["expire_at"] = self._now() + seconds
        self._save()
        return 1

    def ttl(self, key: str) -> int:
        entry = self._get_entry(key)
        if entry is None:
            return -2
        expire_at = entry.get("expire_at")
        if expire_at is None:
            return -1
        remaining = int(expire_at - self._now())
        if remaining < 0:
            self._expire_if_needed(key)
            return -2
        return remaining

    def persist(self, key: str) -> int:
        entry = self._get_entry(key)
        if entry is None:
            return 0
        if entry.get("expire_at") is None:
            return 0
        entry["expire_at"] = None
        self._save()
        return 1

    # Sets
    def sadd(self, key: str, members: List[str]) -> int:
        entry = self._require_type(key, "set")
        expire_at = entry["expire_at"] if entry else None
        current = set(entry["value"]) if entry else set()
        before = len(current)
        current.update(members)
        added = len(current) - before
        self._set_entry(key, "set", sorted(current), expire_at)
        self._save()
        return added

    def srem(self, key: str, members: List[str]) -> int:
        entry = self._require_type(key, "set")
        if entry is None:
            return 0
        current = set(entry["value"])
        deleted = 0
        for member in members:
            if member in current:
                current.remove(member)
                deleted += 1
        if deleted:
            if current:
                entry["value"] = sorted(current)
            else:
                del self._data[key]
            self._save()
        return deleted

    def smembers(self, key: str) -> List[str]:
        entry = self._require_type(key, "set")
        if entry is None:
            return []
        return sorted(entry["value"])

    def sismember(self, key: str, member: str) -> int:
        entry = self._require_type(key, "set")
        if entry is None:
            return 0
        return 1 if member in set(entry["value"]) else 0

    # Counters
    def incr(self, key: str) -> int:
        return self._incrby(key, 1)

    def decr(self, key: str) -> int:
        return self._incrby(key, -1)

    def _incrby(self, key: str, delta: int) -> int:
        entry = self._get_entry(key)
        expire_at = entry["expire_at"] if entry else None
        if entry is None:
            value = 0
        else:
            if entry["type"] != "string":
                raise WrongTypeError()
            try:
                value = int(entry["value"])
            except (ValueError, TypeError):
                raise IntegerValueError()
        value += delta
        self._set_entry(key, "string", str(value), expire_at)
        self._save()
        return value


def parse_int(value: str, error_factory) -> int:
    try:
        return int(value)
    except ValueError:
        raise error_factory()


def execute_command(store: RedisStore, argv: List[str]) -> str:
    if not argv:
        raise UnknownCommandError("")
    cmd = argv[0].upper()
    args = argv[1:]

    if cmd == "SET":
        if len(args) != 2:
            raise ArityError("SET")
        return store.set(args[0], args[1])

    if cmd == "GET":
        if len(args) != 1:
            raise ArityError("GET")
        value = store.get(args[0])
        return format_nil() if value is None else quote_string(value)

    if cmd == "DEL":
        if len(args) < 1:
            raise ArityError("DEL")
        return format_integer(store.delete(args))

    if cmd == "EXISTS":
        if len(args) != 1:
            raise ArityError("EXISTS")
        return format_integer(store.exists(args[0]))

    if cmd == "MSET":
        if len(args) < 2 or len(args) % 2 != 0:
            raise ArityError("MSET")
        return store.mset(args)

    if cmd == "MGET":
        if len(args) < 1:
            raise ArityError("MGET")
        values = store.mget(args)
        rendered = []
        for value in values:
            rendered.append(format_nil() if value is None else quote_string(value))
        return "\n".join(rendered)

    if cmd == "LPUSH":
        if len(args) < 2:
            raise ArityError("LPUSH")
        return format_integer(store.lpush(args[0], args[1:]))

    if cmd == "RPUSH":
        if len(args) < 2:
            raise ArityError("RPUSH")
        return format_integer(store.rpush(args[0], args[1:]))

    if cmd == "LPOP":
        if len(args) != 1:
            raise ArityError("LPOP")
        value = store.lpop(args[0])
        return format_nil() if value is None else quote_string(value)

    if cmd == "RPOP":
        if len(args) != 1:
            raise ArityError("RPOP")
        value = store.rpop(args[0])
        return format_nil() if value is None else quote_string(value)

    if cmd == "LRANGE":
        if len(args) != 3:
            raise ArityError("LRANGE")
        start = parse_int(args[1], lambda: RedisError("ERR value is not an integer or out of range"))
        stop = parse_int(args[2], lambda: RedisError("ERR value is not an integer or out of range"))
        values = store.lrange(args[0], start, stop)
        return format_numbered_list(values, quoted=True, empty_label="(empty list)")

    if cmd == "HSET":
        if len(args) < 3 or len(args) % 2 == 0:
            raise ArityError("HSET")
        return format_integer(store.hset(args[0], args[1:]))

    if cmd == "HGET":
        if len(args) != 2:
            raise ArityError("HGET")
        value = store.hget(args[0], args[1])
        return format_nil() if value is None else quote_string(value)

    if cmd == "HDEL":
        if len(args) < 2:
            raise ArityError("HDEL")
        return format_integer(store.hdel(args[0], args[1:]))

    if cmd == "HGETALL":
        if len(args) != 1:
            raise ArityError("HGETALL")
        values = store.hgetall(args[0])
        return "\n".join(values)

    if cmd == "HKEYS":
        if len(args) != 1:
            raise ArityError("HKEYS")
        return format_numbered_list(store.hkeys(args[0]), quoted=False, empty_label="(empty list)")

    if cmd == "EXPIRE":
        if len(args) != 2:
            raise ArityError("EXPIRE")
        seconds = parse_int(args[1], InvalidExpireError)
        return format_integer(store.expire(args[0], seconds))

    if cmd == "TTL":
        if len(args) != 1:
            raise ArityError("TTL")
        return format_integer(store.ttl(args[0]))

    if cmd == "PERSIST":
        if len(args) != 1:
            raise ArityError("PERSIST")
        return format_integer(store.persist(args[0]))

    if cmd == "SADD":
        if len(args) < 2:
            raise ArityError("SADD")
        return format_integer(store.sadd(args[0], args[1:]))

    if cmd == "SREM":
        if len(args) < 2:
            raise ArityError("SREM")
        return format_integer(store.srem(args[0], args[1:]))

    if cmd == "SMEMBERS":
        if len(args) != 1:
            raise ArityError("SMEMBERS")
        members = store.smembers(args[0])
        return format_numbered_list(members, quoted=True, empty_label="(empty set)")

    if cmd == "SISMEMBER":
        if len(args) != 2:
            raise ArityError("SISMEMBER")
        return format_integer(store.sismember(args[0], args[1]))

    if cmd == "INCR":
        if len(args) != 1:
            raise ArityError("INCR")
        return format_integer(store.incr(args[0]))

    if cmd == "DECR":
        if len(args) != 1:
            raise ArityError("DECR")
        return format_integer(store.decr(args[0]))

    raise UnknownCommandError(argv[0])


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        store = RedisStore()
        output = execute_command(store, argv)
        sys.stdout.write(output + "\n")
        return 0
    except RedisError as e:
        sys.stderr.write(str(e) + "\n")
        return 1
    except OSError as e:
        sys.stderr.write(str(e) + "\n")
        return 2
    except json.JSONDecodeError as e:
        sys.stderr.write(str(e) + "\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())
