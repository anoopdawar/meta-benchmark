"""Tier 2: ORDER BY, LIMIT, OFFSET."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import assert_success, parse_rows, run_sql


def _setup(db):
    run_sql(db, "CREATE TABLE t (id INTEGER, score INTEGER, name TEXT)")
    run_sql(db, "INSERT INTO t VALUES (1, 30, 'Charlie')")
    run_sql(db, "INSERT INTO t VALUES (2, 10, 'Alice')")
    run_sql(db, "INSERT INTO t VALUES (3, 20, 'Bob')")


def test_order_by_asc(db):
    _setup(db)
    r = run_sql(db, "SELECT name FROM t ORDER BY score ASC")
    _, rows = parse_rows(r)
    assert [r[0] for r in rows] == ["Alice", "Bob", "Charlie"]


def test_order_by_desc(db):
    _setup(db)
    r = run_sql(db, "SELECT name FROM t ORDER BY score DESC")
    _, rows = parse_rows(r)
    assert [r[0] for r in rows] == ["Charlie", "Bob", "Alice"]


def test_order_by_stable_on_ties(db):
    run_sql(db, "CREATE TABLE t (id INTEGER, score INTEGER)")
    run_sql(db, "INSERT INTO t VALUES (1, 5)")
    run_sql(db, "INSERT INTO t VALUES (2, 5)")
    run_sql(db, "INSERT INTO t VALUES (3, 5)")
    r = run_sql(db, "SELECT id FROM t ORDER BY score ASC")
    _, rows = parse_rows(r)
    # Stable sort: original insertion order preserved for ties
    assert [r[0] for r in rows] == ["1", "2", "3"]


def test_order_by_null_sorts_last_asc(db):
    run_sql(db, "CREATE TABLE t (id INTEGER, val INTEGER)")
    run_sql(db, "INSERT INTO t VALUES (1, NULL)")
    run_sql(db, "INSERT INTO t VALUES (2, 10)")
    run_sql(db, "INSERT INTO t VALUES (3, 5)")
    r = run_sql(db, "SELECT id FROM t ORDER BY val ASC")
    _, rows = parse_rows(r)
    ids = [r[0] for r in rows]
    assert ids[-1] == "1"  # NULL sorts last


def test_order_by_null_sorts_last_desc(db):
    """NULLs sort last in DESC too — intentional non-standard behavior."""
    run_sql(db, "CREATE TABLE t (id INTEGER, val INTEGER)")
    run_sql(db, "INSERT INTO t VALUES (1, NULL)")
    run_sql(db, "INSERT INTO t VALUES (2, 10)")
    run_sql(db, "INSERT INTO t VALUES (3, 5)")
    r = run_sql(db, "SELECT id FROM t ORDER BY val DESC")
    _, rows = parse_rows(r)
    ids = [r[0] for r in rows]
    # DESC: 10, 5, NULL — NULL last even in descending order
    assert ids[0] == "2"   # val=10 first
    assert ids[-1] == "1"  # NULL last


def test_limit(db):
    _setup(db)
    r = run_sql(db, "SELECT id FROM t ORDER BY id ASC LIMIT 2")
    _, rows = parse_rows(r)
    assert len(rows) == 2
    assert rows[0][0] == "1"


def test_limit_offset(db):
    _setup(db)
    r = run_sql(db, "SELECT id FROM t ORDER BY id ASC LIMIT 2 OFFSET 1")
    _, rows = parse_rows(r)
    assert len(rows) == 2
    assert rows[0][0] == "2"
