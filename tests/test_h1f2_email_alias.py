"""
H1-F2 — US1-XHTTP Per-Inbound Email Alias: TDD tests.

Verifies:
  A. panel_email() returns base email for normal servers
  B. panel_email() appends _i3 for us1-xhttp
  C. ensure_client UUID absent → CREATE uses alias email (not base)
  D. ensure_client UUID found with legacy/base email → UPDATE preserves it (no rename)
  E. ensure_client UUID found with alias email → UPDATE preserves alias
  F. alias email belongs to another UUID → CONFLICT, zero writes
  G. base email in inbound3 under another UUID → CONFLICT via extra_conflict_emails
  H. panel read failure → FAILED, zero writes
  I. _server_sync_client us1 inbound1 → base email unchanged
  J. _server_sync_client us1-xhttp → alias email + extra_conflict=[base]
  K. UK1 xui_standard=False → no behavior change
  L. VLESS link generation not affected by panel email alias

RED on unpatched code. GREEN after:
  - PANEL_EMAIL_SUFFIXES + panel_email() in bot.py
  - ensure_client() preserves existing panel email when UUID found
  - ensure_client() extra_conflict_emails parameter
  - _server_sync_client() applies panel_email before ensure_client call
"""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("BOT_TOKEN", "123456789:AAHs-FakeTestTokenH1F2")

_aiomock = mock.MagicMock()
for _m in [
    "aiogram",
    "aiogram.types",
    "aiogram.utils",
    "aiogram.utils.executor",
    "aiogram.dispatcher",
    "aiogram.dispatcher.filters",
    "aiogram.dispatcher.middlewares",
    "aiogram.contrib",
    "aiogram.contrib.fsm_storage",
    "aiogram.contrib.fsm_storage.memory",
]:
    sys.modules.setdefault(_m, _aiomock)

import config as _config

_TEMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TEMP_DB.close()
_config.DB_PATH = _TEMP_DB.name

import database as _db
_db.DB_PATH = _TEMP_DB.name

import bot as _bot
import xui_api as _xui_module
from xui_api import XUIAPI, EnsureResult
from servers import PROTECTED_SERVER_IDS, VPNServer


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_xui() -> XUIAPI:
    xui = XUIAPI.__new__(XUIAPI)
    xui._logged_in = True
    xui.base_url = "http://127.0.0.1:16175/panel"
    import requests
    xui.session = requests.Session()
    return xui


def _inbound_list_resp(inbound_id: int, clients: list) -> dict:
    settings_str = json.dumps({"clients": clients})
    return {
        "success": True,
        "obj": [
            {"id": inbound_id, "settings": settings_str},
            {"id": 99, "settings": json.dumps({"clients": []})},
        ],
    }


def _client(uuid: str, email: str, expiry: int = 0) -> dict:
    return {"id": uuid, "email": email, "enable": True, "expiryTime": expiry,
            "flow": "", "limitIp": 3, "totalGB": 0, "subId": ""}


def _srv(server_id: str, inbound_id: int = 1, standard: bool = True) -> VPNServer:
    return VPNServer(
        id=server_id,
        name=f"Test {server_id}",
        host="10.0.0.1",
        xui_host="127.0.0.1",
        xui_port=16175,
        xui_web_path="/panel",
        xui_username="admin",
        xui_password="pass",
        xui_ssl=False,
        transport="xhttp" if "xhttp" in server_id else "tcp",
        flow="",
        inbound_id=inbound_id,
        xui_standard=standard,
    )


def _xhttp_srv() -> VPNServer:
    return _srv("us1-xhttp", inbound_id=3, standard=True)


def _mock_xui_ensure(result: EnsureResult):
    """Return a mock XUIAPI class whose instance.ensure_client returns result."""
    mock_instance = mock.MagicMock()
    mock_instance.login.return_value = True
    mock_instance.ensure_client.return_value = result
    mock_cls = mock.MagicMock(return_value=mock_instance)
    return mock_cls, mock_instance


# ══════════════════════════════════════════════════════════════════════════════
# GROUP A/B: panel_email() helper
# ══════════════════════════════════════════════════════════════════════════════

class TestPanelEmailDerivation(unittest.TestCase):
    """panel_email() must be deterministic and only alias us1-xhttp."""

    def test_01_normal_server_fr1_returns_base(self):
        """A: fr1 → base email unchanged."""
        self.assertEqual(_bot.panel_email("fr1", "tg_123_456"), "tg_123_456")

    def test_02_us1_primary_returns_base(self):
        """A: us1 inbound1 → base email unchanged."""
        self.assertEqual(_bot.panel_email("us1", "tg_123_456"), "tg_123_456")

    def test_03_us1_xhttp_appends_i3(self):
        """B: us1-xhttp → base email + '_i3'."""
        self.assertEqual(_bot.panel_email("us1-xhttp", "tg_123_456"), "tg_123_456_i3")

    def test_04_empty_base_email_unchanged(self):
        """panel_email with empty string returns empty string (no crash)."""
        self.assertEqual(_bot.panel_email("us1-xhttp", ""), "")

    def test_05_panel_email_suffixes_dict_exists(self):
        """PANEL_EMAIL_SUFFIXES dict must exist in bot module."""
        self.assertTrue(hasattr(_bot, "PANEL_EMAIL_SUFFIXES"))
        self.assertIsInstance(_bot.PANEL_EMAIL_SUFFIXES, dict)
        self.assertIn("us1-xhttp", _bot.PANEL_EMAIL_SUFFIXES)

    def test_06_deterministic_same_input_same_output(self):
        """Same input always produces same output."""
        for _ in range(5):
            self.assertEqual(_bot.panel_email("us1-xhttp", "tg_999_888"), "tg_999_888_i3")

    def test_07_uk1_xhttp_not_in_suffixes(self):
        """UK1-xhttp is out of scope — must NOT be aliased."""
        self.assertEqual(_bot.panel_email("uk1-xhttp", "tg_123_456"), "tg_123_456")

    def test_08_us2_not_in_suffixes(self):
        """us2 is protected — must NOT be aliased."""
        self.assertEqual(_bot.panel_email("us2", "tg_123_456"), "tg_123_456")


# ══════════════════════════════════════════════════════════════════════════════
# GROUP C-H: ensure_client() alias and extra_conflict_emails
# ══════════════════════════════════════════════════════════════════════════════

class TestEnsureClientAlias(unittest.TestCase):
    """ensure_client() must preserve panel email on UUID found, and check extra conflicts."""

    def _mock_list(self, xui, inbound_id, clients):
        resp = mock.MagicMock()
        resp.headers = {"Content-Type": "application/json"}
        resp.json.return_value = _inbound_list_resp(inbound_id, clients)
        return resp

    def test_10_uuid_found_legacy_email_preserved_no_rename(self):
        """D: UUID in panel with legacy/base email → update uses legacy email, not alias."""
        xui = _make_xui()
        base_email = "tg_123_456"
        alias_email = "tg_123_456_i3"
        uuid_val = "uuid-legacy"
        panel = [_client(uuid_val, base_email, expiry=0)]

        update_calls = []

        def fake_update(iid, uuid, email, **kw):
            update_calls.append(email)
            return True

        with mock.patch.object(xui.session, "get") as mg:
            mg.return_value = self._mock_list(xui, 3, panel)
            with mock.patch.object(xui, "update_client", side_effect=fake_update):
                result = xui.ensure_client(3, uuid_val, alias_email)

        self.assertEqual(result, EnsureResult.UPDATED)
        self.assertEqual(len(update_calls), 1)
        # MUST use legacy email from panel, NOT alias_email
        self.assertEqual(update_calls[0], base_email)
        self.assertNotEqual(update_calls[0], alias_email)

    def test_11_uuid_found_alias_email_preserved(self):
        """E: UUID in panel with alias email → update preserves alias (no change)."""
        xui = _make_xui()
        alias_email = "tg_123_456_i3"
        uuid_val = "uuid-alias"
        panel = [_client(uuid_val, alias_email, expiry=0)]

        update_calls = []

        def fake_update(iid, uuid, email, **kw):
            update_calls.append(email)
            return True

        with mock.patch.object(xui.session, "get") as mg:
            mg.return_value = self._mock_list(xui, 3, panel)
            with mock.patch.object(xui, "update_client", side_effect=fake_update):
                result = xui.ensure_client(3, uuid_val, alias_email)

        self.assertEqual(result, EnsureResult.UPDATED)
        self.assertEqual(update_calls[0], alias_email)

    def test_12_alias_conflict_returns_conflict(self):
        """F: alias email in panel under another UUID → CONFLICT, add_client never called."""
        xui = _make_xui()
        alias_email = "tg_123_456_i3"
        our_uuid = "uuid-ours"
        other_uuid = "uuid-other"
        panel = [_client(other_uuid, alias_email)]  # alias already taken

        with mock.patch.object(xui.session, "get") as mg, \
             mock.patch.object(xui, "add_client") as mock_add:
            mg.return_value = self._mock_list(xui, 3, panel)
            result = xui.ensure_client(3, our_uuid, alias_email)

        self.assertEqual(result, EnsureResult.CONFLICT)
        mock_add.assert_not_called()

    def test_13_extra_conflict_email_base_in_panel_returns_conflict(self):
        """G: base email in inbound3 under another UUID → CONFLICT via extra_conflict_emails."""
        xui = _make_xui()
        base_email = "tg_123_456"
        alias_email = "tg_123_456_i3"
        our_uuid = "uuid-ours"
        other_uuid = "uuid-other"
        # Alias absent, but base email exists under a different UUID
        panel = [_client(other_uuid, base_email)]

        with mock.patch.object(xui.session, "get") as mg, \
             mock.patch.object(xui, "add_client") as mock_add:
            mg.return_value = self._mock_list(xui, 3, panel)
            result = xui.ensure_client(
                3, our_uuid, alias_email,
                extra_conflict_emails=[base_email],
            )

        self.assertEqual(result, EnsureResult.CONFLICT)
        mock_add.assert_not_called()

    def test_14_extra_conflict_email_absent_allows_create(self):
        """G counterpart: base email absent in inbound3 → CREATE proceeds normally."""
        xui = _make_xui()
        base_email = "tg_123_456"
        alias_email = "tg_123_456_i3"
        our_uuid = "uuid-ours"
        panel = []  # completely empty

        with mock.patch.object(xui.session, "get") as mg, \
             mock.patch.object(xui, "add_client") as mock_add:
            mg.return_value = self._mock_list(xui, 3, panel)
            mock_add.return_value = True
            result = xui.ensure_client(
                3, our_uuid, alias_email,
                extra_conflict_emails=[base_email],
            )

        self.assertEqual(result, EnsureResult.CREATED)
        mock_add.assert_called_once()
        # add_client called with alias_email, not base_email
        call_email = mock_add.call_args[0][2]  # positional: (iid, uuid, email)
        self.assertEqual(call_email, alias_email)

    def test_15_read_failure_returns_failed(self):
        """H: panel read returns None → FAILED, no writes."""
        xui = _make_xui()
        with mock.patch.object(xui.session, "get", side_effect=Exception("down")), \
             mock.patch.object(xui, "add_client") as mock_add, \
             mock.patch.object(xui, "update_client") as mock_upd:
            result = xui.ensure_client(3, "some-uuid", "some@email")

        self.assertEqual(result, EnsureResult.FAILED)
        mock_add.assert_not_called()
        mock_upd.assert_not_called()

    def test_16_no_extra_conflict_no_regression_for_normal_create(self):
        """Without extra_conflict_emails, normal CREATE still works (no regression)."""
        xui = _make_xui()
        alias_email = "tg_999_i3"
        our_uuid = "uuid-999"
        panel = []

        with mock.patch.object(xui.session, "get") as mg, \
             mock.patch.object(xui, "add_client") as mock_add:
            mg.return_value = self._mock_list(xui, 3, panel)
            mock_add.return_value = True
            result = xui.ensure_client(3, our_uuid, alias_email)

        self.assertEqual(result, EnsureResult.CREATED)
        mock_add.assert_called_once()


# ══════════════════════════════════════════════════════════════════════════════
# GROUP I/J: _server_sync_client routing with panel_email
# ══════════════════════════════════════════════════════════════════════════════

class TestServerSyncClientAliasRouting(unittest.TestCase):
    """_server_sync_client must apply panel_email before calling ensure_client."""

    _patch_base = "xui_api.XUIAPI"

    def _call_sync(self, server, mock_cls, uuid="test-uuid", email="tg_111_222"):
        with mock.patch(self._patch_base, mock_cls):
            return _bot._server_sync_client(server, uuid, email, sub_id="sub1",
                                             expiry_ms=9999999, flow="")

    def test_20_us1_xhttp_ensure_called_with_alias_email(self):
        """J: us1-xhttp → ensure_client receives alias email tg_..._i3, not base."""
        srv = _xhttp_srv()
        mock_cls, instance = _mock_xui_ensure(EnsureResult.CREATED)

        result = self._call_sync(srv, mock_cls, email="tg_111_222")

        self.assertTrue(result)
        ensure_call = instance.ensure_client.call_args
        called_email = ensure_call[0][2] if len(ensure_call[0]) > 2 else ensure_call[1].get("email")
        # Should be alias, not base
        self.assertEqual(called_email, "tg_111_222_i3")

    def test_21_us1_xhttp_extra_conflict_includes_base_email(self):
        """J: us1-xhttp → extra_conflict_emails contains the base email."""
        srv = _xhttp_srv()
        mock_cls, instance = _mock_xui_ensure(EnsureResult.CREATED)

        self._call_sync(srv, mock_cls, email="tg_111_222")

        ensure_call = instance.ensure_client.call_args
        extra = ensure_call[1].get("extra_conflict_emails") or []
        self.assertIn("tg_111_222", extra)

    def test_22_us1_inbound1_uses_base_email_no_extra(self):
        """I: us1 inbound 1 → base email unchanged, no extra_conflict_emails."""
        srv = _srv("us1", inbound_id=1, standard=True)
        mock_cls, instance = _mock_xui_ensure(EnsureResult.ALREADY_OK)

        result = self._call_sync(srv, mock_cls, email="tg_111_222")

        self.assertTrue(result)
        ensure_call = instance.ensure_client.call_args
        called_email = ensure_call[0][2] if len(ensure_call[0]) > 2 else ensure_call[1].get("email")
        # No alias for us1 inbound 1
        self.assertEqual(called_email, "tg_111_222")
        extra = ensure_call[1].get("extra_conflict_emails")
        self.assertFalse(extra)  # None or empty

    def test_23_fr1_uses_base_email_no_extra(self):
        """A/I: fr1 → base email unchanged, no extra_conflict_emails."""
        srv = _srv("fr1", inbound_id=1, standard=True)
        mock_cls, instance = _mock_xui_ensure(EnsureResult.ALREADY_OK)

        result = self._call_sync(srv, mock_cls, email="tg_555_666")

        self.assertTrue(result)
        ensure_call = instance.ensure_client.call_args
        called_email = ensure_call[0][2] if len(ensure_call[0]) > 2 else ensure_call[1].get("email")
        self.assertEqual(called_email, "tg_555_666")
        extra = ensure_call[1].get("extra_conflict_emails")
        self.assertFalse(extra)


# ══════════════════════════════════════════════════════════════════════════════
# GROUP K: UK1 xui_standard=False — no behavior change
# ══════════════════════════════════════════════════════════════════════════════

class TestUk1NoChange(unittest.TestCase):

    def test_30_uk1_xhttp_xui_standard_false_returns_false(self):
        """K: uk1-xhttp xui_standard=False → _server_sync_client returns False (deferred)."""
        srv = _srv("uk1-xhttp", inbound_id=2, standard=False)
        mock_cls, instance = _mock_xui_ensure(EnsureResult.CREATED)

        with mock.patch("xui_api.XUIAPI", mock_cls):
            result = _bot._server_sync_client(srv, "uuid-x", "email@x")

        self.assertFalse(result)
        instance.ensure_client.assert_not_called()

    def test_31_uk1_xhttp_panel_email_not_aliased(self):
        """K: uk1-xhttp is NOT in PANEL_EMAIL_SUFFIXES — no alias applied."""
        self.assertNotIn("uk1-xhttp", _bot.PANEL_EMAIL_SUFFIXES)
        self.assertEqual(_bot.panel_email("uk1-xhttp", "tg_123"), "tg_123")


# ══════════════════════════════════════════════════════════════════════════════
# GROUP J protected: us2 / us2-ws unchanged
# ══════════════════════════════════════════════════════════════════════════════

class TestProtectedServersUnchanged(unittest.TestCase):

    def _run_sync(self, server_id):
        srv = _srv(server_id, standard=True)
        srv.id = server_id
        mock_cls, instance = _mock_xui_ensure(EnsureResult.CREATED)
        with mock.patch("xui_api.XUIAPI", mock_cls):
            return _bot._server_sync_client(srv, "uuid-p", "email-p"), instance

    def test_40_us2_no_xui_contact(self):
        """J: us2 → refused at protection guard, ensure_client never called."""
        result, instance = self._run_sync("us2")
        self.assertFalse(result)
        instance.ensure_client.assert_not_called()

    def test_41_us2_ws_no_contact(self):
        """J: us2-ws → refused at protection guard, ensure_client never called."""
        result, instance = self._run_sync("us2-ws")
        self.assertFalse(result)
        instance.ensure_client.assert_not_called()

    def test_42_us2_panel_email_not_aliased(self):
        """us2 is not in PANEL_EMAIL_SUFFIXES."""
        self.assertNotIn("us2", _bot.PANEL_EMAIL_SUFFIXES)


# ══════════════════════════════════════════════════════════════════════════════
# GROUP L: VLESS link generation unaffected
# ══════════════════════════════════════════════════════════════════════════════

class TestVlessLinkUnaffected(unittest.TestCase):

    def test_50_build_vless_link_has_no_email_parameter(self):
        """L: build_vless_link takes uuid, host, port, transport — no email/panel_email."""
        from utils import build_vless_link
        import inspect
        sig = inspect.signature(build_vless_link)
        param_names = list(sig.parameters.keys())
        # panel_email is a provisioning concern; VLESS link takes UUID and routing params
        self.assertNotIn("email", param_names)
        self.assertNotIn("panel_email", param_names)
        # UUID is always the first parameter
        self.assertEqual(param_names[0], "uuid_str")

    def test_51_vless_link_output_contains_uuid_not_panel_email(self):
        """L: Generated link contains the UUID, not any email alias."""
        from utils import build_vless_link
        uuid_val = "aaaa-bbbb-cccc-dddd"
        link = build_vless_link(
            uuid_str=uuid_val,
            host="1.2.3.4",
            port=2053,
            transport="xhttp",
            path="/test",
            camouflage_host="www.example.com",
            xhttp_mode="packet-up",
            reality_pbk="pubkey123",
            reality_sid="sid123",
            reality_fp="chrome",
            reality_sni="www.example.com",
            reality_spx="/",
        )
        self.assertIn(uuid_val, link)
        # Email aliases should not appear in VPN connection links
        self.assertNotIn("_i3", link)


if __name__ == "__main__":
    unittest.main()
