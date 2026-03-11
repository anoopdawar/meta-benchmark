"""Adversarial: exact error message format."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import assert_failure, run_sql


def test_unknown_table_error_message(db):
    r = run_sql(db, "SELECT * FROM nosuchable")
    assert_failure(r)
    assert "no such table" in r.stderr.lower()
    assert r.stdout.strip() == ""


def test_drop_unknown_table_error_message(db):
    r = run_sql(db, "DROP TABLE nosuchable")
    assert_failure(r)
    assert "no such table" in r.stderr.lower()


def test_select_unknown_column(db):
    run_sql(db, "CREATE TABLE t (id INTEGER)")
    r = run_sql(db, "SELECT nosuchcol FROM t")
    assert_failure(r)
    assert "no such column" in r.stderr.lower()


def test_unsupported_feature_primary_key(db):
    r = run_sql(db, "CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
    assert_failure(r)
    assert "unsupported" in r.stderr.lower()


def test_stderr_empty_on_success(db):
    run_sql(db, "CREATE TABLE t (id INTEGER)")
    r = run_sql(db, "INSERT INTO t VALUES (1)")
    assert r.stderr.strip() == ""


def test_stdout_empty_on_error(db):
    r = run_sql(db, "SELECT * FROM nosuchable")
    assert r.stdout.strip() == ""
