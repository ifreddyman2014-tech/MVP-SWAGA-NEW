"""
XUI Live Network Guard — TDD tests (RED before implementation, GREEN after).

Tests A–I: SWAGA_ALLOW_LIVE_XUI env-var must gate ALL live XUI network calls.
Default (absent/wrong value) → LiveXUIAccessDenied raised BEFORE any socket.
Explicit =1 → network path permitted.
Mocked unit tests → remain testable without opt-in.

RED state: LiveXUIAccessDenied not yet defined in xui_api → ImportError on load.
GREEN state: guard implemented, 0 new failures in full suite.
"""
import json
import os
import sys
import unittest
import requests
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("BOT_TOKEN", "123456789:AAHs-FakeTestTokenForUnitTests_Guard")

from xui_api import XUIAPI, EnsureResult, LiveXUIAccessDenied  # RED: ImportError if not exported


# ─── helpers ──────────────────────────────────────────────────────────────────

def _no_live_env() -> dict:
    """Return a copy of os.environ with SWAGA_ALLOW_LIVE_XUI removed."""
    return {k: v for k, v in os.environ.items() if k != "SWAGA_ALLOW_LIVE_XUI"}


def _fresh_xui() -> XUIAPI:
    """XUIAPI instance with _logged_in=False (normal instantiation path)."""
    return XUIAPI()


def _make_xui() -> XUIAPI:
    """XUIAPI with _logged_in=True and mocked-ready session (matches existing test pattern)."""
    xui = XUIAPI.__new__(XUIAPI)
    xui._logged_in = True
    xui.base_url = "http://127.0.0.1:4444/panel"
    xui.session = requests.Session()
    return xui


# ══════════════════════════════════════════════════════════════════════════════
#  A — no env opt-in: LiveXUIAccessDenied raised, zero HTTP
# ══════════════════════════════════════════════════════════════════════════════

class TestNoEnvDenied(unittest.TestCase):

    def test_A_no_env_raises_denied_before_http(self):
        """No SWAGA_ALLOW_LIVE_XUI → LiveXUIAccessDenied, no HTTP request made."""
        with mock.patch.dict(os.environ, _no_live_env(), clear=True):
            xui = _fresh_xui()
            with mock.patch.object(xui.session, "post") as mock_post, \
                 mock.patch.object(xui.session, "get") as mock_get:
                with self.assertRaises(LiveXUIAccessDenied) as ctx:
                    xui.login()
                mock_post.assert_not_called()
                mock_get.assert_not_called()
        self.assertIn("disabled", str(ctx.exception).lower())


# ══════════════════════════════════════════════════════════════════════════════
#  B — explicit =0 denied
# ══════════════════════════════════════════════════════════════════════════════

class TestExplicitZeroDenied(unittest.TestCase):

    def test_B_explicit_zero_raises_denied(self):
        """SWAGA_ALLOW_LIVE_XUI=0 → LiveXUIAccessDenied."""
        with mock.patch.dict(os.environ, {"SWAGA_ALLOW_LIVE_XUI": "0"}):
            xui = _fresh_xui()
            with mock.patch.object(xui.session, "post") as mock_post:
                with self.assertRaises(LiveXUIAccessDenied):
                    xui.login()
                mock_post.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
#  C — invalid value denied
# ══════════════════════════════════════════════════════════════════════════════

class TestInvalidValueDenied(unittest.TestCase):

    def test_C_invalid_value_raises_denied(self):
        """SWAGA_ALLOW_LIVE_XUI=yes (not '1') → LiveXUIAccessDenied."""
        with mock.patch.dict(os.environ, {"SWAGA_ALLOW_LIVE_XUI": "yes"}):
            xui = _fresh_xui()
            with self.assertRaises(LiveXUIAccessDenied):
                xui.login()

    def test_C2_true_string_raises_denied(self):
        """SWAGA_ALLOW_LIVE_XUI=true → denied (only '1' is the opt-in)."""
        with mock.patch.dict(os.environ, {"SWAGA_ALLOW_LIVE_XUI": "true"}):
            xui = _fresh_xui()
            with self.assertRaises(LiveXUIAccessDenied):
                xui.login()


# ══════════════════════════════════════════════════════════════════════════════
#  D — explicit =1 permits network path
# ══════════════════════════════════════════════════════════════════════════════

class TestOptInPermits(unittest.TestCase):

    def test_D_opt_in_1_login_attempts_http(self):
        """SWAGA_ALLOW_LIVE_XUI=1 → guard passes, login attempts HTTP (mocked)."""
        with mock.patch.dict(os.environ, {"SWAGA_ALLOW_LIVE_XUI": "1"}):
            xui = _fresh_xui()
            mock_get_resp = mock.MagicMock(text="", status_code=200)
            mock_post_resp = mock.MagicMock()
            mock_post_resp.headers = {"Content-Type": "application/json"}
            mock_post_resp.json.return_value = {"success": True}
            with mock.patch.object(xui.session, "get", return_value=mock_get_resp), \
                 mock.patch.object(xui.session, "post", return_value=mock_post_resp) as mock_post:
                result = xui.login()
            self.assertTrue(result)
            mock_post.assert_called_once()

    def test_D2_opt_in_1_no_exception_raised(self):
        """SWAGA_ALLOW_LIVE_XUI=1 → LiveXUIAccessDenied is NOT raised."""
        with mock.patch.dict(os.environ, {"SWAGA_ALLOW_LIVE_XUI": "1"}):
            xui = _fresh_xui()
            mock_post_resp = mock.MagicMock()
            mock_post_resp.headers = {"Content-Type": "application/json"}
            mock_post_resp.json.return_value = {"success": False, "msg": "bad password"}
            with mock.patch.object(xui.session, "get", return_value=mock.MagicMock(text="")), \
                 mock.patch.object(xui.session, "post", return_value=mock_post_resp):
                try:
                    result = xui.login()
                except LiveXUIAccessDenied:
                    self.fail("LiveXUIAccessDenied raised unexpectedly with SWAGA_ALLOW_LIVE_XUI=1")
            self.assertFalse(result)  # login failed (wrong password), but guard didn't fire


# ══════════════════════════════════════════════════════════════════════════════
#  E — mocked unit test pattern testable WITHOUT env opt-in
# ══════════════════════════════════════════════════════════════════════════════

class TestMockedPathNoOptIn(unittest.TestCase):
    """_make_xui() pattern: _logged_in=True bypasses _ensure_login → login never called
    → guard never triggered → tests work without SWAGA_ALLOW_LIVE_XUI."""

    def test_E_logged_in_true_get_inbound_clients_no_guard(self):
        """_logged_in=True + mocked session.get → no LiveXUIAccessDenied."""
        xui = _make_xui()
        panel_resp = {"success": True, "obj": [
            {"id": 1, "settings": json.dumps({"clients": [{"id": "u", "email": "e"}]})}
        ]}
        with mock.patch.dict(os.environ, _no_live_env(), clear=True):
            with mock.patch.object(xui.session, "get") as mock_get:
                resp = mock.MagicMock()
                resp.headers = {"Content-Type": "application/json"}
                resp.json.return_value = panel_resp
                mock_get.return_value = resp
                try:
                    result = xui.get_inbound_clients(1)
                except LiveXUIAccessDenied:
                    self.fail("LiveXUIAccessDenied raised unexpectedly in mocked test path")
        self.assertIsNotNone(result)

    def test_E2_mock_patch_xui_class_no_guard(self):
        """mock.patch('xui_api.XUIAPI', mock_cls) pattern → no guard triggered."""
        mock_instance = mock.MagicMock()
        mock_instance.login.return_value = True
        mock_cls = mock.MagicMock(return_value=mock_instance)
        with mock.patch.dict(os.environ, _no_live_env(), clear=True):
            with mock.patch("xui_api.XUIAPI", mock_cls):
                from xui_api import XUIAPI as _patched
                inst = _patched()
                try:
                    inst.login()
                except LiveXUIAccessDenied:
                    self.fail("LiveXUIAccessDenied raised when XUIAPI class is fully mocked")


# ══════════════════════════════════════════════════════════════════════════════
#  F — add / update / delete all protected
# ══════════════════════════════════════════════════════════════════════════════

class TestWriteMethodsProtected(unittest.TestCase):

    def test_F_add_client_denied_without_env(self):
        """add_client → _ensure_login → login → LiveXUIAccessDenied."""
        with mock.patch.dict(os.environ, _no_live_env(), clear=True):
            xui = _fresh_xui()
            with mock.patch.object(xui.session, "post") as mock_post:
                with self.assertRaises(LiveXUIAccessDenied):
                    xui.add_client(1, "uuid", "email", "sub", 0, "")
                mock_post.assert_not_called()

    def test_F2_update_client_denied_without_env(self):
        """update_client → _ensure_login → login → LiveXUIAccessDenied."""
        with mock.patch.dict(os.environ, _no_live_env(), clear=True):
            xui = _fresh_xui()
            with mock.patch.object(xui.session, "post") as mock_post:
                with self.assertRaises(LiveXUIAccessDenied):
                    xui.update_client(1, "uuid", "email", "sub", 0, "")
                mock_post.assert_not_called()

    def test_F3_delete_client_denied_without_env(self):
        """delete_client → _ensure_login → login → LiveXUIAccessDenied."""
        with mock.patch.dict(os.environ, _no_live_env(), clear=True):
            xui = _fresh_xui()
            with mock.patch.object(xui.session, "post") as mock_post:
                with self.assertRaises(LiveXUIAccessDenied):
                    xui.delete_client(1, "uuid")
                mock_post.assert_not_called()

    def test_F4_add_or_update_client_denied_without_env(self):
        """add_or_update_client → _ensure_login → login → LiveXUIAccessDenied."""
        with mock.patch.dict(os.environ, _no_live_env(), clear=True):
            xui = _fresh_xui()
            with mock.patch.object(xui.session, "post") as mock_post:
                with self.assertRaises(LiveXUIAccessDenied):
                    xui.add_or_update_client(1, "uuid", "email", "sub", 0, "")
                mock_post.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
#  G — read / login also protected
# ══════════════════════════════════════════════════════════════════════════════

class TestReadMethodsProtected(unittest.TestCase):

    def test_G_login_itself_denied_without_env(self):
        """login() directly → LiveXUIAccessDenied, no session.post."""
        with mock.patch.dict(os.environ, _no_live_env(), clear=True):
            xui = _fresh_xui()
            with mock.patch.object(xui.session, "post") as mock_post, \
                 mock.patch.object(xui.session, "get") as mock_get:
                with self.assertRaises(LiveXUIAccessDenied):
                    xui.login()
                mock_post.assert_not_called()
                mock_get.assert_not_called()

    def test_G2_get_inbound_clients_denied_without_env(self):
        """get_inbound_clients (fresh xui, _logged_in=False) → LiveXUIAccessDenied."""
        with mock.patch.dict(os.environ, _no_live_env(), clear=True):
            xui = _fresh_xui()
            with mock.patch.object(xui.session, "get") as mock_get:
                with self.assertRaises(LiveXUIAccessDenied):
                    xui.get_inbound_clients(1)
                mock_get.assert_not_called()

    def test_G3_ensure_client_denied_without_env(self):
        """ensure_client (fresh xui) → _ensure_login → login → LiveXUIAccessDenied."""
        with mock.patch.dict(os.environ, _no_live_env(), clear=True):
            xui = _fresh_xui()
            with mock.patch.object(xui.session, "post") as mock_post, \
                 mock.patch.object(xui.session, "get") as mock_get:
                with self.assertRaises(LiveXUIAccessDenied):
                    xui.ensure_client(1, "uuid", "email", "sub", 0, "")
                mock_post.assert_not_called()
                mock_get.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
#  H — existing production XUI behavior unchanged with opt-in
# ══════════════════════════════════════════════════════════════════════════════

class TestOptInPreservesExistingBehavior(unittest.TestCase):

    def test_H_login_succeeds_with_opt_in(self):
        """With opt-in, successful login sets _logged_in=True."""
        with mock.patch.dict(os.environ, {"SWAGA_ALLOW_LIVE_XUI": "1"}):
            xui = _fresh_xui()
            mock_post_resp = mock.MagicMock()
            mock_post_resp.headers = {"Content-Type": "application/json"}
            mock_post_resp.json.return_value = {"success": True}
            with mock.patch.object(xui.session, "get", return_value=mock.MagicMock(text="")), \
                 mock.patch.object(xui.session, "post", return_value=mock_post_resp):
                result = xui.login()
            self.assertTrue(result)
            self.assertTrue(xui._logged_in)

    def test_H2_ensure_login_no_op_when_already_logged_in(self):
        """_ensure_login with _logged_in=True does not call login() even with opt-in."""
        with mock.patch.dict(os.environ, {"SWAGA_ALLOW_LIVE_XUI": "1"}):
            xui = _make_xui()  # _logged_in=True
            login_called = []
            original_login = xui.login
            def _spy_login(*a, **kw):
                login_called.append(True)
                return original_login(*a, **kw)
            xui.login = _spy_login
            xui._ensure_login()
            self.assertEqual(login_called, [], "_ensure_login must not call login when _logged_in=True")

    def test_H3_add_client_succeeds_with_opt_in(self):
        """add_client with opt-in calls session.post and returns True on success."""
        with mock.patch.dict(os.environ, {"SWAGA_ALLOW_LIVE_XUI": "1"}):
            xui = _make_xui()  # _logged_in=True, so _ensure_login is no-op
            mock_post_resp = mock.MagicMock()
            mock_post_resp.headers = {"Content-Type": "application/json"}
            mock_post_resp.json.return_value = {"success": True}
            with mock.patch.object(xui.session, "post", return_value=mock_post_resp) as mock_post:
                result = xui.add_client(1, "uuid", "email", "sub", 0, "")
            self.assertTrue(result)
            mock_post.assert_called_once()

    def test_H4_exception_class_is_runtime_error(self):
        """LiveXUIAccessDenied is a RuntimeError subclass for easy catch-all handling."""
        self.assertTrue(issubclass(LiveXUIAccessDenied, RuntimeError))


# ══════════════════════════════════════════════════════════════════════════════
#  I — LiveXUIAccessDenied is a distinct exception (not ConnectionError, not silent)
# ══════════════════════════════════════════════════════════════════════════════

class TestExceptionIsDistinct(unittest.TestCase):

    def test_I_denied_not_connection_error(self):
        """LiveXUIAccessDenied is NOT a ConnectionError — callers can distinguish."""
        self.assertFalse(issubclass(LiveXUIAccessDenied, ConnectionError))

    def test_I2_denied_has_clear_message(self):
        """LiveXUIAccessDenied message references 'disabled' or 'environment'."""
        with mock.patch.dict(os.environ, _no_live_env(), clear=True):
            xui = _fresh_xui()
            with mock.patch.object(xui.session, "post"), \
                 mock.patch.object(xui.session, "get"):
                try:
                    xui.login()
                    self.fail("LiveXUIAccessDenied not raised")
                except LiveXUIAccessDenied as e:
                    msg = str(e).lower()
                    self.assertTrue(
                        "disabled" in msg or "environment" in msg,
                        f"Message too vague: {e}"
                    )


if __name__ == "__main__":
    unittest.main()
