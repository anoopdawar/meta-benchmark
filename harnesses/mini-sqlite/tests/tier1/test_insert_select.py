"""Tier 1: INSERT and SELECT."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import assert_failure, assert_success, assert_stdout, parse_rows, run_sql


def test_insert_one_row_returns_1_row_affected(db):
    run_sql(db, "CREATE TABLE t (id INTEGER, name TEXT)")
    r = run_sql(db, "INSERT INTO t VALUES (1, 'Alice')")
    assert_success(r)
    assert_stdout(r, "1 row affected")


def test_select_star_returns_inserted_row(db):
    run_sql(db, "CREATE TABLE t (id INTEGER, name TEXT)")
    run_sql(db, "INSERT INTO t VALUES (1, 'Alice')")
    r = run_sql(db, "SELECT * FROM t")
    assert_success(r)
    header, rows = parse_rows(r)
    assert header == ["id", "name"]
    assert rows == [["1", "Alice"]]


def test_select_specific_columns(db):
    run_sql(db, "CREATE TABLE t (id INTEGER, name TEXT, age INTEGER)")
    run_sql(db, "INSERT INTO t VALUES (1, 'Alice', 30)")
    r = run_sql(db, "SELECT name, age FROM t")
    header, rows = parse_rows(r)
    assert header == ["name", "age"]
    assert rows == [["Alice", "30"]]


def test_select_multiple_rows_insertion_order(db):
    run_sql(db, "CREATE TABLE t (id INTEGER, name TEXT)")
    run_sql(db, "INSERT INTO t VALUES (1, 'Alice')")
    run_sql(db, "INSERT INTO t VALUES (2, 'Bob')")
    run_sql(db, "INSERT INTO t VALUES (3, 'Carol')")
    r = run_sql(db, "SELECT * FROM t")
    header, rows = parse_rows(r)
    assert rows == [["1", "Alice"], ["2", "Bob"], ["3", "Carol"]]


def test_insert_named_columns(db):
    run_sql(db, "CREATE TABLE t (id INTEGER, name TEXT, age INTEGER)")
    run_sql(db, "INSERT INTO t (name, id) VALUES ('Alice', 1)")
    r = run_sql(db, "SELECT * FROM t")
    header, rows = parse_rows(r)
    # Schema order: id, name, age; age defaults to NULL (empty)
    assert header == ["id", "name", "age"]
    assert rows == [["1", "Alice", ""]]


def test_insert_null_value(db):
    run_sql(db, "CREATE TABLE t (a INTEGER, b TEXT)")
    run_sql(db, "INSERT INTO t VALUES (NULL, 'hello')")
    r = run_sql(db, "SELECT * FROM t")
    header, rows = parse_rows(r)
    assert rows == [["", "hello"]]


def test_select_empty_table_shows_header_only(db):
    run_sql(db, "CREATE TABLE t (id INTEGER, name TEXT)")
    r = run_sql(db, "SELECT * FROM t")
    lines = r.stdout.strip().splitlines()
    assert lines == ["id|name"]


def test_select_star_column_order_matches_schema(db):
    """Columns always in schema order, regardless of INSERT column order."""
    run_sql(db, "CREATE TABLE t (a INTEGER, b TEXT, c REAL)")
    run_sql(db, "INSERT INTO t (c, a, b) VALUES (3.14, 1, 'hello')")
    r = run_sql(db, "SELECT * FROM t")
    header, rows = parse_rows(r)
    assert header == ["a", "b", "c"]
    assert rows[0][0] == "1"
    assert rows[0][1] == "hello"
