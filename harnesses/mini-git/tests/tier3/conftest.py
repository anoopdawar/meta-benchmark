"""
tier3/conftest.py — Ensures tests/ is on sys.path so `from conftest import ...` works.
"""
import sys
from pathlib import Path

_tests_dir = str(Path(__file__).parent.parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)
