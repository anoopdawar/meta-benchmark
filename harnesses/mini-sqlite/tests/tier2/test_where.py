"""Tier 2: WHERE clause with various operators."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import assert_success, parse_rows, run_sql


def _setup(db):
    run_sql(db, "CREATE TABLE t (id INTEGER, name TEXT, score REAL)")
    run_sql(db, "INSERT INTO t VALUES (1, 'Alice', 90.5)")
    run_sql(db, "INSERT INTO t VALUES (2, 'Bob', 75.0)")
    run_sql(db, "INSERT INTO t VALUES (3, 'Carol', 90.5)")
    run_sql(db, "INSERT INTO t VALUES (4, 'Dave', NULL)")


def test_where_equality(db):
    _setup(db)
    r = run_sql(db, "SELECT name FROM t WHERE id = 2")
    _, rows = parse_rows(r)
    assert rows == [["Bob"]]


def test_where_inequality(db):
    _setup(db)
    r = run_sql(db, "SELECT id FROM t WHERE id != 2")
    _, rows = parse_rows(r)
    ids = [row[0] for row in rows]
    assert "2" not in ids
    assert len(ids) == 3


def test_where_less_than(db):
    _setup(db)
    r = run_sql(db, "SELECT name FROM t WHERE id < 3")
    _, rows = parse_rows(r)
    assert len(rows) == 2


def test_where_greater_than(db):
    _setup(db)
    r = run_sql(db, "SELECT name FROM t WHERE score > 80.0")
    _, rows = parse_rows(r)
    names = [r[0] for r in rows]
    assert "Alice" in names
    assert "Carol" in names
    assert "Bob" not in names


def test_where_and(db):
    _setup(db)
    r = run_sql(db, "SELECT name FROM t WHERE id > 1 AND score > 80.0")
    _, rows = parse_rows(r)
    assert rows == [["Carol"]]


def test_where_or(db):
    _setup(db)
    r = run_sql(db, "SELECT name FROM t WHERE id = 1 OR id = 3")
    _, rows = parse_rows(r)
    names = {r[0] for r in rows}
    assert names == {"Alice", "Carol"}


def test_where_is_null(db):
    _setup(db)
    r = run_sql(db, "SELECT name FROM t WHERE score IS NULL")
    _, rows = parse_rows(r)
    assert rows == [["Dave"]]


def test_where_is_not_null(db):
    _setup(db)
    r = run_sql(db, "SELECT name FROM t WHERE score IS NOT NULL")
    _, rows = parse_rows(r)
    assert len(rows) == 3


def test_where_not(db):
    _setup(db)
    r = run_sql(db, "SELECT name FROM t WHERE NOT id = 1")
    _, rows = parse_rows(r)
    names = [r[0] for r in rows]
    assert "Alice" not in names


def test_where_no_matches_returns_header_only(db):
    _setup(db)
    r = run_sql(db, "SELECT * FROM t WHERE id = 999")
    lines = r.stdout.strip().splitlines()
    assert len(lines) == 1  # header only


def test_delete_where(db):
    _setup(db)
    r = run_sql(db, "DELETE FROM t WHERE id = 2")
    assert_success(r)
    assert r.stdout.strip() == "1 rows affected"
    r2 = run_sql(db, "SELECT name FROM t WHERE id = 2")
    _, rows = parse_rows(r2)
    assert rows == []
