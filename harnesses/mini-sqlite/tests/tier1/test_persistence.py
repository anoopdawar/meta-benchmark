"""Tier 1: data persists across process restarts."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import assert_success, parse_rows, run_sql


def test_table_persists_after_restart(db):
    run_sql(db, "CREATE TABLE users (id INTEGER, name TEXT)")
    run_sql(db, "INSERT INTO users VALUES (1, 'Alice')")
    # New process invocation
    r = run_sql(db, "SELECT * FROM users")
    assert_success(r)
    header, rows = parse_rows(r)
    assert rows == [["1", "Alice"]]


def test_multiple_tables_persist(db):
    run_sql(db, "CREATE TABLE a (x INTEGER)")
    run_sql(db, "CREATE TABLE b (y TEXT)")
    run_sql(db, "INSERT INTO a VALUES (42)")
    run_sql(db, "INSERT INTO b VALUES ('hello')")
    r_a = run_sql(db, "SELECT * FROM a")
    r_b = run_sql(db, "SELECT * FROM b")
    _, rows_a = parse_rows(r_a)
    _, rows_b = parse_rows(r_b)
    assert rows_a == [["42"]]
    assert rows_b == [["hello"]]


def test_new_db_file_created_on_first_create(tmp_path):
    db = tmp_path / "brand_new.db"
    assert not db.exists()
    r = run_sql(db, "CREATE TABLE t (x INTEGER)")
    assert_success(r)
    assert db.exists()
