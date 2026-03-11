"""Tier 2: UPDATE."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import assert_success, parse_rows, run_sql


def test_update_all_rows(db):
    run_sql(db, "CREATE TABLE t (id INTEGER, val TEXT)")
    run_sql(db, "INSERT INTO t VALUES (1, 'old')")
    run_sql(db, "INSERT INTO t VALUES (2, 'old')")
    r = run_sql(db, "UPDATE t SET val = 'new'")
    assert_success(r)
    assert r.stdout.strip() == "2 rows affected"


def test_update_with_where(db):
    run_sql(db, "CREATE TABLE t (id INTEGER, name TEXT)")
    run_sql(db, "INSERT INTO t VALUES (1, 'Alice')")
    run_sql(db, "INSERT INTO t VALUES (2, 'Bob')")
    run_sql(db, "UPDATE t SET name = 'Alicia' WHERE id = 1")
    r = run_sql(db, "SELECT name FROM t WHERE id = 1")
    _, rows = parse_rows(r)
    assert rows == [["Alicia"]]


def test_update_no_match_returns_0(db):
    run_sql(db, "CREATE TABLE t (id INTEGER, name TEXT)")
    run_sql(db, "INSERT INTO t VALUES (1, 'Alice')")
    r = run_sql(db, "UPDATE t SET name = 'X' WHERE id = 999")
    assert r.stdout.strip() == "0 rows affected"


def test_update_multiple_columns(db):
    run_sql(db, "CREATE TABLE t (a INTEGER, b TEXT, c REAL)")
    run_sql(db, "INSERT INTO t VALUES (1, 'old', 1.0)")
    run_sql(db, "UPDATE t SET b = 'new', c = 2.0 WHERE a = 1")
    r = run_sql(db, "SELECT * FROM t")
    _, rows = parse_rows(r)
    assert rows[0] == ["1", "new", "2.0"]


def test_update_rows_matched_not_changed(db):
    """UPDATE counts rows matched by WHERE, not rows where value changed."""
    run_sql(db, "CREATE TABLE t (id INTEGER, val TEXT)")
    run_sql(db, "INSERT INTO t VALUES (1, 'same')")
    run_sql(db, "INSERT INTO t VALUES (2, 'same')")
    r = run_sql(db, "UPDATE t SET val = 'same'")
    assert r.stdout.strip() == "2 rows affected"
