#!/usr/bin/env python3
"""mini-redis: A Redis-compatible key-value store in a single Python file."""

import json
import os
import sys
import time


def escape_string(s):
    """Escape a string value for Redis-style output."""
    s = s.replace('\\', '\\\\')
    s = s.replace('"', '\\"')
    s = s.replace('\n', '\\n')
    return s


def format_string(s):
    """Format a string value with quotes."""
    return f'"{escape_string(s)}"'


class RedisStore:
    """Core data structure logic for the mini-redis store."""

    def __init__(self, data_path=None):
        if data_path is None:
            data_path = os.environ.get('MINI_REDIS_DATA', './mini_redis.json')
        self.data_path = data_path
        self._data = {}  # key -> {"type": str, "value": ..., "ttl": float|None}
        self._load()

    def _load(self):
        """Load data from disk."""
        if os.path.exists(self.data_path):
            try:
                with open(self.data_path, 'r') as f:
                    self._data = json.load(f)
            except (json.JSONDecodeError, IOError):
                self._data = {}

    def _save(self):
        """Save data to disk with fsync."""
        try:
            dir_path = os.path.dirname(os.path.abspath(self.data_path))
            os.makedirs(dir_path, exist_ok=True)
            tmp_path = self.data_path + '.tmp'
            with open(tmp_path, 'w') as f:
                json.dump(self._data, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.data_path)
        except IOError:
            sys.exit(2)

    def _is_expired(self, key):
        """Check if a key has expired."""
        if key not in self._data:
            return True
        entry = self._data[key]
        ttl = entry.get('ttl')
        if ttl is not None and time.time() >= ttl:
            return True
        return False

    def _clean_if_expired(self, key):
        """Remove key if expired. Returns True if it was expired and removed."""
        if key in self._data:
            entry = self._data[key]
            ttl = entry.get('ttl')
            if ttl is not None and time.time() >= ttl:
                del self._data[key]
                return True
        return False

    def _get_entry(self, key):
        """Get entry if exists and not expired, else None."""
        if key not in self._data:
            return None
        if self._clean_if_expired(key):
            return None
        return self._data[key]

    def _check_type(self, key, expected_type):
        """Check that key is of the expected type. Raise error if wrong type."""
        entry = self._get_entry(key)
        if entry is not None and entry['type'] != expected_type:
            raise TypeError("WRONGTYPE Operation against a key holding the wrong kind of value")

    # --- String commands ---

    def set(self, key, value):
        entry = self._get_entry(key)
        # SET always overwrites regardless of type
        self._data[key] = {'type': 'string', 'value': value, 'ttl': None}
        self._save()
        return 'OK'

    def get(self, key):
        entry = self._get_entry(key)
        if entry is None:
            return None
        if entry['type'] != 'string':
            raise TypeError("WRONGTYPE Operation against a key holding the wrong kind of value")
        return entry['value']

    def delete(self, keys):
        need_save = False
        count = 0
        for key in keys:
            # Check expiration first
            self._clean_if_expired(key)
            if key in self._data:
                del self._data[key]
                count += 1
                need_save = True
        if need_save:
            self._save()
        return count

    def exists(self, key):
        entry = self._get_entry(key)
        return 1 if entry is not None else 0

    def mset(self, pairs):
        for key, value in pairs:
            self._data[key] = {'type': 'string', 'value': value, 'ttl': None}
        self._save()
        return 'OK'

    def mget(self, keys):
        results = []
        for key in keys:
            entry = self._get_entry(key)
            if entry is None or entry['type'] != 'string':
                results.append(None)
            else:
                results.append(entry['value'])
        return results

    # --- List commands ---

    def lpush(self, key, values):
        self._check_type(key, 'list')
        entry = self._get_entry(key)
        if entry is None:
            self._data[key] = {'type': 'list', 'value': [], 'ttl': None}
            entry = self._data[key]
        for v in values:
            entry['value'].insert(0, v)
        self._save()
        return len(entry['value'])

    def rpush(self, key, values):
        self._check_type(key, 'list')
        entry = self._get_entry(key)
        if entry is None:
            self._data[key] = {'type': 'list', 'value': [], 'ttl': None}
            entry = self._data[key]
        for v in values:
            entry['value'].append(v)
        self._save()
        return len(entry['value'])

    def lpop(self, key):
        self._check_type(key, 'list')
        entry = self._get_entry(key)
        if entry is None or len(entry['value']) == 0:
            return None
        val = entry['value'].pop(0)
        if len(entry['value']) == 0:
            del self._data[key]
        self._save()
        return val

    def rpop(self, key):
        self._check_type(key, 'list')
        entry = self._get_entry(key)
        if entry is None or len(entry['value']) == 0:
            return None
        val = entry['value'].pop()
        if len(entry['value']) == 0:
            del self._data[key]
        self._save()
        return val

    def lrange(self, key, start, stop):
        self._check_type(key, 'list')
        entry = self._get_entry(key)
        if entry is None:
            return []
        lst = entry['value']
        length = len(lst)
        # Convert negative indices
        if start < 0:
            start = max(length + start, 0)
        if stop < 0:
            stop = length + stop
        if start > stop or start >= length:
            return []
        stop = min(stop, length - 1)
        return lst[start:stop + 1]

    # --- Hash commands ---

    def hset(self, key, pairs):
        self._check_type(key, 'hash')
        entry = self._get_entry(key)
        if entry is None:
            self._data[key] = {'type': 'hash', 'value': {}, 'ttl': None}
            entry = self._data[key]
        new_count = 0
        for field, value in pairs:
            if field not in entry['value']:
                new_count += 1
            entry['value'][field] = value
        self._save()
        return new_count

    def hget(self, key, field):
        self._check_type(key, 'hash')
        entry = self._get_entry(key)
        if entry is None:
            return None
        return entry['value'].get(field)

    def hdel(self, key, fields):
        self._check_type(key, 'hash')
        entry = self._get_entry(key)
        if entry is None:
            return 0
        count = 0
        for field in fields:
            if field in entry['value']:
                del entry['value'][field]
                count += 1
        if len(entry['value']) == 0:
            del self._data[key]
        if count > 0:
            self._save()
        return count

    def hgetall(self, key):
        self._check_type(key, 'hash')
        entry = self._get_entry(key)
        if entry is None:
            return {}
        return dict(entry['value'])

    def hkeys(self, key):
        self._check_type(key, 'hash')
        entry = self._get_entry(key)
        if entry is None:
            return []
        return sorted(entry['value'].keys())

    # --- TTL commands ---

    def expire(self, key, seconds):
        try:
            seconds = int(seconds)
        except (ValueError, TypeError):
            raise ValueError(f"ERR invalid expire time in 'EXPIRE' command")
        if seconds <= 0:
            raise ValueError(f"ERR invalid expire time in 'EXPIRE' command")
        entry = self._get_entry(key)
        if entry is None:
            return 0
        entry['ttl'] = time.time() + seconds
        self._save()
        return 1

    def ttl(self, key):
        if key not in self._data:
            return -2
        if self._clean_if_expired(key):
            return -2
        entry = self._data[key]
        ttl_val = entry.get('ttl')
        if ttl_val is None:
            return -1
        remaining = int(ttl_val - time.time())
        if remaining < 0:
            # expired
            del self._data[key]
            return -2
        return remaining

    def persist(self, key):
        entry = self._get_entry(key)
        if entry is None:
            return 0
        if entry.get('ttl') is not None:
            entry['ttl'] = None
            self._save()
            return 1
        return 0

    # --- Set commands ---

    def sadd(self, key, members):
        self._check_type(key, 'set')
        entry = self._get_entry(key)
        if entry is None:
            self._data[key] = {'type': 'set', 'value': [], 'ttl': None}
            entry = self._data[key]
        count = 0
        existing = set(entry['value'])
        for m in members:
            if m not in existing:
                entry['value'].append(m)
                existing.add(m)
                count += 1
        self._save()
        return count

    def srem(self, key, members):
        self._check_type(key, 'set')
        entry = self._get_entry(key)
        if entry is None:
            return 0
        count = 0
        for m in members:
            if m in entry['value']:
                entry['value'].remove(m)
                count += 1
        if len(entry['value']) == 0:
            del self._data[key]
        if count > 0:
            self._save()
        return count

    def smembers(self, key):
        self._check_type(key, 'set')
        entry = self._get_entry(key)
        if entry is None:
            return []
        return sorted(entry['value'])

    def sismember(self, key, member):
        self._check_type(key, 'set')
        entry = self._get_entry(key)
        if entry is None:
            return 0
        return 1 if member in entry['value'] else 0

    # --- Counter commands ---

    def incr(self, key):
        self._check_type(key, 'string')
        entry = self._get_entry(key)
        if entry is None:
            self._data[key] = {'type': 'string', 'value': '0', 'ttl': None}
            entry = self._data[key]
        try:
            val = int(entry['value'])
        except (ValueError, TypeError):
            raise ValueError("ERR value is not an integer or out of range")
        val += 1
        entry['value'] = str(val)
        self._save()
        return val

    def decr(self, key):
        self._check_type(key, 'string')
        entry = self._get_entry(key)
        if entry is None:
            self._data[key] = {'type': 'string', 'value': '0', 'ttl': None}
            entry = self._data[key]
        try:
            val = int(entry['value'])
        except (ValueError, TypeError):
            raise ValueError("ERR value is not an integer or out of range")
        val -= 1
        entry['value'] = str(val)
        self._save()
        return val


def run_command(args):
    """Parse arguments and delegate to RedisStore. Returns (output, exit_code)."""
    if len(args) == 0:
        print("ERR no command provided", file=sys.stderr)
        return 1

    store = RedisStore()
    cmd = args[0].upper()
    cmd_args = args[1:]

    try:
        if cmd == 'SET':
            if len(cmd_args) != 2:
                print(f"ERR wrong number of arguments for 'SET' command", file=sys.stderr)
                return 1
            result = store.set(cmd_args[0], cmd_args[1])
            print(result)
            return 0

        elif cmd == 'GET':
            if len(cmd_args) != 1:
                print(f"ERR wrong number of arguments for 'GET' command", file=sys.stderr)
                return 1
            result = store.get(cmd_args[0])
            if result is None:
                print("(nil)")
            else:
                print(format_string(result))
            return 0

        elif cmd == 'DEL':
            if len(cmd_args) < 1:
                print(f"ERR wrong number of arguments for 'DEL' command", file=sys.stderr)
                return 1
            result = store.delete(cmd_args)
            print(f"(integer) {result}")
            return 0

        elif cmd == 'EXISTS':
            if len(cmd_args) != 1:
                print(f"ERR wrong number of arguments for 'EXISTS' command", file=sys.stderr)
                return 1
            result = store.exists(cmd_args[0])
            print(f"(integer) {result}")
            return 0

        elif cmd == 'MSET':
            if len(cmd_args) < 2 or len(cmd_args) % 2 != 0:
                print(f"ERR wrong number of arguments for 'MSET' command", file=sys.stderr)
                return 1
            pairs = [(cmd_args[i], cmd_args[i + 1]) for i in range(0, len(cmd_args), 2)]
            result = store.mset(pairs)
            print(result)
            return 0

        elif cmd == 'MGET':
            if len(cmd_args) < 1:
                print(f"ERR wrong number of arguments for 'MGET' command", file=sys.stderr)
                return 1
            results = store.mget(cmd_args)
            for i, val in enumerate(results):
                if val is None:
                    print(f"{i + 1}) (nil)")
                else:
                    print(f"{i + 1}) {format_string(val)}")
            return 0

        elif cmd == 'LPUSH':
            if len(cmd_args) < 2:
                print(f"ERR wrong number of arguments for 'LPUSH' command", file=sys.stderr)
                return 1
            result = store.lpush(cmd_args[0], cmd_args[1:])
            print(f"(integer) {result}")
            return 0

        elif cmd == 'RPUSH':
            if len(cmd_args) < 2:
                print(f"ERR wrong number of arguments for 'RPUSH' command", file=sys.stderr)
                return 1
            result = store.rpush(cmd_args[0], cmd_args[1:])
            print(f"(integer) {result}")
            return 0

        elif cmd == 'LPOP':
            if len(cmd_args) != 1:
                print(f"ERR wrong number of arguments for 'LPOP' command", file=sys.stderr)
                return 1
            result = store.lpop(cmd_args[0])
            if result is None:
                print("(nil)")
            else:
                print(format_string(result))
            return 0

        elif cmd == 'RPOP':
            if len(cmd_args) != 1:
                print(f"ERR wrong number of arguments for 'RPOP' command", file=sys.stderr)
                return 1
            result = store.rpop(cmd_args[0])
            if result is None:
                print("(nil)")
            else:
                print(format_string(result))
            return 0

        elif cmd == 'LRANGE':
            if len(cmd_args) != 3:
                print(f"ERR wrong number of arguments for 'LRANGE' command", file=sys.stderr)
                return 1
            try:
                start = int(cmd_args[1])
                stop = int(cmd_args[2])
            except ValueError:
                print(f"ERR value is not an integer or out of range", file=sys.stderr)
                return 1
            result = store.lrange(cmd_args[0], start, stop)
            if not result:
                print("(empty list)")
            else:
                for i, val in enumerate(result):
                    print(f"{i + 1}) {format_string(val)}")
            return 0

        elif cmd == 'HSET':
            if len(cmd_args) < 3 or (len(cmd_args) - 1) % 2 != 0:
                print(f"ERR wrong number of arguments for 'HSET' command", file=sys.stderr)
                return 1
            key = cmd_args[0]
            pairs = [(cmd_args[i], cmd_args[i + 1]) for i in range(1, len(cmd_args), 2)]
            result = store.hset(key, pairs)
            print(f"(integer) {result}")
            return 0

        elif cmd == 'HGET':
            if len(cmd_args) != 2:
                print(f"ERR wrong number of arguments for 'HGET' command", file=sys.stderr)
                return 1
            result = store.hget(cmd_args[0], cmd_args[1])
            if result is None:
                print("(nil)")
            else:
                print(format_string(result))
            return 0

        elif cmd == 'HDEL':
            if len(cmd_args) < 2:
                print(f"ERR wrong number of arguments for 'HDEL' command", file=sys.stderr)
                return 1
            result = store.hdel(cmd_args[0], cmd_args[1:])
            print(f"(integer) {result}")
            return 0

        elif cmd == 'HGETALL':
            if len(cmd_args) != 1:
                print(f"ERR wrong number of arguments for 'HGETALL' command", file=sys.stderr)
                return 1
            result = store.hgetall(cmd_args[0])
            if not result:
                print("(empty list)")
            else:
                for field in sorted(result.keys()):
                    print(field)
                    print(result[field])
            return 0

        elif cmd == 'HKEYS':
            if len(cmd_args) != 1:
                print(f"ERR wrong number of arguments for 'HKEYS' command", file=sys.stderr)
                return 1
            result = store.hkeys(cmd_args[0])
            if not result:
                print("(empty list)")
            else:
                for i, key in enumerate(result):
                    print(f"{i + 1}) {format_string(key)}")
            return 0

        elif cmd == 'EXPIRE':
            if len(cmd_args) != 2:
                print(f"ERR wrong number of arguments for 'EXPIRE' command", file=sys.stderr)
                return 1
            try:
                result = store.expire(cmd_args[0], cmd_args[1])
            except ValueError as e:
                print(str(e), file=sys.stderr)
                return 1
            print(f"(integer) {result}")
            return 0

        elif cmd == 'TTL':
            if len(cmd_args) != 1:
                print(f"ERR wrong number of arguments for 'TTL' command", file=sys.stderr)
                return 1
            result = store.ttl(cmd_args[0])
            print(f"(integer) {result}")
            return 0

        elif cmd == 'PERSIST':
            if len(cmd_args) != 1:
                print(f"ERR wrong number of arguments for 'PERSIST' command", file=sys.stderr)
                return 1
            result = store.persist(cmd_args[0])
            print(f"(integer) {result}")
            return 0

        elif cmd == 'SADD':
            if len(cmd_args) < 2:
                print(f"ERR wrong number of arguments for 'SADD' command", file=sys.stderr)
                return 1
            result = store.sadd(cmd_args[0], cmd_args[1:])
            print(f"(integer) {result}")
            return 0

        elif cmd == 'SREM':
            if len(cmd_args) < 2:
                print(f"ERR wrong number of arguments for 'SREM' command", file=sys.stderr)
                return 1
            result = store.srem(cmd_args[0], cmd_args[1:])
            print(f"(integer) {result}")
            return 0

        elif cmd == 'SMEMBERS':
            if len(cmd_args) != 1:
                print(f"ERR wrong number of arguments for 'SMEMBERS' command", file=sys.stderr)
                return 1
            result = store.smembers(cmd_args[0])
            if not result:
                print("(empty set)")
            else:
                for i, member in enumerate(result):
                    print(f"{i + 1}) {format_string(member)}")
            return 0

        elif cmd == 'SISMEMBER':
            if len(cmd_args) != 2:
                print(f"ERR wrong number of arguments for 'SISMEMBER' command", file=sys.stderr)
                return 1
            result = store.sismember(cmd_args[0], cmd_args[1])
            print(f"(integer) {result}")
            return 0

        elif cmd == 'INCR':
            if len(cmd_args) != 1:
                print(f"ERR wrong number of arguments for 'INCR' command", file=sys.stderr)
                return 1
            try:
                result = store.incr(cmd_args[0])
            except ValueError as e:
                print(str(e), file=sys.stderr)
                return 1
            print(f"(integer) {result}")
            return 0

        elif cmd == 'DECR':
            if len(cmd_args) != 1:
                print(f"ERR wrong number of arguments for 'DECR' command", file=sys.stderr)
                return 1
            try:
                result = store.decr(cmd_args[0])
            except ValueError as e:
                print(str(e), file=sys.stderr)
                return 1
            print(f"(integer) {result}")
            return 0

        else:
            print(f"ERR unknown command '{args[0]}'", file=sys.stderr)
            return 1

    except TypeError as e:
        print(str(e), file=sys.stderr)
        return 1


def main():
    exit_code = run_command(sys.argv[1:])
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
