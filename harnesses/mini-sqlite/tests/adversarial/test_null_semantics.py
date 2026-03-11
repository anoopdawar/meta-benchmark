"""Adversarial: NULL edge cases."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import assert_success, parse_rows, run_sql


def test_null_not_equal_null(db):
    """WHERE col = NULL should match nothing (NULL != NULL)."""
    run_sql(db, "CREATE TABLE t (val INTEGER)")
    run_sql(db, "INSERT INTO t VALUES (NULL)")
    r = run_sql(db, "SELECT * FROM t WHERE val = NULL")
    _, rows = parse_rows(r)
    assert rows == []


def test_null_is_null_matches(db):
    run_sql(db, "CREATE TABLE t (val INTEGER)")
    run_sql(db, "INSERT INTO t VALUES (NULL)")
    run_sql(db, "INSERT INTO t VALUES (1)")
    r = run_sql(db, "SELECT val FROM t WHERE val IS NULL")
    _, rows = parse_rows(r)
    assert rows == [[""]]


def test_null_in_order_by_last(db):
    run_sql(db, "CREATE TABLE t (id INTEGER, val INTEGER)")
    run_sql(db, "INSERT INTO t VALUES (1, NULL)")
    run_sql(db, "INSERT INTO t VALUES (2, 5)")
    run_sql(db, "INSERT INTO t VALUES (3, 1)")
    r = run_sql(db, "SELECT id FROM t ORDER BY val ASC")
    _, rows = parse_rows(r)
    assert rows[-1][0] == "1"  # NULL row last


def test_count_star_counts_null_rows(db):
    run_sql(db, "CREATE TABLE t (val INTEGER)")
    run_sql(db, "INSERT INTO t VALUES (NULL)")
    run_sql(db, "INSERT INTO t VALUES (NULL)")
    r = run_sql(db, "SELECT COUNT(*) FROM t")
    _, rows = parse_rows(r)
    assert rows == [["2"]]


def test_count_col_skips_nulls(db):
    run_sql(db, "CREATE TABLE t (val INTEGER)")
    run_sql(db, "INSERT INTO t VALUES (NULL)")
    run_sql(db, "INSERT INTO t VALUES (5)")
    r = run_sql(db, "SELECT COUNT(val) FROM t")
    _, rows = parse_rows(r)
    assert rows == [["1"]]


def test_sum_ignores_nulls(db):
    run_sql(db, "CREATE TABLE t (val REAL)")
    run_sql(db, "INSERT INTO t VALUES (10.0)")
    run_sql(db, "INSERT INTO t VALUES (NULL)")
    run_sql(db, "INSERT INTO t VALUES (20.0)")
    r = run_sql(db, "SELECT SUM(val) FROM t")
    _, rows = parse_rows(r)
    assert float(rows[0][0]) == 30.0


def test_null_output_is_empty_field(db):
    run_sql(db, "CREATE TABLE t (a INTEGER, b INTEGER)")
    run_sql(db, "INSERT INTO t VALUES (1, NULL)")
    r = run_sql(db, "SELECT * FROM t")
    lines = r.stdout.strip().splitlines()
    assert lines[1] == "1|"
