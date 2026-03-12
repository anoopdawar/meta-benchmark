#!/usr/bin/env python

import sys
import os
import json
import time
from typing import Any, Dict, List, Optional, Set, Tuple, Union

# --- Custom Exceptions ---

class CommandError(Exception):
    """Custom exception for command-related errors."""
    pass

# --- RedisStore Class ---

class RedisStore:
    """
    Manages all data, persistence, and Redis command logic.
    """
    def __init__(self, data_path: str):
        self.data_path = data_path
        self.data: Dict[str, Dict[str, Any]] = {}
        self.expirations: Dict[str, float] = {}

    def load(self):
        """Loads data from the JSON file."""
        if not os.path.exists(self.data_path):
            return
        try:
            with open(self.data_path, 'r') as f:
                content = f.read()
                if not content:
                    return
                persisted = json.loads(content)
                self.data = persisted.get('data', {})
                self.expirations = persisted.get('expirations', {})
                # Convert lists back to sets for 'set' types
                for key, item in self.data.items():
                    if item.get('type') == 'set':
                        item['value'] = set(item['value'])
        except (IOError, json.JSONDecodeError) as e:
            raise IOError(f"Failed to load data file: {e}")

    def save(self):
        """Saves the current state to the JSON file atomically and with fsync."""
        self._cleanup_expired_keys()
        temp_path = self.data_path + ".tmp"
        
        data_to_save = {'expirations': self.expirations, 'data': {}}
        for key, item in self.data.items():
            if item['type'] == 'set':
                data_to_save['data'][key] = {
                    'type': 'set',
                    'value': sorted(list(item['value']))
                }
            else:
                data_to_save['data'][key] = item

        try:
            with open(temp_path, 'w') as f:
                json.dump(data_to_save, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, self.data_path)
        except IOError as e:
            raise IOError(f"Failed to save data file: {e}")

    def _check_expiry(self, key: str) -> bool:
        """Checks if a key is expired. If so, deletes it and returns False."""
        if key in self.expirations and self.expirations[key] < time.time():
            self.delete(key)
            return False
        return True

    def _cleanup_expired_keys(self):
        """Iterates through all keys and removes expired ones."""
        expired_keys = [
            key for key in self.expirations if self.expirations[key] < time.time()
        ]
        if expired_keys:
            self.delete(*expired_keys)

    def _get_value_and_check_type(self, key: str, expected_type: str) -> Optional[Any]:
        """Retrieves a value, checking for expiry and correct type."""
        if not self._check_expiry(key):
            return None
        item = self.data.get(key)
        if item is None:
            return None
        if item['type'] != expected_type:
            raise CommandError("WRONGTYPE Operation against a key holding the wrong kind of value")
        return item['value']

    def _ensure_type_or_create(self, key: str, expected_type: str) -> Any:
        """
        Gets a value of a certain type, creating an empty one if the key is missing.
        Raises WRONGTYPE if the key exists with a different type.
        """
        if not self._check_expiry(key):
            # Key was expired and deleted, so we can create a new one
            pass

        item = self.data.get(key)
        if item is None:
            if expected_type == 'list': value = []
            elif expected_type == 'hash': value = {}
            elif expected_type == 'set': value = set()
            else: raise TypeError(f"Cannot create unknown type {expected_type}")
            
            self.data[key] = {'type': expected_type, 'value': value}
            return value
        
        if item['type'] != expected_type:
            raise CommandError("WRONGTYPE Operation against a key holding the wrong kind of value")
        
        return item['value']

    # --- String Commands ---
    def set(self, key: str, value: str):
        self.data[key] = {'type': 'string', 'value': str(value)}
        self.expirations.pop(key, None)

    def get(self, key: str) -> Optional[str]:
        return self._get_value_and_check_type(key, 'string')

    def delete(self, *keys: str) -> int:
        deleted_count = 0
        for key in keys:
            if self._check_expiry(key) and key in self.data:
                del self.data[key]
                self.expirations.pop(key, None)
                deleted_count += 1
        return deleted_count

    def exists(self, key: str) -> int:
        return 1 if self._check_expiry(key) and key in self.data else 0

    def mset(self, *args: str):
        for i in range(0, len(args), 2):
            self.set(args[i], args[i+1])

    def mget(self, *keys: str) -> List[Optional[str]]:
        return [self.get(key) for key in keys]

    # --- List Commands ---
    def lpush(self, key: str, *values: str) -> int:
        lst = self._ensure_type_or_create(key, 'list')
        for value in reversed(values):
            lst.insert(0, value)
        return len(lst)

    def rpush(self, key: str, *values: str) -> int:
        lst = self._ensure_type_or_create(key, 'list')
        lst.extend(values)
        return len(lst)

    def lpop(self, key: str) -> Optional[str]:
        lst = self._get_value_and_check_type(key, 'list')
        if not lst:
            return None
        val = lst.pop(0)
        if not lst:
            self.delete(key)
        return val

    def rpop(self, key: str) -> Optional[str]:
        lst = self._get_value_and_check_type(key, 'list')
        if not lst:
            return None
        val = lst.pop()
        if not lst:
            self.delete(key)
        return val

    def lrange(self, key: str, start: int, stop: int) -> List[str]:
        lst = self._get_value_and_check_type(key, 'list')
        if not lst:
            return []
        
        # Redis stop is inclusive, Python slicing is exclusive
        if stop == -1:
            return lst[start:]
        return lst[start:stop+1]

    # --- Hash Commands ---
    def hset(self, key: str, *args: str) -> int:
        h = self._ensure_type_or_create(key, 'hash')
        added_count = 0
        for i in range(0, len(args), 2):
            field, value = args[i], args[i+1]
            if field not in h:
                added_count += 1
            h[field] = value
        return added_count

    def hget(self, key: str, field: str) -> Optional[str]:
        h = self._get_value_and_check_type(key, 'hash')
        return h.get(field) if h else None

    def hdel(self, key: str, *fields: str) -> int:
        h = self._get_value_and_check_type(key, 'hash')
        if not h:
            return 0
        deleted_count = 0
        for field in fields:
            if field in h:
                del h[field]
                deleted_count += 1
        if not h:
            self.delete(key)
        return deleted_count

    def hgetall(self, key: str) -> List[Tuple[str, str]]:
        h = self._get_value_and_check_type(key, 'hash')
        if not h:
            return []
        return sorted(h.items())

    def hkeys(self, key: str) -> List[str]:
        h = self._get_value_and_check_type(key, 'hash')
        if not h:
            return []
        return sorted(h.keys())

    # --- TTL and Expiry Commands ---
    def expire(self, key: str, seconds: int) -> int:
        if not self.exists(key):
            return 0
        self.expirations[key] = time.time() + seconds
        return 1

    def ttl(self, key: str) -> int:
        if not self._check_expiry(key):
            return -2
        if key not in self.data:
            return -2
        if key not in self.expirations:
            return -1
        return int(self.expirations[key] - time.time())

    def persist(self, key: str) -> int:
        if self.exists(key) and key in self.expirations:
            del self.expirations[key]
            return 1
        return 0

    # --- Set Commands ---
    def sadd(self, key: str, *members: str) -> int:
        s = self._ensure_type_or_create(key, 'set')
        added_count = 0
        for member in members:
            if member not in s:
                s.add(member)
                added_count += 1
        return added_count

    def srem(self, key: str, *members: str) -> int:
        s = self._get_value_and_check_type(key, 'set')
        if not s:
            return 0
        removed_count = 0
        for member in members:
            if member in s:
                s.remove(member)
                removed_count += 1
        if not s:
            self.delete(key)
        return removed_count

    def smembers(self, key: str) -> List[str]:
        s = self._get_value_and_check_type(key, 'set')
        return sorted(list(s)) if s else []

    def sismember(self, key: str, member: str) -> int:
        s = self._get_value_and_check_type(key, 'set')
        return 1 if s and member in s else 0

    # --- Counter Commands ---
    def _change_counter(self, key: str, amount: int) -> int:
        val_str = self._get_value_and_check_type(key, 'string')
        current_val = 0
        if val_str is not None:
            try:
                current_val = int(val_str)
            except ValueError:
                raise CommandError("ERR value is not an integer or out of range")
        
        new_val = current_val + amount
        self.set(key, str(new_val))
        return new_val

    def incr(self, key: str) -> int:
        return self._change_counter(key, 1)

    def decr(self, key: str) -> int:
        return self._change_counter(key, -1)

# --- CLI Application Class ---

class MiniRedisCLI:
    """
    Parses command-line arguments, calls RedisStore, and formats output.
    """
    def __init__(self, store: RedisStore):
        self.store = store
        self.write_commands = {
            'SET', 'DEL', 'MSET', 'LPUSH', 'RPUSH', 'LPOP', 'RPOP',
            'HSET', 'HDEL', 'EXPIRE', 'PERSIST', 'SADD', 'SREM',
            'INCR', 'DECR'
        }
        self.commands = {
            # Strings
            'SET': self.handle_set, 'GET': self.handle_get, 'DEL': self.handle_del,
            'EXISTS': self.handle_exists, 'MSET': self.handle_mset, 'MGET': self.handle_mget,
            # Lists
            'LPUSH': self.handle_lpush, 'RPUSH': self.handle_rpush, 'LPOP': self.handle_lpop,
            'RPOP': self.handle_rpop, 'LRANGE': self.handle_lrange,
            # Hashes
            'HSET': self.handle_hset, 'HGET': self.handle_hget, 'HDEL': self.handle_hdel,
            'HGETALL': self.handle_hgetall, 'HKEYS': self.handle_hkeys,
            # TTL
            'EXPIRE': self.handle_expire, 'TTL': self.handle_ttl, 'PERSIST': self.handle_persist,
            # Sets
            'SADD': self.handle_sadd, 'SREM': self.handle_srem, 'SMEMBERS': self.handle_smembers,
            'SISMEMBER': self.handle_sismember,
            # Counters
            'INCR': self.handle_incr, 'DECR': self.handle_decr,
        }

    def run(self, argv: List[str]):
        if not argv:
            # No command provided, exit gracefully.
            sys.exit(0)

        command_name = argv[0].upper()
        args = argv[1:]

        handler = self.commands.get(command_name)
        if not handler:
            raise CommandError(f"ERR unknown command '{argv[0]}'")

        try:
            output = handler(args)
            if output is not None:
                sys.stdout.write(output + '\n')
            
            if command_name in self.write_commands:
                self.store.save()
            
            sys.exit(0)
        except CommandError as e:
            sys.stderr.write(str(e) + '\n')
            sys.exit(1)

    # --- Output Formatters ---
    def _format_string(self, s: Optional[str]) -> str:
        if s is None:
            return "(nil)"
        escaped = s.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
        return f'"{escaped}"'

    def _format_integer(self, i: int) -> str:
        return f"(integer) {i}"

    def _format_numbered_list(self, items: List[str], if_empty: str) -> str:
        if not items:
            return if_empty
        return "\n".join(f"{i}) {self._format_string(item)}" for i, item in enumerate(items, 1))

    # --- String Handlers ---
    def handle_set(self, args: List[str]) -> str:
        if len(args) != 2: raise CommandError("ERR wrong number of arguments for 'SET' command")
        self.store.set(args[0], args[1])
        return "OK"

    def handle_get(self, args: List[str]) -> str:
        if len(args) != 1: raise CommandError("ERR wrong number of arguments for 'GET' command")
        return self._format_string(self.store.get(args[0]))

    def handle_del(self, args: List[str]) -> str:
        if not args: raise CommandError("ERR wrong number of arguments for 'DEL' command")
        return self._format_integer(self.store.delete(*args))

    def handle_exists(self, args: List[str]) -> str:
        if len(args) != 1: raise CommandError("ERR wrong number of arguments for 'EXISTS' command")
        return self._format_integer(self.store.exists(args[0]))

    def handle_mset(self, args: List[str]) -> str:
        if not args or len(args) % 2 != 0: raise CommandError("ERR wrong number of arguments for 'MSET' command")
        self.store.mset(*args)
        return "OK"

    def handle_mget(self, args: List[str]) -> str:
        if not args: raise CommandError("ERR wrong number of arguments for 'MGET' command")
        results = self.store.mget(*args)
        return "\n".join(self._format_string(r) for r in results)

    # --- List Handlers ---
    def handle_lpush(self, args: List[str]) -> str:
        if len(args) < 2: raise CommandError("ERR wrong number of arguments for 'LPUSH' command")
        return self._format_integer(self.store.lpush(args[0], *args[1:]))

    def handle_rpush(self, args: List[str]) -> str:
        if len(args) < 2: raise CommandError("ERR wrong number of arguments for 'RPUSH' command")
        return self._format_integer(self.store.rpush(args[0], *args[1:]))

    def handle_lpop(self, args: List[str]) -> str:
        if len(args) != 1: raise CommandError("ERR wrong number of arguments for 'LPOP' command")
        return self._format_string(self.store.lpop(args[0]))

    def handle_rpop(self, args: List[str]) -> str:
        if len(args) != 1: raise CommandError("ERR wrong number of arguments for 'RPOP' command")
        return self._format_string(self.store.rpop(args[0]))

    def handle_lrange(self, args: List[str]) -> str:
        if len(args) != 3: raise CommandError("ERR wrong number of arguments for 'LRANGE' command")
        try:
            start, stop = int(args[1]), int(args[2])
        except ValueError:
            raise CommandError("ERR value is not an integer or out of range")
        result = self.store.lrange(args[0], start, stop)
        return self._format_numbered_list(result, "(empty list)")

    # --- Hash Handlers ---
    def handle_hset(self, args: List[str]) -> str:
        if len(args) < 3 or len(args) % 2 != 1: raise CommandError("ERR wrong number of arguments for 'HSET' command")
        return self._format_integer(self.store.hset(args[0], *args[1:]))

    def handle_hget(self, args: List[str]) -> str:
        if len(args) != 2: raise CommandError("ERR wrong number of arguments for 'HGET' command")
        return self._format_string(self.store.hget(args[0], args[1]))

    def handle_hdel(self, args: List[str]) -> str:
        if len(args) < 2: raise CommandError("ERR wrong number of arguments for 'HDEL' command")
        return self._format_integer(self.store.hdel(args[0], *args[1:]))

    def handle_hgetall(self, args: List[str]) -> str:
        if len(args) != 1: raise CommandError("ERR wrong number of arguments for 'HGETALL' command")
        items = self.store.hgetall(args[0])
        if not items:
            return ""
        return "\n".join(f"{field}\n{value}" for field, value in items)

    def handle_hkeys(self, args: List[str]) -> str:
        if len(args) != 1: raise CommandError("ERR wrong number of arguments for 'HKEYS' command")
        keys = self.store.hkeys(args[0])
        return self._format_numbered_list(keys, "(empty list)")

    # --- TTL Handlers ---
    def handle_expire(self, args: List[str]) -> str:
        if len(args) != 2: raise CommandError("ERR wrong number of arguments for 'EXPIRE' command")
        try:
            seconds = int(args[1])
        except ValueError:
            raise CommandError("ERR invalid expire time in 'EXPIRE' command")
        return self._format_integer(self.store.expire(args[0], seconds))

    def handle_ttl(self, args: List[str]) -> str:
        if len(args) != 1: raise CommandError("ERR wrong number of arguments for 'TTL' command")
        return self._format_integer(self.store.ttl(args[0]))

    def handle_persist(self, args: List[str]) -> str:
        if len(args) != 1: raise CommandError("ERR wrong number of arguments for 'PERSIST' command")
        return self._format_integer(self.store.persist(args[0]))

    # --- Set Handlers ---
    def handle_sadd(self, args: List[str]) -> str:
        if len(args) < 2: raise CommandError("ERR wrong number of arguments for 'SADD' command")
        return self._format_integer(self.store.sadd(args[0], *args[1:]))

    def handle_srem(self, args: List[str]) -> str:
        if len(args) < 2: raise CommandError("ERR wrong number of arguments for 'SREM' command")
        return self._format_integer(self.store.srem(args[0], *args[1:]))

    def handle_smembers(self, args: List[str]) -> str:
        if len(args) != 1: raise CommandError("ERR wrong number of arguments for 'SMEMBERS' command")
        members = self.store.smembers(args[0])
        return self._format_numbered_list(members, "(empty set)")

    def handle_sismember(self, args: List[str]) -> str:
        if len(args) != 2: raise CommandError("ERR wrong number of arguments for 'SISMEMBER' command")
        return self._format_integer(self.store.sismember(args[0], args[1]))

    # --- Counter Handlers ---
    def handle_incr(self, args: List[str]) -> str:
        if len(args) != 1: raise CommandError("ERR wrong number of arguments for 'INCR' command")
        return self._format_integer(self.store.incr(args[0]))

    def handle_decr(self, args: List[str]) -> str:
        if len(args) != 1: raise CommandError("ERR wrong number of arguments for 'DECR' command")
        return self._format_integer(self.store.decr(args[0]))

# --- Main Execution ---

def main():
    """
    Entry point for the mini-redis application.
    """
    data_path = os.environ.get("MINI_REDIS_DATA", "./mini_redis.json")
    try:
        store = RedisStore(data_path)
        store.load()
        cli = MiniRedisCLI(store)
        cli.run(sys.argv[1:])
    except (IOError, json.JSONDecodeError) as e:
        sys.stderr.write(f"Fatal I/O Error: {e}\n")
        sys.exit(2)

if __name__ == "__main__":
    main()
