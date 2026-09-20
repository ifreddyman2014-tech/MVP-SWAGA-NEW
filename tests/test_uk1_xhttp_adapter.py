"""
Tests for UK1 panel fork adapter (H1 final sprint).

UK1 XUI fork uses a different REST API:
  READ:   GET  /panel/api/inbounds/list  → settings is a dict (not JSON string)
  CREATE: POST /panel/api/clients/add    {client: {id, uuid, email, ...}, inboundIds}
  UPDATE: POST /panel/api/clients/update/{email}  same payload
"""

import json
import unittest
from unittest.mock import MagicMock, patch, call
import urllib.parse

from xui_api import XUIAPI, EnsureResult


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mk_api():
    api = XUIAPI.__new__(XUIAPI)
    api.session = MagicMock()
    api._logged_in = True
    api.base_url = "http://127.0.0.1:13226/web"
    return api


def _list_resp(clients: list) -> MagicMock:
    r = MagicMock()
    r.status_code = 200
    r.headers = {"Content-Type": "application/json"}
    r.json.return_value = {
        "success": True,
        "obj": [{"id": 2, "settings": {"clients": clients}}],
    }
    return r


def _ok_resp(msg: str = "ok") -> MagicMock:
    r = MagicMock()
    r.status_code = 200
    r.headers = {"Content-Type": "application/json"}
    r.json.return_value = {"success": True, "msg": msg}
    return r


def _fail_resp(msg: str = "error") -> MagicMock:
    r = MagicMock()
    r.status_code = 200
    r.headers = {"Content-Type": "application/json"}
    r.json.return_value = {"success": False, "msg": msg}
    return r


UUID_A = "aaaa0000-0000-0000-0000-000000000001"
UUID_B = "bbbb0000-0000-0000-0000-000000000002"
EMAIL_A = "tg_100_1001"
EMAIL_B = "tg_200_2002"


# ── 1. get_inbound_clients_uk1 ────────────────────────────────────────────────

class TestGetInboundClientsUk1(unittest.TestCase):

    def test_returns_list_from_dict_settings(self):
        api = _mk_api()
        api.session.get.return_value = _list_resp([{"id": UUID_A, "email": EMAIL_A}])
        result = api.get_inbound_clients_uk1(2)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], UUID_A)

    def test_returns_empty_list_when_no_clients(self):
        api = _mk_api()
        api.session.get.return_value = _list_resp([])
        result = api.get_inbound_clients_uk1(2)
        self.assertEqual(result, [])

    def test_returns_none_on_api_failure(self):
        api = _mk_api()
        r = MagicMock()
        r.status_code = 200
        r.headers = {"Content-Type": "application/json"}
        r.json.return_value = {"success": False, "msg": "error"}
        api.session.get.return_value = r
        result = api.get_inbound_clients_uk1(2)
        self.assertIsNone(result)

    def test_returns_none_on_network_exception(self):
        api = _mk_api()
        api.session.get.side_effect = Exception("timeout")
        result = api.get_inbound_clients_uk1(2)
        self.assertIsNone(result)

    def test_returns_none_when_settings_is_string(self):
        api = _mk_api()
        r = MagicMock()
        r.status_code = 200
        r.headers = {"Content-Type": "application/json"}
        r.json.return_value = {
            "success": True,
            "obj": [{"id": 2, "settings": json.dumps({"clients": []})}],
        }
        api.session.get.return_value = r
        result = api.get_inbound_clients_uk1(2)
        self.assertIsNone(result)

    def test_returns_none_when_inbound_not_found(self):
        api = _mk_api()
        r = MagicMock()
        r.status_code = 200
        r.headers = {"Content-Type": "application/json"}
        r.json.return_value = {"success": True, "obj": []}
        api.session.get.return_value = r
        result = api.get_inbound_clients_uk1(2)
        self.assertIsNone(result)


# ── 2. ensure_client_uk1: CREATE path ────────────────────────────────────────

class TestEnsureClientUk1Create(unittest.TestCase):

    def _setup(self, clients):
        api = _mk_api()
        api.session.get.return_value = _list_resp(clients)
        return api

    def test_new_uuid_calls_clients_add(self):
        """New UUID absent from panel → POST clients/add → CREATED."""
        api = self._setup([])
        api.session.post.return_value = _ok_resp("Inbound client(s) have been added.")

        result = api.ensure_client_uk1(2, UUID_A, EMAIL_A, expiry_time=9999000)

        self.assertEqual(result, EnsureResult.CREATED)
        call_url = api.session.post.call_args[0][0]
        self.assertIn("clients/add", call_url)
        body = api.session.post.call_args[1].get("json") or api.session.post.call_args[0][1]
        self.assertEqual(body["client"]["id"], UUID_A)
        self.assertEqual(body["client"]["uuid"], UUID_A)
        self.assertEqual(body["client"]["email"], EMAIL_A)
        self.assertIn(2, body["inboundIds"])

    def test_create_failure_returns_failed(self):
        """POST clients/add returns success=false → FAILED."""
        api = self._setup([])
        api.session.post.return_value = _fail_resp("duplicate email")

        result = api.ensure_client_uk1(2, UUID_A, EMAIL_A)

        self.assertEqual(result, EnsureResult.FAILED)

    def test_create_exception_returns_failed(self):
        """Network error during add → FAILED."""
        api = self._setup([])
        api.session.post.side_effect = Exception("timeout")

        result = api.ensure_client_uk1(2, UUID_A, EMAIL_A)

        self.assertEqual(result, EnsureResult.FAILED)

    def test_email_conflict_returns_conflict(self):
        """UUID absent but email taken by another UUID → CONFLICT."""
        existing = [{"id": UUID_B, "email": EMAIL_A}]
        api = self._setup(existing)

        result = api.ensure_client_uk1(2, UUID_A, EMAIL_A)

        self.assertEqual(result, EnsureResult.CONFLICT)
        api.session.post.assert_not_called()


# ── 3. ensure_client_uk1: UPDATE path ────────────────────────────────────────

class TestEnsureClientUk1Update(unittest.TestCase):

    def _setup_existing(self, stored_email=EMAIL_A):
        api = _mk_api()
        api.session.get.return_value = _list_resp(
            [{"id": UUID_A, "email": stored_email}]
        )
        return api

    def test_existing_uuid_calls_clients_update(self):
        """UUID found in panel → POST clients/update/{email} → UPDATED."""
        api = self._setup_existing()
        api.session.post.return_value = _ok_resp("Inbound client has been updated.")

        result = api.ensure_client_uk1(2, UUID_A, EMAIL_A, expiry_time=9999000)

        self.assertEqual(result, EnsureResult.UPDATED)
        call_url = api.session.post.call_args[0][0]
        self.assertIn("clients/update", call_url)
        encoded = urllib.parse.quote(EMAIL_A, safe="")
        self.assertIn(encoded, call_url)

    def test_update_preserves_existing_panel_email(self):
        """UUID found with different email in panel → update uses panel email, not caller email."""
        stored_email = "tg_100_1001_legacy"
        api = self._setup_existing(stored_email)
        api.session.post.return_value = _ok_resp()

        api.ensure_client_uk1(2, UUID_A, EMAIL_A, expiry_time=9999000)

        call_url = api.session.post.call_args[0][0]
        encoded_stored = urllib.parse.quote(stored_email, safe="")
        self.assertIn(encoded_stored, call_url)

    def test_update_failure_returns_failed(self):
        """POST clients/update returns success=false → FAILED."""
        api = self._setup_existing()
        api.session.post.return_value = _fail_resp("not found")

        result = api.ensure_client_uk1(2, UUID_A, EMAIL_A, expiry_time=9999000)

        self.assertEqual(result, EnsureResult.FAILED)

    def test_update_exception_returns_failed(self):
        """Network error during update → FAILED."""
        api = self._setup_existing()
        api.session.post.side_effect = Exception("connection reset")

        result = api.ensure_client_uk1(2, UUID_A, EMAIL_A)

        self.assertEqual(result, EnsureResult.FAILED)

    def test_update_payload_has_both_id_and_uuid(self):
        """Both id and uuid fields set to the same UUID in update payload."""
        api = self._setup_existing()
        api.session.post.return_value = _ok_resp()

        api.ensure_client_uk1(2, UUID_A, EMAIL_A, expiry_time=5000)

        body = api.session.post.call_args[1].get("json") or api.session.post.call_args[0][1]
        self.assertEqual(body["id"], UUID_A)
        self.assertEqual(body["uuid"], UUID_A)


# ── 4. Read failure blocks all writes ────────────────────────────────────────

class TestEnsureClientUk1ReadFirst(unittest.TestCase):

    def test_read_failure_returns_failed_no_write(self):
        """If panel state cannot be read, return FAILED and never write."""
        api = _mk_api()
        api.session.get.side_effect = Exception("network error")

        result = api.ensure_client_uk1(2, UUID_A, EMAIL_A)

        self.assertEqual(result, EnsureResult.FAILED)
        api.session.post.assert_not_called()

    def test_read_none_returns_failed_no_write(self):
        """get_inbound_clients_uk1 returns None → FAILED, no write."""
        api = _mk_api()
        r = MagicMock()
        r.status_code = 200
        r.headers = {"Content-Type": "application/json"}
        r.json.return_value = {"success": False}
        api.session.get.return_value = r

        result = api.ensure_client_uk1(2, UUID_A, EMAIL_A)

        self.assertEqual(result, EnsureResult.FAILED)
        api.session.post.assert_not_called()


# ── 5. _server_sync_client routing ───────────────────────────────────────────

class TestServerSyncClientUk1Routing(unittest.TestCase):
    """_server_sync_client uses ensure_client_uk1 for xui_standard=False non-WS servers."""

    def _make_server(self, server_id, xui_standard, transport="xhttp"):
        srv = MagicMock()
        srv.id = server_id
        srv.name = server_id
        srv.xui_standard = xui_standard
        srv.transport = transport
        srv.inbound_id = 2
        srv.xui_ssl = False
        srv.xui_host = "127.0.0.1"
        srv.xui_port = 13226
        srv.xui_web_path = "/web"
        srv.xui_username = "admin"
        srv.xui_password = "pass"
        return srv

    def _call_sync(self, server_id, xui_standard, transport="xhttp"):
        from bot import _server_sync_client
        srv = self._make_server(server_id, xui_standard, transport)
        with patch("xui_api.XUIAPI") as MockAPI:
            instance = MockAPI.return_value
            instance.login.return_value = True
            instance.ensure_client_uk1.return_value = EnsureResult.CREATED
            instance.ensure_client.return_value = EnsureResult.CREATED
            result = _server_sync_client(srv, UUID_A, EMAIL_A, expiry_ms=9999000)
            return result, instance

    def test_uk1_xhttp_uses_ensure_client_uk1(self):
        """uk1-xhttp (xui_standard=False, transport=xhttp) → ensure_client_uk1."""
        result, api_inst = self._call_sync("uk1-xhttp", xui_standard=False)
        self.assertTrue(result)
        api_inst.ensure_client_uk1.assert_called_once()
        api_inst.ensure_client.assert_not_called()

    def test_us1_xhttp_uses_standard_ensure_client(self):
        """us1-xhttp (xui_standard=True) → standard ensure_client."""
        result, api_inst = self._call_sync("us1-xhttp", xui_standard=True)
        self.assertTrue(result)
        api_inst.ensure_client.assert_called_once()
        api_inst.ensure_client_uk1.assert_not_called()

    def test_fr1_uses_standard_ensure_client(self):
        """fr1 (xui_standard=True) → standard ensure_client."""
        result, api_inst = self._call_sync("fr1", xui_standard=True)
        self.assertTrue(result)
        api_inst.ensure_client.assert_called_once()
        api_inst.ensure_client_uk1.assert_not_called()

    def test_uk1_xhttp_login_failure_returns_false(self):
        """Login failure on uk1-xhttp → False, no ensure call."""
        from bot import _server_sync_client
        srv = self._make_server("uk1-xhttp", xui_standard=False)
        with patch("xui_api.XUIAPI") as MockAPI:
            instance = MockAPI.return_value
            instance.login.return_value = False
            result = _server_sync_client(srv, UUID_A, EMAIL_A)
        self.assertFalse(result)
        instance.ensure_client_uk1.assert_not_called()


# ── 6. USER_029 exclusion ────────────────────────────────────────────────────

class TestUser029ExclusionUk1(unittest.TestCase):

    def test_user_029_excluded_by_caller_not_adapter(self):
        """
        USER_029 exclusion is enforced at reconciliation loop level (not inside adapter).
        Verify ensure_client_uk1 itself does not filter by UUID — caller is responsible.
        """
        api = _mk_api()
        api.session.get.return_value = _list_resp([])
        api.session.post.return_value = _ok_resp()

        # The adapter processes any UUID given to it — caller must exclude USER_029
        result = api.ensure_client_uk1(2, UUID_B, EMAIL_B)
        self.assertEqual(result, EnsureResult.CREATED)


# ── 7. uk1 WS path unchanged ─────────────────────────────────────────────────

class TestUk1WsUnchanged(unittest.TestCase):

    def test_uk1_ws_uses_ws_manager_not_xui(self):
        """uk1 (transport=ws) goes through ws_manager.add_client, never touches XUI API."""
        from bot import _server_sync_client
        srv = MagicMock()
        srv.id = "uk1"
        srv.name = "uk1"
        srv.transport = "ws"
        srv.ws_host = "163.5.210.147"
        srv.ws_ssh_password = "pass"
        srv.ws_config_path = "/etc/xray-ws/config.json"
        srv.ws_ssh_key = "/root/.ssh/key"

        with patch("ws_manager.add_client", return_value=True) as mock_ws, \
             patch("bot.XUIAPI") as MockXUI:
            result = _server_sync_client(srv, UUID_A, EMAIL_A)

        self.assertTrue(result)
        mock_ws.assert_called_once()
        MockXUI.assert_not_called()


# ── 8. us2/us2-ws zero I/O ────────────────────────────────────────────────────

class TestUs2ZeroIoUk1Sprint(unittest.TestCase):

    def _assert_protected_returns_false(self, server_id):
        from bot import _server_sync_client
        srv = MagicMock()
        srv.id = server_id
        srv.name = server_id
        srv.transport = "xhttp"
        srv.xui_standard = False

        with patch("bot.XUIAPI") as MockXUI:
            result = _server_sync_client(srv, UUID_A, EMAIL_A)

        self.assertFalse(result)
        MockXUI.assert_not_called()

    def test_us2_blocked(self):
        self._assert_protected_returns_false("us2")

    def test_us2_ws_blocked(self):
        self._assert_protected_returns_false("us2-ws")


# ── 9. Subscription UUID/link semantics unchanged ─────────────────────────────

class TestVlessLinkUnchangedUk1(unittest.TestCase):

    def test_ensure_client_uk1_passes_caller_uuid_to_panel(self):
        """The UUID used in the panel matches the UUID from DB — VLESS link stays valid."""
        api = _mk_api()
        api.session.get.return_value = _list_resp([])
        api.session.post.return_value = _ok_resp()

        desired_uuid = "deadbeef-cafe-babe-0000-000000000099"
        api.ensure_client_uk1(2, desired_uuid, EMAIL_A, expiry_time=9999000)

        body = api.session.post.call_args[1].get("json") or api.session.post.call_args[0][1]
        self.assertEqual(body["client"]["id"], desired_uuid)
        self.assertEqual(body["client"]["uuid"], desired_uuid)


if __name__ == "__main__":
    unittest.main()
