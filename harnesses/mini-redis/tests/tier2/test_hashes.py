"""Tier 2: HSET, HGET, HDEL, HGETALL, HKEYS."""

import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import assert_failure, assert_success, assert_stdout, run_redis


def test_hset_and_hget(db):
    r = run_redis(["HSET", "user", "name", "Alice"], data_path=db)
    assert_success(r)
    assert_stdout(r, "(integer) 1")
    r2 = run_redis(["HGET", "user", "name"], data_path=db)
    assert_stdout(r2, '"Alice"')


def test_hset_multiple_fields(db):
    r = run_redis(["HSET", "user", "name", "Alice", "age", "30"], data_path=db)
    assert_stdout(r, "(integer) 2")


def test_hset_update_existing_returns_zero(db):
    run_redis(["HSET", "h", "f", "v1"], data_path=db)
    r = run_redis(["HSET", "h", "f", "v2"], data_path=db)
    assert_stdout(r, "(integer) 0")
    r2 = run_redis(["HGET", "h", "f"], data_path=db)
    assert_stdout(r2, '"v2"')


def test_hget_missing_field(db):
    run_redis(["HSET", "h", "f", "v"], data_path=db)
    r = run_redis(["HGET", "h", "nosuchfield"], data_path=db)
    assert_stdout(r, "(nil)")


def test_hget_missing_key(db):
    r = run_redis(["HGET", "nosuchkey", "f"], data_path=db)
    assert_stdout(r, "(nil)")


def test_hdel_field(db):
    run_redis(["HSET", "h", "f1", "v1", "f2", "v2"], data_path=db)
    r = run_redis(["HDEL", "h", "f1"], data_path=db)
    assert_stdout(r, "(integer) 1")
    r2 = run_redis(["HGET", "h", "f1"], data_path=db)
    assert_stdout(r2, "(nil)")


def test_hdel_missing_field_returns_zero(db):
    run_redis(["HSET", "h", "f", "v"], data_path=db)
    r = run_redis(["HDEL", "h", "nosuchfield"], data_path=db)
    assert_stdout(r, "(integer) 0")


def test_hgetall_alphabetical_order(db):
    run_redis(["HSET", "h", "zebra", "z", "apple", "a", "mango", "m"], data_path=db)
    r = run_redis(["HGETALL", "h"], data_path=db)
    assert_success(r)
    lines = r.stdout.strip().splitlines()
    assert lines == ["apple", "a", "mango", "m", "zebra", "z"]


def test_hgetall_empty_key(db):
    r = run_redis(["HGETALL", "nosuchkey"], data_path=db)
    assert_success(r)
    assert_stdout(r, "(empty list)")


def test_hkeys_alphabetical(db):
    run_redis(["HSET", "h", "c", "3", "a", "1", "b", "2"], data_path=db)
    r = run_redis(["HKEYS", "h"], data_path=db)
    lines = r.stdout.strip().splitlines()
    assert lines == ['1) "a"', '2) "b"', '3) "c"']


def test_hkeys_empty(db):
    r = run_redis(["HKEYS", "nosuchkey"], data_path=db)
    assert_stdout(r, "(empty list)")
