"""Tier 1: DELETE (all rows)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import assert_success, assert_stdout, parse_rows, run_sql


def test_delete_all_rows(db):
    run_sql(db, "CREATE TABLE t (id INTEGER)")
    run_sql(db, "INSERT INTO t VALUES (1)")
    run_sql(db, "INSERT INTO t VALUES (2)")
    r = run_sql(db, "DELETE FROM t")
    assert_success(r)
    assert_stdout(r, "2 rows affected")


def test_delete_all_from_empty_table(db):
    run_sql(db, "CREATE TABLE t (id INTEGER)")
    r = run_sql(db, "DELETE FROM t")
    assert_success(r)
    assert_stdout(r, "0 rows affected")


def test_delete_all_leaves_table_empty(db):
    run_sql(db, "CREATE TABLE t (id INTEGER, name TEXT)")
    run_sql(db, "INSERT INTO t VALUES (1, 'Alice')")
    run_sql(db, "DELETE FROM t")
    r = run_sql(db, "SELECT * FROM t")
    lines = r.stdout.strip().splitlines()
    assert lines == ["id|name"]
