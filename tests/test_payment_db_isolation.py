"""
Regression test: test_payment_logic.py must never write to the production DB.

DESIGN: This file name starts with 'd' — pytest alphabetical collection
ensures it is imported BEFORE test_payment_logic.py ('p').  The module-level
`import database as _db` therefore caches the database module in sys.modules
with the production DB_PATH *before* test_payment_logic.py has a chance to
patch it.

INVARIANTS enforced:
  1. database.DB_PATH does not resolve to the production database.
  2. database.DB_PATH and config.DB_PATH resolve to the same file (no split-brain).
  3. _assert_db_isolation (tripwire added by the fix) exists in
     test_payment_logic and raises RuntimeError on split-brain.
  4. The tripwire also raises when database.DB_PATH == production.

RED state (before fix): test_payment_logic.py only sets config.DB_PATH = temp
but not database.DB_PATH, leaving the cached module pointing at production.
Tests 1–3 fail.

GREEN state (after fix): test_payment_logic.py sets BOTH, so the cached module
is overridden.  All four tests pass.

NOTE: running this file in isolation (without test_payment_logic.py being
collected alongside it) will always fail test_01 because database.DB_PATH
defaults to the production path.  That is intentional — the test is designed
to validate the cross-file import-order safety of the full suite.
"""

import os
import sys
import tempfile
import unittest

# ── Project root on sys.path ─────────────────────────────────────────────────
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_TESTS_DIR)
sys.path.insert(0, _PROJECT_ROOT)

# ── Pre-import database BEFORE test_payment_logic.py can patch it ─────────────
# Alphabetical collection ('d' < 'p') guarantees this runs first.
# If test_payment_logic.py only sets config.DB_PATH and not database.DB_PATH,
# this cached reference will still point at production after collection.
import database as _db
import config as _config

_PRODUCTION_DB_PATH = os.path.realpath(os.path.join(_PROJECT_ROOT, "vpn_bot.db"))


def _get_test_payment_logic_module():
    """Return test_payment_logic module however pytest imported it."""
    for key in ("test_payment_logic", "tests.test_payment_logic"):
        m = sys.modules.get(key)
        if m is not None:
            return m
    if _TESTS_DIR not in sys.path:
        sys.path.insert(0, _TESTS_DIR)
    import importlib
    return importlib.import_module("test_payment_logic")


class TestPaymentDBIsolation(unittest.TestCase):

    def test_01_database_db_path_not_production(self):
        """database.DB_PATH must not resolve to the production database.

        FAIL means: test_payment_logic.py leaves database.DB_PATH pointing
        at production (split-brain: cached module not overridden by the fix).
        All subsequent writes in payment tests go to the production DB.
        """
        actual = os.path.realpath(_db.DB_PATH)
        self.assertNotEqual(
            actual,
            _PRODUCTION_DB_PATH,
            f"SPLIT-BRAIN: database.DB_PATH ({actual!r}) resolves to production "
            f"({_PRODUCTION_DB_PATH!r}). "
            f"Fix: add `db.DB_PATH = _TEMP_DB.name` after `import database as db` "
            f"in test_payment_logic.py."
        )

    def test_02_config_and_database_paths_agree(self):
        """config.DB_PATH and database.DB_PATH must resolve to the same file.

        FAIL means split-brain: helpers that write via aiosqlite.connect(db.DB_PATH)
        go to a different file than helpers that use config.DB_PATH directly.
        """
        db_path = os.path.realpath(_db.DB_PATH)
        cfg_path = os.path.realpath(_config.DB_PATH)
        self.assertEqual(
            db_path,
            cfg_path,
            f"SPLIT-BRAIN: database.DB_PATH={db_path!r} != config.DB_PATH={cfg_path!r}. "
            f"Fix: set both paths to the same temp file in test_payment_logic.py."
        )

    def test_03_tripwire_exists_and_raises_on_split_brain(self):
        """_assert_db_isolation must exist and raise RuntimeError on split-brain paths."""
        tpl = _get_test_payment_logic_module()
        assert_fn = getattr(tpl, "_assert_db_isolation", None)
        self.assertIsNotNone(
            assert_fn,
            "_assert_db_isolation not found in test_payment_logic — "
            "safety tripwire not implemented (part of the fix)."
        )

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as fa:
            sentinel_a = fa.name
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as fb:
            sentinel_b = fb.name

        orig_db = _db.DB_PATH
        orig_cfg = _config.DB_PATH
        try:
            _db.DB_PATH = sentinel_a
            _config.DB_PATH = sentinel_b  # deliberate split-brain
            with self.assertRaises(RuntimeError,
                                   msg="tripwire must raise RuntimeError on split-brain"):
                assert_fn()
        finally:
            _db.DB_PATH = orig_db
            _config.DB_PATH = orig_cfg
            os.unlink(sentinel_a)
            os.unlink(sentinel_b)

    def test_04_tripwire_raises_when_db_path_is_production(self):
        """_assert_db_isolation must raise RuntimeError if database.DB_PATH == production."""
        tpl = _get_test_payment_logic_module()
        assert_fn = getattr(tpl, "_assert_db_isolation", None)
        if assert_fn is None:
            self.skipTest("_assert_db_isolation absent — covered by test_03")

        orig_db = _db.DB_PATH
        orig_cfg = _config.DB_PATH
        try:
            _db.DB_PATH = _PRODUCTION_DB_PATH
            _config.DB_PATH = _PRODUCTION_DB_PATH
            with self.assertRaises(RuntimeError,
                                   msg="tripwire must raise RuntimeError when db path = production"):
                assert_fn()
        finally:
            _db.DB_PATH = orig_db
            _config.DB_PATH = orig_cfg


if __name__ == "__main__":
    unittest.main()
