"""
H4 Purchase → Connection UX — TDD tests (RED before implementation, GREEN after).

Tests A–J.
"""
import sys, os, asyncio, unittest, importlib as _importlib
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _uncontaminate_keyboards():
    """Fix aiogram mock contamination (same pattern as test_h3_renewals)."""
    if "keyboards" not in sys.modules:
        return
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
        sys.modules.update(_saved)


_uncontaminate_keyboards()


def _run(coro):
    return asyncio.run(coro)


def _keyboard_urls(kb):
    """Return set of url strings from an InlineKeyboardMarkup."""
    if kb is None:
        return set()
    result = set()
    for row in kb.inline_keyboard:
        for btn in row:
            if getattr(btn, "url", None):
                result.add(btn.url)
    return result


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


# ══════════════════════════════════════════════════════════════════════════════
#  A — payment success message has connect CTA keyboard
# ══════════════════════════════════════════════════════════════════════════════

class TestPaymentSuccessConnectCTA(unittest.TestCase):
    """Test A: handle_payment_success uses payment_success_kb (not quick_connect_kb)."""

    def test_A_payment_success_uses_payment_success_kb(self):
        import bot as bot_module, inspect
        src = inspect.getsource(bot_module.handle_payment_success)
        self.assertIn(
            "payment_success_kb", src,
            "handle_payment_success must call payment_success_kb for the user notification",
        )

    def test_A2_payment_success_kb_exists_in_keyboards(self):
        from keyboards import payment_success_kb
        from keyboards import InlineKeyboardMarkup
        kb = payment_success_kb("https://sub.swaga-vpn.ru/connect/abc123")
        self.assertIsInstance(kb, InlineKeyboardMarkup,
                              "payment_success_kb must return InlineKeyboardMarkup")

    def test_A3_payment_success_kb_primary_cta_is_url_button(self):
        """payment_success_kb first button is a URL button pointing to sub_url."""
        from keyboards import payment_success_kb
        sub_url = "https://sub.swaga-vpn.ru/connect/testid"
        kb = payment_success_kb(sub_url)
        urls = _keyboard_urls(kb)
        self.assertIn(sub_url, urls,
                      "payment_success_kb must have a URL button pointing to sub_url (connect CTA)")


# ══════════════════════════════════════════════════════════════════════════════
#  B — raw VLESS URI hidden from payment success message body
# ══════════════════════════════════════════════════════════════════════════════

class TestPaymentSuccessNoRawVless(unittest.TestCase):
    """Test B: handle_payment_success message body does NOT contain raw vless:// URI."""

    def test_B_payment_success_text_has_no_vless_code_block(self):
        import bot as bot_module, inspect
        src = inspect.getsource(bot_module.handle_payment_success)
        # The user notification text block must not expose the vless_link inline
        self.assertNotIn(
            "<code>{vless_link}</code>", src,
            "Payment success user message must not expose raw VLESS URI in a code block",
        )

    def test_B2_payment_success_text_has_no_vless_key_section(self):
        import bot as bot_module, inspect
        src = inspect.getsource(bot_module.handle_payment_success)
        # Must not have the literal "🔑 Ваш конфиг:" header in the success text
        self.assertNotIn(
            "🔑 <b>Ваш конфиг:</b>", src,
            "Payment success message must not contain the raw config header",
        )


# ══════════════════════════════════════════════════════════════════════════════
#  C — manual config available via explicit button
# ══════════════════════════════════════════════════════════════════════════════

class TestManualConfigCallback(unittest.TestCase):
    """Test C: cb_show_config handler exists; payment_success_kb has show_config callback."""

    def test_C_show_config_handler_in_bot(self):
        import bot as bot_module, inspect
        bot_src = inspect.getsource(bot_module)
        self.assertIn(
            "show_config", bot_src,
            "bot.py must define a show_config callback handler",
        )

    def test_C2_payment_success_kb_has_show_config_callback(self):
        from keyboards import payment_success_kb
        kb = payment_success_kb("https://sub.swaga-vpn.ru/connect/abc")
        cbs = _keyboard_callbacks(kb)
        self.assertIn(
            "show_config", cbs,
            "payment_success_kb must include 'show_config' callback button",
        )

    def test_C3_cb_show_config_handler_exists(self):
        import bot as bot_module, inspect
        bot_src = inspect.getsource(bot_module)
        self.assertTrue(
            hasattr(bot_module, "cb_show_config") or "async def cb_show_config" in bot_src,
            "bot must define async def cb_show_config handler",
        )


# ══════════════════════════════════════════════════════════════════════════════
#  D — active subscription /connect/ still returns HTML (regression)
# ══════════════════════════════════════════════════════════════════════════════

class TestConnectActiveRegression(unittest.TestCase):
    """Test D: /connect/ for an active subscription returns HTML (not broken)."""

    def test_D_connect_returns_html_content_type_for_active_sub(self):
        import sub_app, inspect
        src = inspect.getsource(sub_app.handle_connect)
        # Verify the active path reaches the HTML response line
        self.assertIn(
            'content_type="text/html"', src,
            "/connect/ must return text/html for active subscription",
        )

    def test_D2_connect_html_template_has_deeplinks(self):
        """CONNECT_HTML template contains working deep-link variables."""
        import sub_app
        for var in ("hiddify_deeplink", "karing_deeplink", "happ_deeplink"):
            self.assertIn(
                "{" + var + "}", sub_app.CONNECT_HTML,
                f"CONNECT_HTML must contain deeplink placeholder {{{var}}}",
            )


# ══════════════════════════════════════════════════════════════════════════════
#  E — expired subscription /connect/ returns friendly HTML
# ══════════════════════════════════════════════════════════════════════════════

class TestExpiredConnectFriendly(unittest.TestCase):
    """Test E: expired /connect/ shows renewal page, not raw 403."""

    def test_E_expired_connect_is_not_raw_403(self):
        import sub_app as sub_app_module

        inactive_sub = {
            "sub_id": 1, "user_id": 999, "vless_uuid": "test-uuid",
            "is_active": False, "end_date": "2026-01-01",
            "xui_sub_id": "test_sub_id",
        }
        req = mock.MagicMock()
        req.match_info = {"sub_id": "test_sub_id"}

        async def _inner():
            with mock.patch("sub_app.get_sub_by_xui_id",
                            new=mock.AsyncMock(return_value=inactive_sub)):
                return await sub_app_module.handle_connect(req)

        resp = _run(_inner())
        self.assertEqual(
            resp.content_type, "text/html",
            "Expired /connect/ must return text/html, not a raw HTTP error",
        )
        body = resp.text
        self.assertNotEqual(
            body, "subscription expired",
            "Expired /connect/ must not return plain text 'subscription expired'",
        )

    def test_E2_expired_connect_contains_renewal_cta(self):
        import sub_app as sub_app_module

        inactive_sub = {
            "sub_id": 1, "user_id": 999, "vless_uuid": "test-uuid",
            "is_active": False, "end_date": "2026-01-01",
            "xui_sub_id": "test_sub_id",
        }
        req = mock.MagicMock()
        req.match_info = {"sub_id": "test_sub_id"}

        async def _inner():
            with mock.patch("sub_app.get_sub_by_xui_id",
                            new=mock.AsyncMock(return_value=inactive_sub)):
                return await sub_app_module.handle_connect(req)

        resp = _run(_inner())
        body = resp.text.lower()
        has_cta = (
            "продли" in body
            or "подписк" in body
            or "t.me" in body
            or "telegram" in body.lower()
        )
        self.assertTrue(
            has_cta,
            "Expired /connect/ must contain a renewal CTA or link to the bot",
        )


# ══════════════════════════════════════════════════════════════════════════════
#  F — no-subscription /connect/ returns friendly HTML
# ══════════════════════════════════════════════════════════════════════════════

class TestNoSubConnectFriendly(unittest.TestCase):
    """Test F: no-sub /connect/ shows get-access page, not raw 404."""

    def test_F_nosub_connect_is_not_raw_404(self):
        import sub_app as sub_app_module

        req = mock.MagicMock()
        req.match_info = {"sub_id": "unknown_sub_id"}

        async def _inner():
            with mock.patch("sub_app.get_sub_by_xui_id",
                            new=mock.AsyncMock(return_value=None)):
                return await sub_app_module.handle_connect(req)

        resp = _run(_inner())
        self.assertEqual(
            resp.content_type, "text/html",
            "No-sub /connect/ must return text/html, not a raw HTTP 404",
        )
        body = resp.text
        self.assertNotEqual(
            body, "subscription not found",
            "No-sub /connect/ must not return plain text 'subscription not found'",
        )

    def test_F2_nosub_connect_contains_get_access_cta(self):
        import sub_app as sub_app_module

        req = mock.MagicMock()
        req.match_info = {"sub_id": "unknown_sub_id"}

        async def _inner():
            with mock.patch("sub_app.get_sub_by_xui_id",
                            new=mock.AsyncMock(return_value=None)):
                return await sub_app_module.handle_connect(req)

        resp = _run(_inner())
        body = resp.text.lower()
        has_cta = (
            "получить" in body
            or "доступ" in body
            or "t.me" in body
            or "подписк" in body
        )
        self.assertTrue(
            has_cta,
            "No-sub /connect/ must contain a get-access CTA or link to the bot",
        )


# ══════════════════════════════════════════════════════════════════════════════
#  G — support action visible in payment success keyboard
# ══════════════════════════════════════════════════════════════════════════════

class TestSupportActionVisible(unittest.TestCase):
    """Test G: payment_success_kb includes a support button."""

    def test_G_payment_success_kb_has_support_url(self):
        from keyboards import payment_success_kb
        from config import SUPPORT_URL
        kb = payment_success_kb("https://sub.swaga-vpn.ru/connect/abc")
        urls = _keyboard_urls(kb)
        self.assertIn(
            SUPPORT_URL, urls,
            f"payment_success_kb must include SUPPORT_URL button ({SUPPORT_URL})",
        )


# ══════════════════════════════════════════════════════════════════════════════
#  H — H3 regression: renew_cta_kb still works
# ══════════════════════════════════════════════════════════════════════════════

class TestH3RenewalRegression(unittest.TestCase):
    """Test H: H3 renew_cta_kb still produces correct callbacks after H4 changes."""

    def test_H_renew_cta_kb_72h_still_works(self):
        from keyboards import renew_cta_kb
        kb = renew_cta_kb("72h")
        cbs = _keyboard_callbacks(kb)
        self.assertIn("renew_72h", cbs,
                      "renew_cta_kb('72h') must still produce renew_72h callback (H3 regression)")

    def test_H2_quick_connect_kb_has_renew_cabinet(self):
        from keyboards import quick_connect_kb
        kb = quick_connect_kb("https://sub.swaga-vpn.ru/connect/abc")
        cbs = _keyboard_callbacks(kb)
        self.assertIn("renew_cabinet", cbs,
                      "quick_connect_kb must still have renew_cabinet callback (H3 regression)")


# ══════════════════════════════════════════════════════════════════════════════
#  I — infra boundary: provisioning/xui untouched
# ══════════════════════════════════════════════════════════════════════════════

class TestInfraBoundary(unittest.TestCase):
    """Test I: H4 does not modify provisioning/xui/servers infrastructure."""

    def _check_no_h4_tokens(self, module_name, tokens):
        import importlib, inspect
        mod = importlib.import_module(module_name)
        src = inspect.getsource(mod)
        for tok in tokens:
            self.assertNotIn(tok, src,
                             f"{module_name}.py must not reference H4 token '{tok}'")

    def test_I_provisioning_untouched(self):
        self._check_no_h4_tokens("provisioning",
                                 ["payment_success_kb", "show_config", "cb_show_config"])

    def test_I2_xui_api_untouched(self):
        self._check_no_h4_tokens("xui_api",
                                 ["payment_success_kb", "show_config", "cb_show_config"])

    def test_I3_servers_untouched(self):
        self._check_no_h4_tokens("servers",
                                 ["payment_success_kb", "show_config"])


# ══════════════════════════════════════════════════════════════════════════════
#  J — US2 zero contact
# ══════════════════════════════════════════════════════════════════════════════

class TestUS2ZeroContact(unittest.TestCase):
    """Test J: H4 new code paths do not reference us2."""

    def test_J_show_config_no_us2_reference(self):
        import bot as bot_module, inspect
        bot_src = inspect.getsource(bot_module)
        # Find show_config handler and check no us2 references
        idx = bot_src.find("async def cb_show_config")
        if idx == -1:
            # Try fallback — at least show_config token must exist
            self.assertIn("show_config", bot_src,
                          "bot must define cb_show_config handler")
            return
        handler_src = bot_src[idx: idx + 500]
        self.assertNotIn(
            "us2", handler_src,
            "cb_show_config handler must not reference us2",
        )

    def test_J2_payment_success_kb_no_us2(self):
        import keyboards, inspect
        src = inspect.getsource(keyboards.payment_success_kb)
        self.assertNotIn("us2", src,
                         "payment_success_kb must not reference us2")

    def test_J3_expired_nosub_html_no_us2(self):
        import sub_app, inspect
        src = inspect.getsource(sub_app.handle_connect)
        # Check that the new error HTML paths don't expose us2 internals
        # (We check by verifying us2 doesn't appear in the friendly HTML constants)
        if hasattr(sub_app, "_EXPIRED_HTML"):
            self.assertNotIn("us2", sub_app._EXPIRED_HTML)
        if hasattr(sub_app, "_NOSUB_HTML"):
            self.assertNotIn("us2", sub_app._NOSUB_HTML)


if __name__ == "__main__":
    unittest.main()
