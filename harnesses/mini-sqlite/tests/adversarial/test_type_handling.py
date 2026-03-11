"""Adversarial: integer/real edge cases and type storage."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import assert_success, parse_rows, run_sql


def test_integer_roundtrip(db):
    run_sql(db, "CREATE TABLE t (val INTEGER)")
    run_sql(db, "INSERT INTO t VALUES (9999999999)")
    r = run_sql(db, "SELECT val FROM t")
    _, rows = parse_rows(r)
    assert rows == [["9999999999"]]


def test_negative_integer(db):
    run_sql(db, "CREATE TABLE t (val INTEGER)")
    run_sql(db, "INSERT INTO t VALUES (-42)")
    r = run_sql(db, "SELECT val FROM t")
    _, rows = parse_rows(r)
    assert rows == [["-42"]]


def test_real_roundtrip(db):
    run_sql(db, "CREATE TABLE t (val REAL)")
    run_sql(db, "INSERT INTO t VALUES (3.14)")
    r = run_sql(db, "SELECT val FROM t")
    _, rows = parse_rows(r)
    assert abs(float(rows[0][0]) - 3.14) < 0.0001


def test_zero_value(db):
    run_sql(db, "CREATE TABLE t (val INTEGER)")
    run_sql(db, "INSERT INTO t VALUES (0)")
    r = run_sql(db, "SELECT val FROM t")
    _, rows = parse_rows(r)
    assert rows == [["0"]]


def test_where_compares_integers_correctly(db):
    run_sql(db, "CREATE TABLE t (val INTEGER)")
    run_sql(db, "INSERT INTO t VALUES (9)")
    run_sql(db, "INSERT INTO t VALUES (10)")
    run_sql(db, "INSERT INTO t VALUES (11)")
    r = run_sql(db, "SELECT val FROM t WHERE val > 9")
    _, rows = parse_rows(r)
    assert len(rows) == 2
    # Must be numeric comparison, not lexicographic
