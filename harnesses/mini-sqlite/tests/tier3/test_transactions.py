"""Tier 3: BEGIN, COMMIT, ROLLBACK."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import assert_failure, assert_success, assert_stdout, parse_rows, run_sql


def test_begin_commit_persists(db):
    run_sql(db, "CREATE TABLE t (id INTEGER)")
    run_sql(db, "BEGIN")
    run_sql(db, "INSERT INTO t VALUES (1)")
    run_sql(db, "COMMIT")
    r = run_sql(db, "SELECT * FROM t")
    _, rows = parse_rows(r)
    assert rows == [["1"]]


def test_rollback_reverts_insert(db):
    run_sql(db, "CREATE TABLE t (id INTEGER)")
    run_sql(db, "BEGIN")
    run_sql(db, "INSERT INTO t VALUES (42)")
    run_sql(db, "ROLLBACK")
    r = run_sql(db, "SELECT * FROM t")
    _, rows = parse_rows(r)
    assert rows == []


def test_rollback_reverts_delete(db):
    run_sql(db, "CREATE TABLE t (id INTEGER)")
    run_sql(db, "INSERT INTO t VALUES (1)")
    run_sql(db, "BEGIN")
    run_sql(db, "DELETE FROM t")
    run_sql(db, "ROLLBACK")
    r = run_sql(db, "SELECT * FROM t")
    _, rows = parse_rows(r)
    assert rows == [["1"]]


def test_rollback_reverts_update(db):
    run_sql(db, "CREATE TABLE t (id INTEGER, name TEXT)")
    run_sql(db, "INSERT INTO t VALUES (1, 'Alice')")
    run_sql(db, "BEGIN")
    run_sql(db, "UPDATE t SET name = 'Changed'")
    run_sql(db, "ROLLBACK")
    r = run_sql(db, "SELECT name FROM t")
    _, rows = parse_rows(r)
    assert rows == [["Alice"]]


def test_begin_returns_ok(db):
    r = run_sql(db, "BEGIN")
    assert_success(r)
    assert_stdout(r, "OK")
    run_sql(db, "COMMIT")


def test_commit_without_begin_exits_1(db):
    r = run_sql(db, "COMMIT")
    assert_failure(r, code=1)
    assert "no active transaction" in r.stderr.lower()


def test_rollback_without_begin_exits_1(db):
    r = run_sql(db, "ROLLBACK")
    assert_failure(r, code=1)
    assert "no active transaction" in r.stderr.lower()


def test_begin_twice_exits_1(db):
    run_sql(db, "BEGIN")
    r = run_sql(db, "BEGIN")
    assert_failure(r, code=1)
    assert "transaction already active" in r.stderr.lower()
    run_sql(db, "ROLLBACK")


def test_rollback_reverts_create_table(db):
    """ROLLBACK must undo DDL (CREATE TABLE) per spec."""
    run_sql(db, "BEGIN")
    run_sql(db, "CREATE TABLE temp_table (id INTEGER)")
    run_sql(db, "ROLLBACK")
    # After rollback, temp_table must not exist
    r = run_sql(db, "SELECT * FROM temp_table")
    assert r.returncode != 0, "Table should not exist after ROLLBACK"
    assert "no such table" in r.stderr.lower()
