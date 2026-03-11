"""Tier 2: LPUSH, RPUSH, LPOP, RPOP, LRANGE."""

import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import assert_failure, assert_success, assert_stdout, run_redis


def test_rpush_creates_list_and_returns_length(db):
    r = run_redis(["RPUSH", "mylist", "a"], data_path=db)
    assert_success(r)
    assert_stdout(r, "(integer) 1")


def test_rpush_multiple_values_returns_new_length(db):
    r = run_redis(["RPUSH", "mylist", "a", "b", "c"], data_path=db)
    assert_stdout(r, "(integer) 3")


def test_lpush_prepends(db):
    run_redis(["RPUSH", "mylist", "b"], data_path=db)
    run_redis(["LPUSH", "mylist", "a"], data_path=db)
    r = run_redis(["LRANGE", "mylist", "0", "-1"], data_path=db)
    lines = r.stdout.strip().splitlines()
    assert lines == ['1) "a"', '2) "b"']


def test_lrange_full_list(db):
    run_redis(["RPUSH", "mylist", "x", "y", "z"], data_path=db)
    r = run_redis(["LRANGE", "mylist", "0", "-1"], data_path=db)
    lines = r.stdout.strip().splitlines()
    assert lines == ['1) "x"', '2) "y"', '3) "z"']


def test_lrange_partial(db):
    run_redis(["RPUSH", "mylist", "a", "b", "c", "d"], data_path=db)
    r = run_redis(["LRANGE", "mylist", "1", "2"], data_path=db)
    lines = r.stdout.strip().splitlines()
    assert lines == ['1) "b"', '2) "c"']


def test_lrange_negative_indices(db):
    run_redis(["RPUSH", "mylist", "a", "b", "c"], data_path=db)
    r = run_redis(["LRANGE", "mylist", "-2", "-1"], data_path=db)
    lines = r.stdout.strip().splitlines()
    assert lines == ['1) "b"', '2) "c"']


def test_lrange_empty_list(db):
    run_redis(["RPUSH", "mylist", "x"], data_path=db)
    run_redis(["LPOP", "mylist"], data_path=db)
    r = run_redis(["LRANGE", "mylist", "0", "-1"], data_path=db)
    assert_stdout(r, "(empty list)")


def test_lrange_missing_key(db):
    r = run_redis(["LRANGE", "nosuchkey", "0", "-1"], data_path=db)
    assert_success(r)
    assert_stdout(r, "(empty list)")


def test_lpop_returns_and_removes(db):
    run_redis(["RPUSH", "mylist", "first", "second"], data_path=db)
    r = run_redis(["LPOP", "mylist"], data_path=db)
    assert_success(r)
    assert_stdout(r, '"first"')
    r2 = run_redis(["LRANGE", "mylist", "0", "-1"], data_path=db)
    lines = r2.stdout.strip().splitlines()
    assert lines == ['1) "second"']


def test_rpop_returns_and_removes(db):
    run_redis(["RPUSH", "mylist", "a", "b"], data_path=db)
    r = run_redis(["RPOP", "mylist"], data_path=db)
    assert_stdout(r, '"b"')


def test_lpop_on_empty_key_returns_nil(db):
    r = run_redis(["LPOP", "nosuchkey"], data_path=db)
    assert_success(r)
    assert_stdout(r, "(nil)")


def test_lpush_multiple_values_order(db):
    # LPUSH a b c → list is [c, b, a] (each pushed to left)
    run_redis(["LPUSH", "mylist", "a", "b", "c"], data_path=db)
    r = run_redis(["LRANGE", "mylist", "0", "-1"], data_path=db)
    lines = r.stdout.strip().splitlines()
    assert lines == ['1) "c"', '2) "b"', '3) "a"']
