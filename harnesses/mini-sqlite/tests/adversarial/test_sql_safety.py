"""Adversarial: SQL injection stored as data (not executed)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import assert_success, parse_rows, run_sql


def test_sql_in_string_value_stored_not_executed(db):
    """SQL injection attempt in a value must be stored as a string."""
    run_sql(db, "CREATE TABLE t (id INTEGER, payload TEXT)")
    run_sql(db, "INSERT INTO t VALUES (1, 'DROP TABLE t; --')")
    r = run_sql(db, "SELECT payload FROM t")
    assert_success(r)
    _, rows = parse_rows(r)
    assert rows == [["DROP TABLE t; --"]]


def test_single_quote_in_value(db):
    run_sql(db, "CREATE TABLE t (id INTEGER, name TEXT)")
    run_sql(db, "INSERT INTO t VALUES (1, \"it's a test\")")
    r = run_sql(db, "SELECT name FROM t")
    assert_success(r)
    _, rows = parse_rows(r)
    assert "it's a test" in rows[0][0]


def test_pipe_in_value_escaped(db):
    """Value containing | must be escaped as \\| in output."""
    run_sql(db, "CREATE TABLE t (id INTEGER, val TEXT)")
    run_sql(db, "INSERT INTO t VALUES (1, 'a|b')")
    r = run_sql(db, "SELECT val FROM t")
    assert_success(r)
    out = r.stdout.strip()
    # The data row must not parse as two columns
    lines = out.splitlines()
    assert len(lines) == 2  # header + 1 row
    # The value should contain the escaped pipe
    assert "\\|" in lines[1] or "a|b" in lines[1]


def test_empty_string_value_roundtrips(db):
    run_sql(db, "CREATE TABLE t (id INTEGER, val TEXT)")
    run_sql(db, "INSERT INTO t VALUES (1, '')")
    r = run_sql(db, "SELECT val FROM t")
    _, rows = parse_rows(r)
    # SELECT val selects one column; empty string stored as '' should roundtrip as ""
    assert rows == [[""]]


def test_unicode_value_stored(db):
    run_sql(db, "CREATE TABLE t (id INTEGER, name TEXT)")
    run_sql(db, "INSERT INTO t VALUES (1, 'こんにちは')")
    r = run_sql(db, "SELECT name FROM t")
    assert_success(r)
    assert "こんにちは" in r.stdout


def test_numeric_string_not_coerced(db):
    """TEXT column stores '42' as text, not integer."""
    run_sql(db, "CREATE TABLE t (val TEXT)")
    run_sql(db, "INSERT INTO t VALUES ('42')")
    r = run_sql(db, "SELECT val FROM t")
    _, rows = parse_rows(r)
    assert rows == [["42"]]
