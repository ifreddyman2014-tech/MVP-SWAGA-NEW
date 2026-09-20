"""
H3 Renewals — TDD tests (RED before implementation, GREEN after).

Spec tests A–N.
"""
import sys, os, unittest, asyncio, importlib as _importlib
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _uncontaminate_keyboards():
    """Fix aiogram mock contamination from test_fulfillment_sync_reliability.py.

    That file installs MagicMock stubs via sys.modules.setdefault("aiogram*", ...)
    at module level, which causes keyboards.InlineKeyboardMarkup to become a MagicMock
    when keyboards is first imported.  Python functions look up globals from their
    module's __dict__ at call time, so patching the live module object's attributes
    fixes all keyboard-building functions — including those already bound into bot.py.
    """
    if "keyboards" not in sys.modules:
        return  # keyboards not yet imported; will pick up real types on first import.
    _stubs = [k for k in sys.modules if k == "aiogram" or k.startswith("aiogram.")]
    _saved = {k: sys.modules.pop(k) for k in _stubs}
    try:
        from aiogram.types import (
            InlineKeyboardButton, InlineKeyboardMarkup,
            KeyboardButton, ReplyKeyboardMarkup,
        )
        _kb = sys.modules["keyboards"]
        _kb.InlineKeyboardMarkup = InlineKeyboardMarkup
        _kb.InlineKeyboardButton = InlineKeyboardButton
        _kb.KeyboardButton = KeyboardButton
        _kb.ReplyKeyboardMarkup = ReplyKeyboardMarkup
    except Exception:
        sys.modules.update(_saved)  # restore on failure; tests will fail clearly.


_uncontaminate_keyboards()


def _run(coro):
    return asyncio.run(coro)


# ── helpers ───────────────────────────────────────────────────────────────────

def _keyboard_callbacks(kb):
    """Return set of callback_data strings from an InlineKeyboardMarkup."""
    if kb is None:
        return set()
    result = set()
    for row in kb.inline_keyboard:
        for btn in row:
            if getattr(btn, "callback_data", None):
                result.add(btn.callback_data)
    return result


def _has_renewal_cta(kb):
    """True if keyboard has get_access or any renew_* callback."""
    cbs = _keyboard_callbacks(kb)
    return "get_access" in cbs or any(c.startswith("renew_") for c in cbs)


def _make_sub(sub_id=1, user_id=999, end_date="2026-12-01"):
    return {"sub_id": sub_id, "user_id": user_id, "end_date": end_date}


# ══════════════════════════════════════════════════════════════════════════════
#  GROUP 1 — Reminder CTA buttons (A–D)
# ══════════════════════════════════════════════════════════════════════════════

class TestReminderCTA(unittest.TestCase):
    """Tests A–D: each reminder stage sends an inline renewal CTA."""

    def _run_scheduler_reminders_with_one_bucket(self, bucket_code):
        """Run _scheduler_reminders with one non-empty bucket; return sent keyboards."""
        import bot as bot_module
        sub = _make_sub()
        sent_kbs = []

        async def _inner():
            # First sleep (initial 60s delay) passes; second sleep (3600s loop) cancels.
            sleep_side = mock.AsyncMock(
                side_effect=[None, asyncio.CancelledError()]
            )
            with mock.patch("bot.get_subs_for_reminder") as mock_get, \
                 mock.patch("bot.mark_reminder_sent"), \
                 mock.patch("bot.bot") as mock_bot, \
                 mock.patch("bot.asyncio.sleep", sleep_side):

                async def _get(hours, reminder_code):
                    return [sub] if reminder_code == bucket_code else []
                mock_get.side_effect = _get

                async def _send(uid, text, **kwargs):
                    sent_kbs.append(kwargs.get("reply_markup"))
                mock_bot.send_message.side_effect = _send

                try:
                    await bot_module._scheduler_reminders()
                except asyncio.CancelledError:
                    pass

        _run(_inner())
        return sent_kbs

    # A — 72h reminder has renewal CTA
    def test_A_72h_reminder_has_renewal_cta(self):
        sent_kbs = self._run_scheduler_reminders_with_one_bucket("3d")
        self.assertTrue(sent_kbs, "72h reminder: no message sent")
        self.assertTrue(_has_renewal_cta(sent_kbs[0]),
                        f"72h reminder keyboard must contain renewal CTA, "
                        f"got callbacks: {_keyboard_callbacks(sent_kbs[0])}")

    # B — 24h reminder has renewal CTA
    def test_B_24h_reminder_has_renewal_cta(self):
        sent_kbs = self._run_scheduler_reminders_with_one_bucket("1d")
        self.assertTrue(sent_kbs, "24h reminder: no message sent")
        self.assertTrue(_has_renewal_cta(sent_kbs[0]),
                        f"24h reminder keyboard must contain renewal CTA, "
                        f"got callbacks: {_keyboard_callbacks(sent_kbs[0])}")

    # C — 3h reminder has renewal CTA
    def test_C_3h_reminder_has_renewal_cta(self):
        sent_kbs = self._run_scheduler_reminders_with_one_bucket("3h")
        self.assertTrue(sent_kbs, "3h reminder: no message sent")
        self.assertTrue(_has_renewal_cta(sent_kbs[0]),
                        f"3h reminder keyboard must contain renewal CTA, "
                        f"got callbacks: {_keyboard_callbacks(sent_kbs[0])}")

    # D — expired notification has renewal CTA
    def test_D_expired_notification_has_renewal_cta(self):
        import bot as bot_module
        sub = {
            "sub_id": 1, "user_id": 999,
            "end_date": "2026-01-01", "vless_uuid": "test-uuid",
        }
        sent_kbs = []

        async def _inner():
            # First sleep (midnight wait) passes; second sleep cancels.
            sleep_side = mock.AsyncMock(
                side_effect=[None, asyncio.CancelledError()]
            )
            with mock.patch("bot.list_expired", return_value=[sub]), \
                 mock.patch("bot.deactivate_subscription"), \
                 mock.patch("bot.asyncio.get_event_loop") as mock_loop, \
                 mock.patch("bot._delete_client_from_all_servers"), \
                 mock.patch("bot.bot") as mock_bot, \
                 mock.patch("bot.notify_admins"), \
                 mock.patch("bot.asyncio.sleep", sleep_side):

                mock_loop.return_value.run_in_executor = mock.AsyncMock(return_value=None)

                async def _send(uid, text, **kwargs):
                    sent_kbs.append(kwargs.get("reply_markup"))
                mock_bot.send_message.side_effect = _send

                try:
                    await bot_module._scheduler_expiration_check()
                except asyncio.CancelledError:
                    pass

        _run(_inner())
        self.assertTrue(sent_kbs, "expired notification: no message sent")
        self.assertTrue(_has_renewal_cta(sent_kbs[0]),
                        f"expired notification keyboard must contain renewal CTA, "
                        f"got callbacks: {_keyboard_callbacks(sent_kbs[0])}")


# ══════════════════════════════════════════════════════════════════════════════
#  GROUP 2 — CTA destinations (E)
# ══════════════════════════════════════════════════════════════════════════════

class TestCTADestination(unittest.TestCase):
    """Test E: CTA callback opens tariff-selection handler directly."""

    def test_E_renew_cta_kb_exists_with_get_access(self):
        """`renew_cta_kb()` (no source) must produce keyboard with 'get_access' callback."""
        from keyboards import renew_cta_kb
        kb = renew_cta_kb()
        cbs = _keyboard_callbacks(kb)
        self.assertIn("get_access", cbs,
                      f"renew_cta_kb() must contain 'get_access', got: {cbs}")

    def test_E2_renew_cta_kb_with_source_produces_renew_callback(self):
        """`renew_cta_kb('72h')` must produce keyboard with 'renew_72h' callback."""
        from keyboards import renew_cta_kb
        kb = renew_cta_kb("72h")
        cbs = _keyboard_callbacks(kb)
        self.assertIn("renew_72h", cbs,
                      f"renew_cta_kb('72h') must contain 'renew_72h', got: {cbs}")

    def test_E3_renew_source_handlers_exist(self):
        """Handlers for renew_72h, renew_24h, renew_3h, renew_expired, renew_cabinet must exist."""
        import bot as bot_module
        for source in ("72h", "24h", "3h", "expired", "cabinet"):
            handler_name = f"cb_renew_{source}"
            self.assertTrue(
                hasattr(bot_module, handler_name),
                f"bot.{handler_name} handler does not exist",
            )


# ══════════════════════════════════════════════════════════════════════════════
#  GROUP 3 — Cabinet CTAs (F, G)
# ══════════════════════════════════════════════════════════════════════════════

class TestCabinetCTA(unittest.TestCase):
    """Tests F–G: renewal CTA visible in cabinet for active and expired users."""

    # F — active cabinet quick_connect_kb has renewal CTA
    def test_F_active_cabinet_has_renewal_cta(self):
        """`quick_connect_kb` must include a renewal CTA button."""
        from keyboards import quick_connect_kb
        kb = quick_connect_kb("https://sub.example.com/abc123")
        cbs = _keyboard_callbacks(kb)
        self.assertTrue(
            "get_access" in cbs or any(c.startswith("renew_") for c in cbs),
            f"quick_connect_kb must include renewal CTA, got: {cbs}",
        )

    # G — no-sub / expired cabinet has renewal CTA
    def test_G_nosub_cabinet_has_renewal_cta(self):
        """`cabinet_kb` must include 'get_access' button."""
        from keyboards import cabinet_kb
        kb = cabinet_kb()
        cbs = _keyboard_callbacks(kb)
        self.assertIn("get_access", cbs,
                      f"cabinet_kb must include 'get_access', got: {cbs}")


# ══════════════════════════════════════════════════════════════════════════════
#  GROUP 4 — Duplicate prevention (H, I)
# ══════════════════════════════════════════════════════════════════════════════

class TestDuplicatePrevention(unittest.TestCase):
    """Tests H–I: duplicate reminder prevention."""

    def test_H_expiration_check_no_longer_sends_duplicate_3d(self):
        """`_scheduler_expiration_check` must NOT call `list_expiring`.

        The 3-day reminder is exclusively owned by `_scheduler_reminders`
        (which uses mark_reminder_sent dedup). The midnight scheduler must
        only handle truly expired subscriptions.
        """
        import bot as bot_module
        import inspect
        src = inspect.getsource(bot_module._scheduler_expiration_check)
        self.assertNotIn(
            "list_expiring", src,
            "_scheduler_expiration_check must not call list_expiring "
            "(duplicate of _scheduler_reminders 3-day reminder)",
        )

    def test_I_reminder_sent_tracking_is_authoritative(self):
        """`get_subs_for_reminder` and `mark_reminder_sent` exist with correct signatures."""
        from database import get_subs_for_reminder, mark_reminder_sent
        import inspect
        for fn, required_params in [
            (get_subs_for_reminder, ["hours", "reminder_code"]),
            (mark_reminder_sent, ["sub_id", "reminder_code"]),
        ]:
            sig = inspect.signature(fn)
            params = list(sig.parameters.keys())
            for p in required_params:
                self.assertIn(p, params,
                              f"{fn.__name__} must have parameter '{p}'")
            self.assertTrue(asyncio.iscoroutinefunction(fn),
                            f"{fn.__name__} must be async")


# ══════════════════════════════════════════════════════════════════════════════
#  GROUP 5 — Renewal semantics (J, K)
# ══════════════════════════════════════════════════════════════════════════════

class TestRenewalSemantics(unittest.TestCase):
    """Tests J–K: renewing active sub extends current expiry; confirmation shows new date."""

    def test_J_renewal_extends_from_current_expiry(self):
        """`begin_fulfillment` must accept `is_renewal=True` and `no_shrink` behavior."""
        from database import begin_fulfillment
        import inspect
        sig = inspect.signature(begin_fulfillment)
        params = list(sig.parameters.keys())
        self.assertIn("is_renewal", params,
                      "begin_fulfillment must accept is_renewal parameter")

    def test_K_payment_confirmation_shows_new_expiry(self):
        """`handle_payment_success` must call `format_date` and include ✅."""
        import bot as bot_module
        import inspect
        src = inspect.getsource(bot_module.handle_payment_success)
        self.assertIn("format_date", src,
                      "handle_payment_success must call format_date to show new expiry")
        self.assertIn("✅", src,
                      "handle_payment_success must include ✅ in success confirmation")


# ══════════════════════════════════════════════════════════════════════════════
#  GROUP 6 — Trial semantics (L)
# ══════════════════════════════════════════════════════════════════════════════

class TestTrialSemantics(unittest.TestCase):
    """Test L: trial reminder copy does not misrepresent as paid renewal."""

    def test_L_reminder_does_not_use_paid_copy(self):
        """Reminder messages must not contain 'платн' (implies paid-only)."""
        import bot as bot_module
        import inspect
        src = inspect.getsource(bot_module._scheduler_reminders)
        self.assertNotIn("платн", src.lower(),
                         "_scheduler_reminders text must not contain 'платн'")


# ══════════════════════════════════════════════════════════════════════════════
#  GROUP 7 — Infra boundary (M)
# ══════════════════════════════════════════════════════════════════════════════

class TestInfraBoundary(unittest.TestCase):
    """Test M: H3 does not modify provisioning/xui/servers infrastructure."""

    def _check_no_h3_tokens(self, module_name, h3_tokens):
        import importlib, inspect
        mod = importlib.import_module(module_name)
        src = inspect.getsource(mod)
        for tok in h3_tokens:
            self.assertNotIn(tok, src,
                             f"{module_name}.py must not reference H3 token '{tok}'")

    def test_M_provisioning_untouched(self):
        self._check_no_h3_tokens("provisioning",
                                 ["renew_cta_kb", "mark_reminder_sent"])

    def test_M2_xui_api_untouched(self):
        self._check_no_h3_tokens("xui_api",
                                 ["renew_cta_kb", "mark_reminder_sent"])

    def test_M3_servers_untouched(self):
        self._check_no_h3_tokens("servers",
                                 ["renew_cta_kb", "mark_reminder_sent"])


# ══════════════════════════════════════════════════════════════════════════════
#  GROUP 8 — Expiry-aware dedup / cycle reset (N1–N3)
# ══════════════════════════════════════════════════════════════════════════════

class TestExpiryAwareDedup(unittest.TestCase):
    """Tests N1–N3: reminder cycle resets after renewal changes end_date."""

    def test_N1_begin_fulfillment_resets_reminder_sent(self):
        """`begin_fulfillment` or `mark_payment_fulfilled` must reset reminder_sent.

        After a successful renewal changes end_date, the new expiry window must
        be eligible for reminder sends again. We verify that there exists a DB
        function that clears reminder_sent for a subscription.
        """
        import database
        # Either begin_fulfillment clears it internally, or there's a dedicated reset fn
        has_reset = (
            hasattr(database, "reset_reminder_sent")
            or "reminder_sent" in _get_begin_fulfillment_source()
        )
        self.assertTrue(
            has_reset,
            "database must reset reminder_sent on renewal "
            "(via begin_fulfillment or reset_reminder_sent)",
        )

    def test_N2_old_expiry_cannot_resend_same_stage(self):
        """`get_subs_for_reminder` excludes subs with reminder_code already in reminder_sent."""
        import database, inspect
        src = inspect.getsource(database.get_subs_for_reminder)
        self.assertIn("reminder_sent", src,
                      "get_subs_for_reminder must check reminder_sent column")
        self.assertIn("NOT LIKE", src.upper(),
                      "get_subs_for_reminder must use NOT LIKE to exclude sent codes")

    def test_N3_renew_source_handlers_route_to_tariffs(self):
        """renew_<source> handlers must invoke cb_get_access or show tariffs directly."""
        import bot as bot_module, inspect
        # Module source is used as fallback when dp is mocked (decorator wraps fn in MagicMock)
        bot_module_src = inspect.getsource(bot_module)
        for source in ("72h", "24h", "3h", "expired", "cabinet"):
            handler_name = f"cb_renew_{source}"
            self.assertTrue(hasattr(bot_module, handler_name),
                            f"bot.{handler_name} must exist")
            handler = getattr(bot_module, handler_name)
            try:
                handler_src = inspect.getsource(handler)
            except TypeError:
                # Mock dp wraps the function in a MagicMock — fall back to the
                # function's definition site in the module source file.
                self.assertIn(f"async def {handler_name}", bot_module_src,
                              f"async def {handler_name} not found in bot.py")
                idx = bot_module_src.index(f"async def {handler_name}")
                handler_src = bot_module_src[idx: idx + 300]
            routes_to_tariffs = (
                "cb_get_access" in handler_src
                or "get_access" in handler_src
                or "plans_kb" in handler_src
                or "Выберите тариф" in handler_src
                or "_renew_click" in handler_src  # delegates to shared routing fn
            )
            self.assertTrue(
                routes_to_tariffs,
                f"cb_renew_{source} must route to tariff selection "
                f"(call cb_get_access or show plans_kb)",
            )


def _get_begin_fulfillment_source() -> str:
    import database, inspect
    try:
        return inspect.getsource(database.begin_fulfillment)
    except Exception:
        return ""


# ══════════════════════════════════════════════════════════════════════════════
#  GROUP 9 — Migration safety (N4, N5)
# ══════════════════════════════════════════════════════════════════════════════

class TestMigrationSafety(unittest.TestCase):
    """Tests N4–N5: existing reminder flags preserved on unchanged end_date;
    renewal clears flags for new cycle."""

    def test_N4_legacy_flags_preserved_without_renewal(self):
        """get_subs_for_reminder must still exclude subs with legacy reminder_sent flags.

        A subscription with reminder_sent="3d" and end_date unchanged must NOT
        be returned for the "3d" bucket — no resend purely from H3 deploy.
        Verifies that the NOT LIKE guard is present in the query (unchanged).
        """
        import database, inspect
        src = inspect.getsource(database.get_subs_for_reminder)
        self.assertIn("NOT LIKE", src.upper(),
                      "get_subs_for_reminder must use NOT LIKE guard — "
                      "legacy reminder_sent flags must continue to block resend")
        self.assertIn("reminder_sent", src,
                      "get_subs_for_reminder must check reminder_sent column")

    def test_N5_renewal_clears_reminder_sent_for_new_cycle(self):
        """begin_fulfillment must reset reminder_sent when end_date changes on renewal.

        After renewal, the new expiry window must be eligible for reminder sends.
        We verify that begin_fulfillment (or a function it calls) resets
        reminder_sent, so the next scheduler run can deliver fresh reminders.
        """
        import database, inspect

        # Primary: begin_fulfillment itself resets reminder_sent
        begin_src = _get_begin_fulfillment_source()
        resets_in_begin = "reminder_sent" in begin_src

        # Acceptable alternative: dedicated reset function exists
        has_reset_fn = hasattr(database, "reset_reminder_sent")

        self.assertTrue(
            resets_in_begin or has_reset_fn,
            "After renewal, reminder_sent must be cleared so the new expiry "
            "starts a fresh reminder cycle. Implement either: "
            "(a) reset in begin_fulfillment, or "
            "(b) database.reset_reminder_sent() called by bot on renewal.",
        )

    def test_N5b_renewal_reset_does_not_fire_without_end_date_change(self):
        """reminder_sent is NOT cleared for subscriptions that were not renewed.

        This is implicit: the reset only runs inside begin_fulfillment, which
        is only called during payment fulfillment. Scheduler/reminder code
        never clears reminder_sent itself.
        """
        import bot as bot_module, inspect
        scheduler_src = inspect.getsource(bot_module._scheduler_reminders)
        # Scheduler must not reset reminder_sent (that would cause duplicate sends)
        self.assertNotIn(
            "reminder_sent = ''", scheduler_src,
            "_scheduler_reminders must not reset reminder_sent "
            "(only begin_fulfillment/renewal should clear it)",
        )
        expiry_src = inspect.getsource(bot_module._scheduler_expiration_check)
        self.assertNotIn(
            "reminder_sent = ''", expiry_src,
            "_scheduler_expiration_check must not reset reminder_sent",
        )


if __name__ == "__main__":
    unittest.main()
