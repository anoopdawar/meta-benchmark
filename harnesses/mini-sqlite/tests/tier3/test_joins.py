"""Tier 3: INNER JOIN and LEFT JOIN."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import assert_success, parse_rows, run_sql


def _setup(db):
    run_sql(db, "CREATE TABLE users (id INTEGER, name TEXT)")
    run_sql(db, "CREATE TABLE orders (id INTEGER, user_id INTEGER, item TEXT)")
    run_sql(db, "INSERT INTO users VALUES (1, 'Alice')")
    run_sql(db, "INSERT INTO users VALUES (2, 'Bob')")
    run_sql(db, "INSERT INTO users VALUES (3, 'Carol')")
    run_sql(db, "INSERT INTO orders VALUES (1, 1, 'Book')")
    run_sql(db, "INSERT INTO orders VALUES (2, 1, 'Pen')")
    run_sql(db, "INSERT INTO orders VALUES (3, 2, 'Notebook')")


def test_inner_join_basic(db):
    _setup(db)
    r = run_sql(db, "SELECT users.name, orders.item FROM users INNER JOIN orders ON users.id = orders.user_id")
    assert_success(r)
    _, rows = parse_rows(r)
    names = [r[0] for r in rows]
    assert "Alice" in names
    assert "Bob" in names
    assert "Carol" not in names


def test_inner_join_excludes_no_match(db):
    _setup(db)
    r = run_sql(db, "SELECT users.name FROM users INNER JOIN orders ON users.id = orders.user_id")
    _, rows = parse_rows(r)
    names = [r[0] for r in rows]
    assert "Carol" not in names


def test_left_join_includes_non_matching(db):
    _setup(db)
    r = run_sql(db, "SELECT users.name, orders.item FROM users LEFT JOIN orders ON users.id = orders.user_id")
    assert_success(r)
    _, rows = parse_rows(r)
    names = [r[0] for r in rows]
    assert "Carol" in names
    # Carol's item should be NULL (empty)
    carol_row = [r for r in rows if r[0] == "Carol"]
    assert len(carol_row) == 1
    assert carol_row[0][1] == ""  # NULL → empty


def test_inner_join_all_match(db):
    _setup(db)
    r = run_sql(db, "SELECT orders.item FROM users INNER JOIN orders ON users.id = orders.user_id ORDER BY orders.id ASC")
    _, rows = parse_rows(r)
    assert [r[0] for r in rows] == ["Book", "Pen", "Notebook"]


def test_select_star_join_column_order_and_disambiguation(db):
    """SELECT * on a JOIN: left-table cols first, right-table cols second.
    Ambiguous column names (both tables have 'id') must be disambiguated
    as 'users.id' and 'orders.id' in the header."""
    _setup(db)
    r = run_sql(db, "SELECT * FROM users INNER JOIN orders ON users.id = orders.user_id")
    assert_success(r)
    header, rows = parse_rows(r)
    # Header must include disambiguated names for shared column 'id'
    assert "users.id" in header, f"Expected 'users.id' in header, got {header}"
    assert "orders.id" in header, f"Expected 'orders.id' in header, got {header}"
    # Left-table columns come before right-table columns
    assert header.index("users.id") < header.index("orders.id")
    assert header.index("users.id") < header.index("item")
