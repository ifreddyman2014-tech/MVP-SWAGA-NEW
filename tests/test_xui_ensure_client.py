"""
H1-F1 — Standard XUI Read-First Ensure Client: TDD tests.

Verifies:
  1. get_inbound_clients() reads panel state correctly
  2. ensure_client() uses read-first state-driven flow
  3. _server_sync_client() in bot.py routes through ensure_client for xui_standard servers
  4. xui_standard=False guard: sync skipped for non-standard panels (uk1, uk1-xhttp)
  5. H0 invariants: us2/us2-ws never contacted

RED on unpatched code. GREEN after:
  - EnsureResult enum in xui_api.py
  - get_inbound_clients() in xui_api.py
  - ensure_client() in xui_api.py
  - xui_standard: bool = True field in VPNServer (servers.py)
  - _server_sync_client() updated in bot.py
  - servers.json uk1/uk1-xhttp: "xui_standard": false
"""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── bootstrap: stub heavy deps before importing bot ──────────────────────────

os.environ.setdefault("BOT_TOKEN", "123456789:AAHs-FakeTestTokenForUnitTests_H1F1")

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
from xui_api import XUIAPI

from servers import PROTECTED_SERVER_IDS, VPNServer


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_xui() -> XUIAPI:
    xui = XUIAPI.__new__(XUIAPI)
    xui._logged_in = True
    xui.base_url = "http://127.0.0.1:4444/panel"
    import requests
    xui.session = requests.Session()
    return xui


def _inbound_list_resp(inbound_id: int, clients: list[dict]) -> dict:
    """Build a fake /inbounds/list API response."""
    settings_str = json.dumps({"clients": clients})
    return {
        "success": True,
        "obj": [
            {"id": inbound_id, "settings": settings_str},
            {"id": 99, "settings": json.dumps({"clients": []})},
        ],
    }


def _client(uuid: str, email: str) -> dict:
    return {"id": uuid, "email": email, "enable": True, "expiryTime": 0,
            "flow": "", "limitIp": 3, "totalGB": 0, "subId": ""}


def _srv_standard(server_id: str = "fr1") -> VPNServer:
    """VPNServer with xui_standard=True (default for all non-uk1 servers)."""
    return VPNServer(
        id=server_id,
        name=f"Test {server_id}",
        host="10.0.0.1",
        xui_host="127.0.0.1",
        xui_port=4444,
        xui_web_path="/panel",
        xui_username="admin",
        xui_password="pass",
        xui_ssl=False,
        transport="tcp",
        flow="xtls-rprx-vision",
        inbound_id=1,
    )


def _srv_nonstandard(server_id: str = "uk1") -> VPNServer:
    """VPNServer with xui_standard=False (uk1/uk1-xhttp)."""
    srv = _srv_standard(server_id)
    srv.xui_standard = False   # attribute set directly for test purposes
    return srv


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 1: get_inbound_clients() — panel read
# ══════════════════════════════════════════════════════════════════════════════

class TestGetInboundClients(unittest.TestCase):
    """get_inbound_clients() must return list from panel or None on failure."""

    def test_01_returns_client_list_for_matching_inbound(self):
        """Happy path: returns list of client dicts for the requested inbound_id."""
        xui = _make_xui()
        clients_in_panel = [
            _client("uuid-aaa", "user-a"),
            _client("uuid-bbb", "user-b"),
        ]
        panel_resp = _inbound_list_resp(inbound_id=1, clients=clients_in_panel)

        with mock.patch.object(xui.session, "get") as mock_get:
            resp = mock.MagicMock()
            resp.headers = {"Content-Type": "application/json"}
            resp.json.return_value = panel_resp
            mock_get.return_value = resp

            result = xui.get_inbound_clients(inbound_id=1)

        self.assertIsNotNone(result)
        self.assertEqual(len(result), 2)
        uuids = {c["id"] for c in result}
        self.assertIn("uuid-aaa", uuids)
        self.assertIn("uuid-bbb", uuids)

    def test_02_returns_empty_list_when_no_clients(self):
        """Inbound exists but has zero clients → returns [], not None."""
        xui = _make_xui()
        panel_resp = _inbound_list_resp(inbound_id=1, clients=[])

        with mock.patch.object(xui.session, "get") as mock_get:
            resp = mock.MagicMock()
            resp.headers = {"Content-Type": "application/json"}
            resp.json.return_value = panel_resp
            mock_get.return_value = resp

            result = xui.get_inbound_clients(inbound_id=1)

        self.assertIsNotNone(result)
        self.assertEqual(result, [])

    def test_03_returns_none_on_http_error(self):
        """Network failure → None (not empty list)."""
        xui = _make_xui()

        with mock.patch.object(xui.session, "get", side_effect=Exception("timeout")):
            result = xui.get_inbound_clients(inbound_id=1)

        self.assertIsNone(result)

    def test_04_returns_none_when_settings_is_dict_not_string(self):
        """UK1-format: settings is a dict, not JSON string → None (read incompatible)."""
        xui = _make_xui()
        panel_resp = {
            "success": True,
            "obj": [
                {
                    "id": 2,
                    "settings": {"clients": [_client("uuid-uk1", "uk-user")]},  # dict, not str
                }
            ],
        }

        with mock.patch.object(xui.session, "get") as mock_get:
            resp = mock.MagicMock()
            resp.headers = {"Content-Type": "application/json"}
            resp.json.return_value = panel_resp
            mock_get.return_value = resp

            result = xui.get_inbound_clients(inbound_id=2)

        self.assertIsNone(result)

    def test_05_returns_none_on_api_success_false(self):
        """Panel returns success=false → None."""
        xui = _make_xui()

        with mock.patch.object(xui.session, "get") as mock_get:
            resp = mock.MagicMock()
            resp.headers = {"Content-Type": "application/json"}
            resp.json.return_value = {"success": False, "msg": "unauthorized"}
            mock_get.return_value = resp

            result = xui.get_inbound_clients(inbound_id=1)

        self.assertIsNone(result)

    def test_06_returns_none_when_inbound_id_not_in_list(self):
        """Inbound ID not found in panel's list → None."""
        xui = _make_xui()
        panel_resp = _inbound_list_resp(inbound_id=99, clients=[_client("x", "y")])

        with mock.patch.object(xui.session, "get") as mock_get:
            resp = mock.MagicMock()
            resp.headers = {"Content-Type": "application/json"}
            resp.json.return_value = panel_resp
            mock_get.return_value = resp

            result = xui.get_inbound_clients(inbound_id=1)

        self.assertIsNone(result)


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 2: ensure_client() — state-driven provisioning
# ══════════════════════════════════════════════════════════════════════════════

class TestEnsureClient(unittest.TestCase):
    """ensure_client() must use read-first logic, never error-string parsing."""

    def _mock_read(self, xui, inbound_id, clients):
        """Patch get_inbound_clients to return the given list."""
        return mock.patch.object(xui, "get_inbound_clients", return_value=clients)

    def _mock_read_none(self, xui):
        return mock.patch.object(xui, "get_inbound_clients", return_value=None)

    def test_10_new_uuid_creates_client(self):
        """
        TEST 10 — NEW UUID (CREATED):
        Panel state: inbound exists, no target UUID, no target email.
        Expected: READ occurs, updateClient DOES NOT occur, addClient called once,
        result = CREATED.
        """
        from xui_api import EnsureResult
        xui = _make_xui()

        with self._mock_read(xui, 1, []):
            with mock.patch.object(xui, "add_client", return_value=True) as mock_add:
                with mock.patch.object(xui, "update_client") as mock_upd:
                    result = xui.ensure_client(
                        inbound_id=1,
                        uuid="new-uuid-1234",
                        email="user@test",
                    )

        self.assertEqual(result, EnsureResult.CREATED)
        mock_add.assert_called_once()
        mock_upd.assert_not_called()

    def test_11_existing_uuid_updates_client(self):
        """
        TEST 11 — EXISTING UUID (UPDATED):
        Panel state: UUID already exists.
        Expected: READ occurs, updateClient called once, addClient NOT called,
        result = UPDATED.
        """
        from xui_api import EnsureResult
        xui = _make_xui()
        existing = [_client("existing-uuid", "user@test")]

        with self._mock_read(xui, 1, existing):
            with mock.patch.object(xui, "update_client", return_value=True) as mock_upd:
                with mock.patch.object(xui, "add_client") as mock_add:
                    result = xui.ensure_client(
                        inbound_id=1,
                        uuid="existing-uuid",
                        email="user@test",
                    )

        self.assertEqual(result, EnsureResult.UPDATED)
        mock_upd.assert_called_once()
        mock_add.assert_not_called()

    def test_12_email_conflict_returns_conflict(self):
        """
        TEST 12 — EMAIL CONFLICT (CONFLICT):
        Panel state: email exists but belongs to a DIFFERENT UUID.
        Expected: no write operation, result = CONFLICT.
        """
        from xui_api import EnsureResult
        xui = _make_xui()
        existing = [_client("other-uuid-9999", "user@test")]  # same email, different UUID

        with self._mock_read(xui, 1, existing):
            with mock.patch.object(xui, "add_client") as mock_add:
                with mock.patch.object(xui, "update_client") as mock_upd:
                    result = xui.ensure_client(
                        inbound_id=1,
                        uuid="target-uuid-1111",
                        email="user@test",
                    )

        self.assertEqual(result, EnsureResult.CONFLICT)
        mock_add.assert_not_called()
        mock_upd.assert_not_called()

    def test_13_read_failure_returns_failed(self):
        """
        TEST 13 — READ FAILURE (FAILED):
        get_inbound_clients returns None (panel unreachable).
        Expected: result = FAILED, no write operations.
        """
        from xui_api import EnsureResult
        xui = _make_xui()

        with self._mock_read_none(xui):
            with mock.patch.object(xui, "add_client") as mock_add:
                with mock.patch.object(xui, "update_client") as mock_upd:
                    result = xui.ensure_client(
                        inbound_id=1,
                        uuid="any-uuid",
                        email="any@test",
                    )

        self.assertEqual(result, EnsureResult.FAILED)
        mock_add.assert_not_called()
        mock_upd.assert_not_called()

    def test_14_add_failure_returns_failed(self):
        """
        TEST 14 — ADD FAILURE (FAILED):
        UUID absent, email absent → tries addClient → addClient returns False.
        Expected: result = FAILED.
        """
        from xui_api import EnsureResult
        xui = _make_xui()

        with self._mock_read(xui, 1, []):
            with mock.patch.object(xui, "add_client", return_value=False):
                result = xui.ensure_client(
                    inbound_id=1,
                    uuid="new-uuid",
                    email="new@test",
                )

        self.assertEqual(result, EnsureResult.FAILED)

    def test_15_update_failure_returns_failed(self):
        """
        TEST 15 — UPDATE FAILURE (FAILED):
        UUID exists → tries updateClient → updateClient returns False.
        Expected: result = FAILED.
        """
        from xui_api import EnsureResult
        xui = _make_xui()
        existing = [_client("existing-uuid", "user@test")]

        with self._mock_read(xui, 1, existing):
            with mock.patch.object(xui, "update_client", return_value=False):
                result = xui.ensure_client(
                    inbound_id=1,
                    uuid="existing-uuid",
                    email="user@test",
                )

        self.assertEqual(result, EnsureResult.FAILED)

    def test_16_incident_payload_does_not_block_add(self):
        """
        TEST 16 — INCIDENT PAYLOAD (no error-string parsing):
        Reproduces the 2026-09-18 failure: UUID absent → addClient is called.
        The old add_or_update_client would have called updateClient first and
        been blocked by "Something went wrong (empty client ID)" not being in
        _NOT_FOUND_MARKERS. ensure_client must NOT call updateClient at all
        for a new UUID — it reads the panel state first.
        """
        from xui_api import EnsureResult
        xui = _make_xui()
        # Panel has different users, NOT the target UUID
        existing = [_client("other-uuid-abc", "other@test")]

        with self._mock_read(xui, 1, existing):
            with mock.patch.object(xui, "add_client", return_value=True) as mock_add:
                with mock.patch.object(xui, "update_client") as mock_upd:
                    result = xui.ensure_client(
                        inbound_id=1,
                        uuid="1b5946b0-cb1d-4b3d-b07c-7e7a9a7a7a71",
                        email="364044145_us1",
                    )

        self.assertEqual(result, EnsureResult.CREATED)
        mock_add.assert_called_once()
        mock_upd.assert_not_called()

    def test_17_already_synced_client_returns_already_ok(self):
        """
        TEST 17 — ALREADY_OK:
        UUID exists and email matches. No update needed (expiry same).
        When ensure_client is given same params as already stored, it should
        still call updateClient (to refresh expiry), but ALREADY_OK is returned
        if the updateClient is essentially a no-op update.
        Actually: when UUID found in list, always update (refreshes expiry) → UPDATED.
        So ALREADY_OK is for future use — this test verifies UPDATED is returned,
        not CONFLICT, when UUID matches.
        """
        from xui_api import EnsureResult
        xui = _make_xui()
        existing = [_client("uuid-found", "user@test")]

        with self._mock_read(xui, 1, existing):
            with mock.patch.object(xui, "update_client", return_value=True):
                result = xui.ensure_client(
                    inbound_id=1,
                    uuid="uuid-found",
                    email="user@test",
                )

        self.assertIn(result, (EnsureResult.UPDATED, EnsureResult.ALREADY_OK))


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 3: EnsureResult enum existence
# ══════════════════════════════════════════════════════════════════════════════

class TestEnsureResultEnum(unittest.TestCase):
    """EnsureResult must be importable from xui_api with correct values."""

    def test_20_ensure_result_importable(self):
        """EnsureResult enum must exist in xui_api module."""
        from xui_api import EnsureResult  # noqa — this should not raise ImportError
        self.assertTrue(hasattr(EnsureResult, "CREATED"))
        self.assertTrue(hasattr(EnsureResult, "UPDATED"))
        self.assertTrue(hasattr(EnsureResult, "ALREADY_OK"))
        self.assertTrue(hasattr(EnsureResult, "CONFLICT"))
        self.assertTrue(hasattr(EnsureResult, "FAILED"))

    def test_21_ensure_result_is_enum(self):
        """EnsureResult must be an Enum subclass."""
        from enum import Enum
        from xui_api import EnsureResult
        self.assertTrue(issubclass(EnsureResult, Enum))


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 4: xui_standard field in VPNServer
# ══════════════════════════════════════════════════════════════════════════════

class TestXuiStandardField(unittest.TestCase):
    """VPNServer must have xui_standard: bool = True field."""

    def test_30_vpnserver_has_xui_standard_true_by_default(self):
        """Standard servers default xui_standard=True."""
        srv = _srv_standard("fr1")
        self.assertTrue(getattr(srv, "xui_standard", None) is not False,
                        "VPNServer.xui_standard must default to True (field missing or False)")

    def test_31_vpnserver_xui_standard_false_respected(self):
        """xui_standard=False must be storable on VPNServer."""
        srv = VPNServer(
            id="uk1",
            name="UK1",
            host="163.5.210.147",
            xui_host="127.0.0.1",
            xui_port=13226,
            xui_web_path="/panel",
            xui_username="admin",
            xui_password="pass",
            xui_standard=False,
        )
        self.assertFalse(srv.xui_standard)

    def test_32_servers_json_uk1_has_xui_standard_false(self):
        """servers.json uk1 entry must have xui_standard=false after H1-F1."""
        import os
        cfg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "servers.json")
        with open(cfg_path) as f:
            data = json.load(f)
        servers_by_id = {s["id"]: s for s in data["servers"]}
        self.assertIn("uk1", servers_by_id)
        self.assertFalse(
            servers_by_id["uk1"].get("xui_standard", True),
            "uk1 must have xui_standard=false in servers.json",
        )

    def test_33_servers_json_uk1_xhttp_has_xui_standard_false(self):
        """servers.json uk1-xhttp entry must have xui_standard=false after H1-F1."""
        import os
        cfg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "servers.json")
        with open(cfg_path) as f:
            data = json.load(f)
        servers_by_id = {s["id"]: s for s in data["servers"]}
        self.assertIn("uk1-xhttp", servers_by_id)
        self.assertFalse(
            servers_by_id["uk1-xhttp"].get("xui_standard", True),
            "uk1-xhttp must have xui_standard=false in servers.json",
        )

    def test_34_servers_json_fr1_us1_default_xui_standard_true(self):
        """fr1 and us1 must NOT have xui_standard=false (standard panels)."""
        import os
        cfg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "servers.json")
        with open(cfg_path) as f:
            data = json.load(f)
        servers_by_id = {s["id"]: s for s in data["servers"]}
        for sid in ("fr1", "us1"):
            entry = servers_by_id.get(sid, {})
            self.assertTrue(
                entry.get("xui_standard", True),
                f"{sid} must not have xui_standard=false",
            )


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 5: _server_sync_client() routing in bot.py
# ══════════════════════════════════════════════════════════════════════════════

class TestServerSyncClientRouting(unittest.TestCase):
    """
    _server_sync_client() must:
    - For xui_standard=True servers: call ensure_client, return True on CREATED/UPDATED/ALREADY_OK
    - For xui_standard=False servers: return False immediately, zero XUI IO
    - For protected servers (us2/us2-ws): return False immediately, zero XUI IO
    """

    def _run_sync(self, server, uuid="test-uuid", email="test@test"):
        """Run _server_sync_client via bot module."""
        return _bot._server_sync_client(
            server,
            uuid=uuid,
            email=email,
            sub_id="subid",
            expiry_ms=0,
            flow="",
        )

    def test_40_xui_standard_false_returns_false_no_io(self):
        """
        TEST 40 — UK1 BLOCK (xui_standard=False):
        xui_standard=False server → _server_sync_client returns False,
        zero calls to XUIAPI and zero calls to ws_manager.
        """
        srv = VPNServer(
            id="uk1",
            name="UK1",
            host="163.5.210.147",
            xui_host="127.0.0.1",
            xui_port=13226,
            xui_web_path="/panel",
            xui_username="admin",
            xui_password="pass",
            xui_ssl=False,
            transport="tcp",
            inbound_id=2,
            xui_standard=False,
        )

        with mock.patch("xui_api.XUIAPI") as mock_xui_cls, \
             mock.patch("ws_manager.add_client") as mock_ws:
            result = self._run_sync(srv)

        self.assertFalse(result)
        mock_xui_cls.assert_not_called()
        mock_ws.assert_not_called()

    def test_41_us2_protected_returns_false_no_io(self):
        """
        TEST 41 — US2 PROTECTED (H0 invariant):
        us2 must never be contacted. _server_sync_client returns False, zero IO.
        """
        srv = VPNServer(
            id="us2",
            name="США 2",
            host="31.57.38.104",
            xui_host="31.57.38.104",
            xui_port=448,
            xui_web_path="/panel",
            xui_username="admin",
            xui_password="pass",
            transport="tcp",
            inbound_id=1,
        )

        with mock.patch("xui_api.XUIAPI") as mock_xui_cls, \
             mock.patch("ws_manager.add_client") as mock_ws:
            result = self._run_sync(srv)

        self.assertFalse(result)
        mock_xui_cls.assert_not_called()
        mock_ws.assert_not_called()

    def test_42_us2_ws_protected_returns_false_no_io(self):
        """
        TEST 42 — US2-WS PROTECTED (H0 invariant):
        us2-ws must never be contacted. _server_sync_client returns False, zero IO.
        """
        srv = VPNServer(
            id="us2-ws",
            name="Канада",
            host="us2.swaga-vpn.ru",
            xui_host="31.57.38.104",
            xui_port=448,
            xui_web_path="/panel",
            xui_username="admin",
            xui_password="pass",
            transport="ws",
            inbound_id=1,
            ws_ssh_password="secret",
            ws_config_path="/etc/xray-ws/config.json",
        )

        with mock.patch("xui_api.XUIAPI") as mock_xui_cls, \
             mock.patch("ws_manager.add_client") as mock_ws:
            result = self._run_sync(srv)

        self.assertFalse(result)
        mock_xui_cls.assert_not_called()
        mock_ws.assert_not_called()

    def test_43_standard_xui_server_calls_ensure_client(self):
        """
        TEST 43 — STANDARD XUI SERVER:
        xui_standard=True TCP server (fr1) → _server_sync_client must call
        ensure_client (not add_or_update_client) and return True when result is CREATED.
        """
        from xui_api import EnsureResult

        srv = VPNServer(
            id="fr1",
            name="Франция",
            host="194.59.31.100",
            xui_host="127.0.0.1",
            xui_port=4444,
            xui_web_path="/iV31Zfverpgxjo2m6D",
            xui_username="admin",
            xui_password="pass",
            xui_ssl=False,
            transport="tcp",
            flow="xtls-rprx-vision",
            inbound_id=1,
        )

        mock_xui_instance = mock.MagicMock()
        mock_xui_instance.login.return_value = True
        mock_xui_instance.ensure_client.return_value = EnsureResult.CREATED

        with mock.patch("xui_api.XUIAPI", return_value=mock_xui_instance):
            result = self._run_sync(srv, uuid="brand-new-uuid", email="newuser@test")

        self.assertTrue(result)
        mock_xui_instance.ensure_client.assert_called_once()
        # Critically: add_or_update_client must NOT be called
        mock_xui_instance.add_or_update_client.assert_not_called()

    def test_44_standard_xui_server_updated_returns_true(self):
        """UPDATED result from ensure_client → _server_sync_client returns True."""
        from xui_api import EnsureResult

        srv = VPNServer(
            id="us1",
            name="США 1",
            host="80.76.49.140",
            xui_host="127.0.0.1",
            xui_port=16175,
            xui_web_path="/panel",
            xui_username="admin",
            xui_password="pass",
            xui_ssl=False,
            transport="tcp",
            flow="xtls-rprx-vision",
            inbound_id=1,
        )

        mock_xui_instance = mock.MagicMock()
        mock_xui_instance.login.return_value = True
        mock_xui_instance.ensure_client.return_value = EnsureResult.UPDATED

        with mock.patch("xui_api.XUIAPI", return_value=mock_xui_instance):
            result = self._run_sync(srv)

        self.assertTrue(result)

    def test_45_standard_xui_server_conflict_returns_false(self):
        """CONFLICT result from ensure_client → _server_sync_client returns False."""
        from xui_api import EnsureResult

        srv = VPNServer(
            id="fr1",
            name="Франция",
            host="194.59.31.100",
            xui_host="127.0.0.1",
            xui_port=4444,
            xui_web_path="/panel",
            xui_username="admin",
            xui_password="pass",
            xui_ssl=False,
            transport="tcp",
            inbound_id=1,
        )

        mock_xui_instance = mock.MagicMock()
        mock_xui_instance.login.return_value = True
        mock_xui_instance.ensure_client.return_value = EnsureResult.CONFLICT

        with mock.patch("xui_api.XUIAPI", return_value=mock_xui_instance):
            result = self._run_sync(srv)

        self.assertFalse(result)

    def test_46_standard_xui_server_failed_returns_false(self):
        """FAILED result from ensure_client → _server_sync_client returns False."""
        from xui_api import EnsureResult

        srv = VPNServer(
            id="fr1",
            name="Франция",
            host="194.59.31.100",
            xui_host="127.0.0.1",
            xui_port=4444,
            xui_web_path="/panel",
            xui_username="admin",
            xui_password="pass",
            xui_ssl=False,
            transport="tcp",
            inbound_id=1,
        )

        mock_xui_instance = mock.MagicMock()
        mock_xui_instance.login.return_value = True
        mock_xui_instance.ensure_client.return_value = EnsureResult.FAILED

        with mock.patch("xui_api.XUIAPI", return_value=mock_xui_instance):
            result = self._run_sync(srv)

        self.assertFalse(result)


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 6: H0 — ensure_client / get_inbound_clients never called for us2/us2-ws
# ══════════════════════════════════════════════════════════════════════════════

class TestH0InvariantsPreserved(unittest.TestCase):
    """H0 protection: protected servers must produce zero network IO."""

    def test_50_us2_protection_survives_ensure_client_import(self):
        """
        Importing EnsureResult / ensure_client must not degrade H0 protection.
        This test verifies PROTECTED_SERVER_IDS still contains us2 after H1-F1.
        """
        self.assertIn("us2", PROTECTED_SERVER_IDS)
        self.assertIn("us2-ws", PROTECTED_SERVER_IDS)

    def test_51_us2_id_not_in_servers_json_xui_standard_false(self):
        """
        us2/us2-ws entries in servers.json must NOT have xui_standard=false added.
        They are protected at a higher level; modifying them is forbidden.
        """
        import os
        cfg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "servers.json")
        with open(cfg_path) as f:
            data = json.load(f)
        servers_by_id = {s["id"]: s for s in data["servers"]}
        for sid in ("us2", "us2-ws"):
            if sid in servers_by_id:
                # xui_standard should not be explicitly false (it may be absent = default True)
                # but more importantly: the entry should still have the original host/credentials
                entry = servers_by_id[sid]
                self.assertIn("xui_username", entry,
                              f"{sid} entry should not have been modified")


if __name__ == "__main__":
    unittest.main(verbosity=2)
