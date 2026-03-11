"""Adversarial: edge cases in SELECT output format and general behavior."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import assert_success, parse_rows, run_sql


def test_large_text_value(db):
    run_sql(db, "CREATE TABLE t (id INTEGER, val TEXT)")
    big = "X" * 100_000
    run_sql(db, f"INSERT INTO t VALUES (1, '{big}')")
    r = run_sql(db, "SELECT val FROM t")
    assert_success(r)
    assert big in r.stdout


def test_many_columns(db):
    cols = ", ".join(f"c{i} INTEGER" for i in range(20))
    run_sql(db, f"CREATE TABLE t ({cols})")
    vals = ", ".join(str(i) for i in range(20))
    run_sql(db, f"INSERT INTO t VALUES ({vals})")
    r = run_sql(db, "SELECT * FROM t")
    header, rows = parse_rows(r)
    assert len(header) == 20
    assert len(rows[0]) == 20


def test_many_rows(db):
    run_sql(db, "CREATE TABLE t (id INTEGER)")
    for i in range(100):
        run_sql(db, f"INSERT INTO t VALUES ({i})")
    r = run_sql(db, "SELECT id FROM t")
    _, rows = parse_rows(r)
    assert len(rows) == 100


def test_empty_table_after_delete_all(db):
    run_sql(db, "CREATE TABLE t (id INTEGER)")
    run_sql(db, "INSERT INTO t VALUES (1)")
    run_sql(db, "DELETE FROM t")
    r = run_sql(db, "SELECT * FROM t")
    lines = r.stdout.strip().splitlines()
    assert lines == ["id"]


def test_where_on_real_column(db):
    run_sql(db, "CREATE TABLE t (id INTEGER, score REAL)")
    run_sql(db, "INSERT INTO t VALUES (1, 9.5)")
    run_sql(db, "INSERT INTO t VALUES (2, 7.0)")
    r = run_sql(db, "SELECT id FROM t WHERE score > 8.0")
    _, rows = parse_rows(r)
    assert rows == [["1"]]
