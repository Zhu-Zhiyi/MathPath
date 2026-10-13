"""Run offline checks in a fresh data directory, never against the user's API settings."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

with tempfile.TemporaryDirectory(prefix="mathpath-offline-check-", ignore_cleanup_errors=True) as directory:
    os.environ["MATHPATH_DATA_DIR"] = directory
    os.environ.pop("MATHPATH_DESKTOP", None)
    suite = unittest.defaultTestLoader.discover(str(PROJECT / "tests"), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
