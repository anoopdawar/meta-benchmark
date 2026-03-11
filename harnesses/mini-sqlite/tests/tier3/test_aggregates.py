"""Tier 3: GROUP BY, HAVING, and aggregate functions."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import assert_success, parse_rows, run_sql


def _setup(db):
    run_sql(db, "CREATE TABLE sales (id INTEGER, dept TEXT, amount REAL)")
    run_sql(db, "INSERT INTO sales VALUES (1, 'Engineering', 100.0)")
    run_sql(db, "INSERT INTO sales VALUES (2, 'Engineering', 200.0)")
    run_sql(db, "INSERT INTO sales VALUES (3, 'Marketing', 50.0)")
    run_sql(db, "INSERT INTO sales VALUES (4, 'Marketing', NULL)")


def test_count_star(db):
    _setup(db)
    r = run_sql(db, "SELECT COUNT(*) FROM sales")
    _, rows = parse_rows(r)
    assert rows == [["4"]]


def test_count_column_ignores_null(db):
    _setup(db)
    r = run_sql(db, "SELECT COUNT(amount) FROM sales")
    _, rows = parse_rows(r)
    assert rows == [["3"]]


def test_sum(db):
    _setup(db)
    r = run_sql(db, "SELECT SUM(amount) FROM sales")
    _, rows = parse_rows(r)
    assert float(rows[0][0]) == 350.0


def test_avg(db):
    _setup(db)
    r = run_sql(db, "SELECT AVG(amount) FROM sales WHERE dept = 'Engineering'")
    _, rows = parse_rows(r)
    assert abs(float(rows[0][0]) - 150.0) < 0.001


def test_min_max(db):
    _setup(db)
    r_min = run_sql(db, "SELECT MIN(amount) FROM sales")
    r_max = run_sql(db, "SELECT MAX(amount) FROM sales")
    _, min_rows = parse_rows(r_min)
    _, max_rows = parse_rows(r_max)
    assert float(min_rows[0][0]) == 50.0
    assert float(max_rows[0][0]) == 200.0


def test_group_by(db):
    _setup(db)
    r = run_sql(db, "SELECT dept, COUNT(*) FROM sales GROUP BY dept")
    assert_success(r)
    _, rows = parse_rows(r)
    dept_counts = {r[0]: int(r[1]) for r in rows}
    assert dept_counts["Engineering"] == 2
    assert dept_counts["Marketing"] == 2


def test_having_filters_groups(db):
    _setup(db)
    r = run_sql(db, "SELECT dept, SUM(amount) FROM sales GROUP BY dept HAVING SUM(amount) > 100")
    assert_success(r)
    _, rows = parse_rows(r)
    depts = [r[0] for r in rows]
    assert "Engineering" in depts
    assert "Marketing" not in depts
