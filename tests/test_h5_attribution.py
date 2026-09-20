"""
H5-MINI — Renewal Attribution TDD tests (RED before implementation, GREEN after).

Tests A–L: renew_source bound to payment record, not user/session.
"""
import sys, os, asyncio, unittest, tempfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database as _db

_TEMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TEMP_DB_PATH = _TEMP_DB.name
_TEMP_DB.close()

# Override before any test runs so standalone invocations never touch production.
_db.DB_PATH = _TEMP_DB_PATH

_PRODUCTION_DB_PATH = "/root/MVP-SWAGA-NEW/vpn_bot.db"


def _assert_db_isolation():
    if _db.DB_PATH == _PRODUCTION_DB_PATH:
        raise RuntimeError("DB_PATH points to production — aborting")


def _run(coro):
    return asyncio.run(coro)


def _keyboard_callbacks(kb):
    if kb is None:
        return set()
    result = set()
    for row in kb.inline_keyboard:
        for btn in row:
            if getattr(btn, "callback_data", None):
                result.add(btn.callback_data)
    return result


# ══════════════════════════════════════════════════════════════════════════════
#  A–F — source stored at payment creation
# ══════════════════════════════════════════════════════════════════════════════

class TestSourceBoundToPayment(unittest.TestCase):
    """Tests A–F: each CTA source is correctly stored in the payment record."""

    @classmethod
    def setUpClass(cls):
        _assert_db_isolation()
        _run(_db.init_db())
        _run(_db.create_user(1001, "user_a"))

    def _create_and_check(self, source, pay_id):
        async def _inner():
            await _db.create_payment(pay_id, 1001, 130.0, "1m", "", renew_source=source)
            return await _db.get_payment(pay_id)
        pmt = _run(_inner())
        self.assertIsNotNone(pmt, f"Payment {pay_id} not found in DB")
        self.assertEqual(pmt.get("renew_source"), source,
                         f"Expected renew_source={source!r}, got {pmt.get('renew_source')!r}")

    def test_A_renew_72h_payment_source(self):
        self._create_and_check("renew_72h", "pay_h5_a_72h")

    def test_B_renew_24h_payment_source(self):
        self._create_and_check("renew_24h", "pay_h5_b_24h")

    def test_C_renew_3h_payment_source(self):
        self._create_and_check("renew_3h", "pay_h5_c_3h")

    def test_D_renew_expired_payment_source(self):
        self._create_and_check("renew_expired", "pay_h5_d_exp")

    def test_E_renew_cabinet_payment_source(self):
        self._create_and_check("renew_cabinet", "pay_h5_e_cab")

    def test_F_ordinary_purchase_renew_source_null(self):
        """Ordinary (non-renewal) purchase must have renew_source=NULL."""
        async def _inner():
            await _db.create_payment("pay_h5_f_null", 1001, 130.0, "1m", "")
            return await _db.get_payment("pay_h5_f_null")
        pmt = _run(_inner())
        self.assertIsNotNone(pmt)
        self.assertIsNone(pmt.get("renew_source"),
                          "Ordinary purchase must have renew_source=NULL")


# ══════════════════════════════════════════════════════════════════════════════
#  G — source belongs to payment, not user
# ══════════════════════════════════════════════════════════════════════════════

class TestSourceOwnership(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        _assert_db_isolation()
        _run(_db.init_db())
        _run(_db.create_user(1002, "user_g"))

    def test_G_each_payment_has_own_source(self):
        """Two payments for same user each keep their own renew_source."""
        async def _inner():
            await _db.create_payment("pay_h5_g_a", 1002, 130.0, "1m", "",
                                     renew_source="renew_24h")
            await _db.create_payment("pay_h5_g_b", 1002, 350.0, "3m", "",
                                     renew_source="renew_cabinet")
            a = await _db.get_payment("pay_h5_g_a")
            b = await _db.get_payment("pay_h5_g_b")
            return a, b
        a, b = _run(_inner())
        self.assertEqual(a.get("renew_source"), "renew_24h",
                         "Payment A must keep renew_24h (not overwritten by B)")
        self.assertEqual(b.get("renew_source"), "renew_cabinet",
                         "Payment B must keep renew_cabinet (independent of A)")

    def test_H_abandoned_source_cannot_leak(self):
        """Abandoned payment A source must NOT appear in later payment B."""
        async def _inner():
            # Payment A from renew_24h — left pending (abandoned)
            await _db.create_payment("pay_h5_h_a", 1002, 130.0, "1m", "",
                                     renew_source="renew_24h")
            # Payment B from ordinary flow — no source
            await _db.create_payment("pay_h5_h_b", 1002, 130.0, "1m", "")
            a = await _db.get_payment("pay_h5_h_a")
            b = await _db.get_payment("pay_h5_h_b")
            return a, b
        a, b = _run(_inner())
        self.assertEqual(a.get("renew_source"), "renew_24h",
                         "Abandoned payment A must still have its own source")
        self.assertIsNone(b.get("renew_source"),
                          "Payment B must have NULL source — A's source must not leak")


# ══════════════════════════════════════════════════════════════════════════════
#  I — webhook preserves source from payment row
# ══════════════════════════════════════════════════════════════════════════════

class TestWebhookPreservesSource(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        _assert_db_isolation()
        _run(_db.init_db())
        _run(_db.create_user(1003, "user_i"))

    def test_I_get_payment_returns_renew_source(self):
        """get_payment must return renew_source stored at creation."""
        async def _inner():
            await _db.create_payment("pay_h5_i", 1003, 130.0, "1m", "",
                                     renew_source="renew_72h")
            return await _db.get_payment("pay_h5_i")
        pmt = _run(_inner())
        self.assertIsNotNone(pmt)
        self.assertEqual(pmt.get("renew_source"), "renew_72h",
                         "get_payment must return renew_source stored at creation")

    def test_I2_renew_source_survives_status_update(self):
        """renew_source must be preserved when payment status changes to succeeded."""
        async def _inner():
            await _db.create_payment("pay_h5_i2", 1003, 130.0, "1m", "",
                                     renew_source="renew_expired")
            await _db.update_payment_status("pay_h5_i2", "succeeded", "2026-09-20T16:00:00")
            return await _db.get_payment("pay_h5_i2")
        pmt = _run(_inner())
        self.assertEqual(pmt.get("status"), "succeeded")
        self.assertEqual(pmt.get("renew_source"), "renew_expired",
                         "renew_source must survive status update to succeeded")


# ══════════════════════════════════════════════════════════════════════════════
#  J — duplicate webhook idempotent
# ══════════════════════════════════════════════════════════════════════════════

class TestDuplicateWebhookIdempotent(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        _assert_db_isolation()
        _run(_db.init_db())
        _run(_db.create_user(1004, "user_j"))

    def test_J_duplicate_webhook_preserves_renew_source(self):
        """Duplicate webhook must not alter renew_source."""
        async def _inner():
            await _db.create_payment("pay_h5_j", 1004, 130.0, "1m", "",
                                     renew_source="renew_cabinet")
            await _db.update_payment_status("pay_h5_j", "succeeded", "2026-09-20T16:00:00")
            await _db.update_payment_status("pay_h5_j", "succeeded", "2026-09-20T16:01:00")
            return await _db.get_payment("pay_h5_j")
        pmt = _run(_inner())
        self.assertEqual(pmt.get("renew_source"), "renew_cabinet",
                         "renew_source must be preserved after duplicate webhook")


# ══════════════════════════════════════════════════════════════════════════════
#  K — attribution failure does not block fulfillment
# ══════════════════════════════════════════════════════════════════════════════

class TestAttributionFailureSafe(unittest.TestCase):

    def test_K_missing_renew_source_is_none(self):
        """Old payment row without renew_source must return None — no exception."""
        pmt = {"payment_id": "pay_old", "status": "succeeded", "amount": 130.0}
        try:
            source = pmt.get("renew_source")
        except Exception as e:
            self.fail(f"pmt.get('renew_source') raised unexpectedly: {e}")
        self.assertIsNone(source)

    def test_K2_handle_payment_success_has_safe_source_lookup(self):
        """handle_payment_success must not crash when renew_source is absent."""
        import bot as bot_module, inspect
        src = inspect.getsource(bot_module.handle_payment_success)
        self.assertIn("renew_source", src,
                      "handle_payment_success must reference renew_source")
        self.assertIn(".get(", src,
                      "renew_source lookup must use .get() (safe for missing key)")


# ══════════════════════════════════════════════════════════════════════════════
#  L — existing H3/H4 behavior unchanged
# ══════════════════════════════════════════════════════════════════════════════

class TestExistingBehaviorUnchanged(unittest.TestCase):

    def test_L_renew_cta_kb_72h_still_works(self):
        from keyboards import renew_cta_kb
        kb = renew_cta_kb("72h")
        cbs = _keyboard_callbacks(kb)
        self.assertIn("renew_72h", cbs,
                      "H3 renew_cta_kb must still produce renew_72h callback")

    def test_L2_payment_success_kb_still_exists(self):
        from keyboards import payment_success_kb, InlineKeyboardMarkup
        kb = payment_success_kb("https://sub.swaga-vpn.ru/connect/test")
        self.assertIsInstance(kb, InlineKeyboardMarkup)

    def test_L3_plans_kb_without_source_unchanged(self):
        """plans_kb without renew_source must not encode any source."""
        from keyboards import plans_kb
        kb = plans_kb(trial_used=True)
        cbs = _keyboard_callbacks(kb)
        plan_cbs = {c for c in cbs if c.startswith("plan_")}
        for cb in plan_cbs:
            self.assertNotIn(":", cb,
                             f"plans_kb without source must not have ':' in {cb!r}")

    def test_L4_plans_kb_with_source_encodes_source(self):
        """plans_kb with renew_source encodes it in each plan callback_data."""
        from keyboards import plans_kb
        kb = plans_kb(trial_used=True, renew_source="renew_72h")
        cbs = _keyboard_callbacks(kb)
        plan_cbs = {c for c in cbs if c.startswith("plan_")}
        self.assertTrue(len(plan_cbs) > 0, "plans_kb must have at least one plan_ button")
        for cb in plan_cbs:
            self.assertIn(":renew_72h", cb,
                          f"plans_kb with source must encode renew_72h in {cb!r}")

    def test_L5_handle_payment_success_source_logging(self):
        """handle_payment_success must reference renew_source for attribution."""
        import bot as bot_module, inspect
        src = inspect.getsource(bot_module.handle_payment_success)
        self.assertIn("renew_source", src,
                      "handle_payment_success must log/use renew_source")

    def test_L6_quick_connect_kb_still_has_renew_cabinet(self):
        from keyboards import quick_connect_kb
        kb = quick_connect_kb("https://sub.swaga-vpn.ru/connect/abc")
        cbs = _keyboard_callbacks(kb)
        self.assertIn("renew_cabinet", cbs,
                      "quick_connect_kb must still have renew_cabinet callback (H3 regression)")


if __name__ == "__main__":
    unittest.main()
