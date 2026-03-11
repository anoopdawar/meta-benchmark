"""Tier 1: SET, GET, DEL, EXISTS, MSET, MGET."""

import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import assert_failure, assert_success, assert_stdout, run_redis


def test_set_and_get_basic(db):
    r = run_redis(["SET", "foo", "bar"], data_path=db)
    assert_success(r)
    assert_stdout(r, "OK")
    r2 = run_redis(["GET", "foo"], data_path=db)
    assert_success(r2)
    assert_stdout(r2, '"bar"')


def test_get_missing_key_returns_nil(db):
    r = run_redis(["GET", "nosuchkey"], data_path=db)
    assert_success(r)
    assert_stdout(r, "(nil)")


def test_set_overwrites_value(db):
    run_redis(["SET", "k", "first"], data_path=db)
    run_redis(["SET", "k", "second"], data_path=db)
    r = run_redis(["GET", "k"], data_path=db)
    assert_stdout(r, '"second"')


def test_del_existing_key(db):
    run_redis(["SET", "k", "v"], data_path=db)
    r = run_redis(["DEL", "k"], data_path=db)
    assert_success(r)
    assert_stdout(r, "(integer) 1")
    r2 = run_redis(["GET", "k"], data_path=db)
    assert_stdout(r2, "(nil)")


def test_del_missing_key_returns_zero(db):
    r = run_redis(["DEL", "nosuchkey"], data_path=db)
    assert_success(r)
    assert_stdout(r, "(integer) 0")


def test_del_multiple_keys(db):
    run_redis(["SET", "a", "1"], data_path=db)
    run_redis(["SET", "b", "2"], data_path=db)
    r = run_redis(["DEL", "a", "b", "c"], data_path=db)
    assert_success(r)
    assert_stdout(r, "(integer) 2")


def test_exists_present(db):
    run_redis(["SET", "k", "v"], data_path=db)
    r = run_redis(["EXISTS", "k"], data_path=db)
    assert_success(r)
    assert_stdout(r, "(integer) 1")


def test_exists_missing(db):
    r = run_redis(["EXISTS", "nosuchkey"], data_path=db)
    assert_success(r)
    assert_stdout(r, "(integer) 0")


def test_mset_and_mget(db):
    r = run_redis(["MSET", "a", "1", "b", "2", "c", "3"], data_path=db)
    assert_success(r)
    assert_stdout(r, "OK")
    r2 = run_redis(["MGET", "a", "b", "c"], data_path=db)
    assert_success(r2)
    lines = r2.stdout.strip().splitlines()
    assert lines == ['1) "1"', '2) "2"', '3) "3"']


def test_mget_with_missing_key(db):
    run_redis(["SET", "a", "alpha"], data_path=db)
    run_redis(["SET", "c", "gamma"], data_path=db)
    r = run_redis(["MGET", "a", "missing", "c"], data_path=db)
    assert_success(r)
    lines = r.stdout.strip().splitlines()
    assert lines == ['1) "alpha"', "2) (nil)", '3) "gamma"']


def test_set_wrong_arity_exits_1(db):
    r = run_redis(["SET", "onlykey"], data_path=db)
    assert_failure(r, code=1)
    assert r.stdout.strip() == ""
    assert "ERR" in r.stderr


def test_get_wrong_arity_exits_1(db):
    r = run_redis(["GET"], data_path=db)
    assert_failure(r, code=1)
