"""Tier 1: data file creation and persistence across process restarts."""

import json
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import assert_success, assert_stdout, run_redis


def test_data_file_created_after_set(db):
    assert not db.exists()
    run_redis(["SET", "k", "v"], data_path=db)
    assert db.exists(), "Data file must be created after SET"


def test_data_file_not_created_by_get(db):
    run_redis(["GET", "nosuchkey"], data_path=db)
    assert not db.exists(), "GET on missing key must not create data file"


def test_data_survives_restart(db):
    run_redis(["SET", "persist_key", "persist_val"], data_path=db)
    # Second process invocation
    r = run_redis(["GET", "persist_key"], data_path=db)
    assert_success(r)
    assert_stdout(r, '"persist_val"')


def test_multiple_keys_survive_restart(db):
    run_redis(["SET", "x", "10"], data_path=db)
    run_redis(["SET", "y", "20"], data_path=db)
    r_x = run_redis(["GET", "x"], data_path=db)
    r_y = run_redis(["GET", "y"], data_path=db)
    assert_stdout(r_x, '"10"')
    assert_stdout(r_y, '"20"')


def test_empty_store_when_file_missing(tmp_path):
    nonexistent = tmp_path / "does_not_exist.json"
    r = run_redis(["GET", "k"], data_path=nonexistent)
    assert_success(r)
    assert_stdout(r, "(nil)")
