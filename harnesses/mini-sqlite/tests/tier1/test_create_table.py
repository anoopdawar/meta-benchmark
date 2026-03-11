"""Tier 1: CREATE TABLE and DROP TABLE."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import assert_failure, assert_success, assert_stdout, run_sql


def test_create_table_returns_ok(db):
    r = run_sql(db, "CREATE TABLE users (id INTEGER, name TEXT)")
    assert_success(r)
    assert_stdout(r, "OK")


def test_create_table_with_three_columns(db):
    r = run_sql(db, "CREATE TABLE products (id INTEGER, name TEXT, price REAL)")
    assert_success(r)
    assert_stdout(r, "OK")


def test_drop_table_returns_ok(db):
    run_sql(db, "CREATE TABLE t (x INTEGER)")
    r = run_sql(db, "DROP TABLE t")
    assert_success(r)
    assert_stdout(r, "OK")


def test_drop_table_missing_exits_1(db):
    r = run_sql(db, "DROP TABLE nosuchable")
    assert_failure(r, code=1)
    assert r.stdout.strip() == ""
    assert "Error" in r.stderr


def test_select_from_empty_table_shows_header(db):
    run_sql(db, "CREATE TABLE t (id INTEGER, name TEXT)")
    r = run_sql(db, "SELECT * FROM t")
    assert_success(r)
    assert r.stdout.strip() == "id|name"


def test_select_from_unknown_table_exits_1(db):
    r = run_sql(db, "SELECT * FROM nosuchable")
    assert_failure(r, code=1)
    assert "no such table" in r.stderr


def test_create_table_with_null_type(db):
    r = run_sql(db, "CREATE TABLE t (a INTEGER, b TEXT, c REAL)")
    assert_success(r)
