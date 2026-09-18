"""
H0 — Protected Server Containment: TDD policy tests.

Protected servers: us2, us2-ws  (PROTECTED_SERVER_IDS in servers.py)

Invariants enforced by this release:
  1. SELECTION  — get_best_server() never returns a protected server
  2. PROVISION  — _server_add_client() never touches XUIAPI/ws_manager for protected IDs
  3. OUTPUT     — /sub/ and /connect/ endpoints exclude protected server configs

Tests A-D:  Selection (servers.py)    — RED on unpatched get_best_server()
Tests E-G:  Provision guard (bot.py)  — RED on unpatched _server_add_client()
Tests H-I:  Output filter (sub_app.py) — RED on unpatched handle_subscription / handle_connect

Implementation guide:
  servers.py : add `s.id not in PROTECTED_SERVER_IDS` to get_best_server() eligible filter
  bot.py     : add guard at top of _server_add_client() returning False before any I/O
  sub_app.py : add `and s.id not in PROTECTED_SERVER_IDS` to both enabled_servers filters
"""

import asyncio
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── bootstrap: stub heavy deps before importing bot ──────────────────────────

os.environ.setdefault("BOT_TOKEN", "123456789:AAHs-FakeTestTokenForUnitTests_H0x")

_aiomock = mock.MagicMock()
for _m in [
    "aiogram",
    "aiogram.types",
    "aiogram.utils",
    "aiogram.utils.executor",
    "aiogram.dispatcher",
    "aiogram.dispatcher.filters",
]:
    sys.modules.setdefault(_m, _aiomock)

import config as _config

_original_db_path = _config.DB_PATH
_TEMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TEMP_DB.close()
_config.DB_PATH = _TEMP_DB.name

import database as _db
import bot as _bot

_config.DB_PATH = _original_db_path

from servers import PROTECTED_SERVER_IDS, ServerManager, VPNServer


# ── helpers ──────────────────────────────────────────────────────────────────

def _srv(server_id: str, *, enabled: bool = True, transport: str = "tcp",
         priority: int = 10, current_users: int = 0, max_users: int = 100) -> VPNServer:
    return VPNServer(
        id=server_id,
        name=f"Test {server_id}",
        host="10.0.0.1",
        xui_host="10.0.0.1",
        xui_port=2053,
        xui_web_path="/panel",
        xui_username="admin",
        xui_password="pass",
        enabled=enabled,
        transport=transport,
        priority=priority,
        current_users=current_users,
        max_users=max_users,
    )


def _mgr(*server_ids: str, **kw) -> ServerManager:
    mgr = ServerManager()
    for sid in server_ids:
        mgr.servers[sid] = _srv(sid, **kw)
    return mgr


def _run(coro):
    return asyncio.run(coro)


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 1: SELECTION — servers.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestProtectedServerSelection(unittest.TestCase):
    """get_best_server() must never return a protected server."""

    def test_a_us2_not_selected_despite_highest_priority(self):
        """
        us2 (priority=10, 0% load) must never win selection over fr1 (priority=5, 50% load).

        RED: get_best_server() sorts by (-priority, load_ratio).
        us2 priority=10 > fr1 priority=5 → us2 is first in sort → returned.
        Expected (GREEN): us2 excluded before sort; fr1 returned.
        """
        mgr = _mgr("fr1", "us2")
        mgr.servers["fr1"].priority = 5
        mgr.servers["fr1"].current_users = 50   # 50% load
        mgr.servers["us2"].priority = 10
        mgr.servers["us2"].current_users = 0    # 0% load

        result = mgr.get_best_server()

        self.assertIsNotNone(result, "get_best_server() must return a server when fr1 is available")
        self.assertNotIn(
            result.id, PROTECTED_SERVER_IDS,
            f"get_best_server() returned protected server '{result.id}' — "
            "protected servers must never be selected for new users",
        )

    def test_b_us2_ws_not_selected_despite_highest_priority(self):
        """
        us2-ws (priority=10, 0% load) must never be selected over uk1 (priority=3).

        RED: same sort logic — us2-ws wins.
        Expected (GREEN): us2-ws excluded; uk1 returned.
        """
        mgr = _mgr("uk1", "us2-ws")
        mgr.servers["uk1"].priority = 3
        mgr.servers["uk1"].current_users = 20
        mgr.servers["us2-ws"].priority = 10
        mgr.servers["us2-ws"].current_users = 0

        result = mgr.get_best_server()

        self.assertIsNotNone(result)
        self.assertNotIn(
            result.id, PROTECTED_SERVER_IDS,
            f"get_best_server() returned protected server '{result.id}'",
        )

    def test_c_only_protected_servers_returns_none(self):
        """
        If only protected servers exist, get_best_server() must return None.

        RED: currently returns us2 (it IS available and enabled).
        Expected (GREEN): all protected → no eligible → None.
        """
        mgr = _mgr("us2", "us2-ws")
        result = mgr.get_best_server()

        self.assertIsNone(
            result,
            "get_best_server() must return None when all available servers are protected — "
            f"got '{result.id if result else None}'",
        )

    def test_d_selects_best_unprotected_when_multiple_available(self):
        """
        With fr1, us1, uk1, us2, us2-ws all enabled, result must be one of the non-protected ones.

        RED: us2 (priority=10, 0% load) beats fr1/us1/uk1 (all priority=5) → us2 returned.
        Expected (GREEN): us2 excluded; best of fr1/us1/uk1 returned.
        """
        mgr = _mgr("fr1", "us1", "uk1", "us2", "us2-ws")
        for sid in ("fr1", "us1", "uk1"):
            mgr.servers[sid].priority = 5
            mgr.servers[sid].current_users = 10
        mgr.servers["us2"].priority = 10
        mgr.servers["us2"].current_users = 0
        mgr.servers["us2-ws"].priority = 10
        mgr.servers["us2-ws"].current_users = 0

        result = mgr.get_best_server()

        self.assertIsNotNone(result)
        self.assertIn(result.id, {"fr1", "us1", "uk1"},
                      f"Expected a non-protected server; got '{result.id}'")
        self.assertNotIn(result.id, PROTECTED_SERVER_IDS)


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 2: PROVISION GUARD — bot.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestProtectedServerProvisionGuard(unittest.TestCase):
    """_server_add_client() must return False before any I/O for protected servers."""

    def test_e_provision_guard_xui_server_no_xuiapi_touch(self):
        """
        _server_add_client(us2, ...) must return False.
        XUIAPI must never be instantiated.

        RED: no guard → code reaches `srv_xui = XUIAPI()` → xui_instantiated records it
             → assertEqual(0) fails.
        Expected (GREEN): guard returns False before XUIAPI() call → xui_instantiated stays empty.
        """
        server = _srv("us2", transport="tcp")
        xui_instantiated: list[str] = []

        class _TrackingXUI:
            def __init__(self):
                xui_instantiated.append("us2")
            base_url = ""
            def login(self, u, p): return True
            def add_client(self, *a, **kw): return True

        with mock.patch("xui_api.XUIAPI", _TrackingXUI):
            result = _bot._server_add_client(
                server, "test-uuid-h0", "test-h0@test.com",
            )

        self.assertFalse(
            result,
            "_server_add_client must return False for protected server us2",
        )
        self.assertEqual(
            len(xui_instantiated), 0,
            f"XUIAPI was instantiated for protected server us2 — "
            f"network call would have been made. Calls: {xui_instantiated}",
        )

    def test_f_provision_guard_ws_server_no_ws_manager_touch(self):
        """
        _server_add_client(us2-ws, ...) must return False.
        ws_manager.add_client must never be called.

        RED: no guard → code reaches `ws_manager.add_client(...)` → ws_called records it.
        Expected (GREEN): guard returns False before ws_manager call.
        """
        server = _srv("us2-ws", transport="ws")
        ws_called: list[str] = []

        def _fake_ws_add(host, password, config_path, uuid, email, **kw):
            ws_called.append(f"us2-ws:{uuid}")
            return True

        with mock.patch("ws_manager.add_client", _fake_ws_add):
            result = _bot._server_add_client(
                server, "test-uuid-h0-ws", "test-ws@test.com",
            )

        self.assertFalse(
            result,
            "_server_add_client must return False for protected server us2-ws",
        )
        self.assertEqual(
            len(ws_called), 0,
            f"ws_manager.add_client was called for protected server us2-ws. Calls: {ws_called}",
        )

    def test_g_normal_server_still_reaches_network(self):
        """
        Non-protected server fr1 must still attempt XUI login (regression).
        This test is GREEN on both patched and unpatched code.
        """
        server = _srv("fr1", transport="tcp")
        login_called: list[str] = []

        class _TrackingXUI:
            def __init__(self):
                pass
            base_url = ""
            def login(self, u, p):
                login_called.append("fr1")
                return False  # auth failure → _server_add_client returns False
            def add_client(self, *a, **kw): return True

        with mock.patch("xui_api.XUIAPI", _TrackingXUI):
            _bot._server_add_client(server, "test-uuid-fr1", "test-fr1@test.com")

        self.assertGreater(
            len(login_called), 0,
            "XUI login must still be attempted for non-protected server fr1",
        )

    def test_h_provision_guard_us2_xui_transport_no_io(self):
        """
        _server_add_client with us2 as xui transport must return False without XUIAPI touch.
        RED: unpatched code constructs XUIAPI, records in xui_instantiated → assertEqual(0) fails.
        """
        server = _srv("us2", transport="tcp")
        xui_instantiated: list[str] = []

        class _TrackingXUI:
            def __init__(self):
                xui_instantiated.append("us2-xui")
            base_url = ""
            def login(self, u, p): return True
            def add_client(self, *a, **kw): return True

        with mock.patch("xui_api.XUIAPI", _TrackingXUI):
            result = _bot._server_add_client(server, "uuid-us2-h", "us2h@test.com")

        self.assertFalse(result)
        self.assertEqual(
            len(xui_instantiated), 0,
            f"XUIAPI instantiated for us2 — network I/O triggered: {xui_instantiated}",
        )

    def test_h_provision_guard_us2_ws_transport_no_io(self):
        """
        _server_add_client with us2-ws as ws transport must return False without ws_manager touch.
        RED: unpatched code calls ws_manager.add_client, records in ws_called → assertEqual(0) fails.
        """
        server = _srv("us2-ws", transport="ws")
        ws_called: list[str] = []

        def _fake_ws_add(host, password, config_path, uuid, email, **kw):
            ws_called.append("us2-ws")
            return True

        with mock.patch("ws_manager.add_client", _fake_ws_add):
            result = _bot._server_add_client(server, "uuid-us2-ws-h", "us2wsh@test.com")

        self.assertFalse(result)
        self.assertEqual(
            len(ws_called), 0,
            f"ws_manager.add_client called for us2-ws: {ws_called}",
        )


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 3: OUTPUT FILTER — sub_app.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestProtectedServerOutputFilter(unittest.TestCase):
    """
    handle_subscription and handle_connect must not include protected server configs.

    Strategy: patch server_manager.get_all_servers() and get_sub_by_xui_id,
    then verify the server list used by the handler excludes protected IDs.
    We test the filter expression used by both handlers:
        enabled_servers = [s for s in server_manager.get_all_servers() if s.enabled]
    This should become:
        enabled_servers = [s for s in server_manager.get_all_servers()
                           if s.enabled and s.id not in PROTECTED_SERVER_IDS]
    """

    def _mixed_servers(self):
        """Return [fr1, us1, us2, us2-ws] — all enabled."""
        return [_srv("fr1"), _srv("us1"), _srv("us2"), _srv("us2-ws")]

    def _enabled_filter(self, servers):
        """Replicate the CURRENT (unpatched) filter used in both handlers."""
        return [s for s in servers if s.enabled]

    def _policy_filter(self, servers):
        """Replicate the DESIRED (patched) filter — what the fix should produce."""
        return [s for s in servers if s.enabled and s.id not in PROTECTED_SERVER_IDS]

    def test_i_current_filter_exposes_protected_servers(self):
        """
        Document the bug: the current filter includes us2/us2-ws.
        This test PASSES on unpatched code, confirming the vulnerability exists.
        Used to verify our understanding before writing RED tests below.
        """
        servers = self._mixed_servers()
        current_result = self._enabled_filter(servers)
        current_ids = {s.id for s in current_result}

        # Bug is present: us2 and us2-ws appear in current filter output
        self.assertIn("us2", current_ids,
                      "Precondition: current filter includes us2 (confirming bug exists)")
        self.assertIn("us2-ws", current_ids,
                      "Precondition: current filter includes us2-ws (confirming bug exists)")

    def test_j_sub_handler_enabled_servers_excludes_protected(self):
        """
        handle_subscription's enabled_servers must not request config for protected servers.

        RED: the current filter `[s for s in get_all_servers() if s.enabled]`
             includes us2/us2-ws → get_server_config("us2") IS called → assertNotIn fails.
        Expected (GREEN): filter adds `and s.id not in PROTECTED_SERVER_IDS`
                          → get_server_config("us2") never called.
        """
        import sub_app as _sub

        all_servers = self._mixed_servers()
        config_requested_for: list[str] = []
        _original_cfg = _sub.get_server_config

        def _spy_get_config(sid):
            config_requested_for.append(sid)
            return _original_cfg(sid)

        async def _fake_get_sub(sub_id):
            return {
                "sub_id": sub_id, "vless_uuid": "test-uuid-j",
                "is_active": True, "end_date": "2027-01-01",
                "user_id": 1, "server_id": "fr1",
            }

        with mock.patch.object(ServerManager, "get_all_servers", lambda self_inner: all_servers), \
             mock.patch("sub_app.get_sub_by_xui_id", _fake_get_sub), \
             mock.patch("sub_app.get_server_config", _spy_get_config), \
             mock.patch("sub_app.server_manager.servers", {s.id: s for s in all_servers}):

            from aiohttp.test_utils import make_mocked_request
            request = make_mocked_request("GET", "/sub/test-sub-j",
                                          match_info={"sub_id": "test-sub-j"})
            _run(_sub.handle_subscription(request))

        for protected_id in PROTECTED_SERVER_IDS:
            self.assertNotIn(
                protected_id, config_requested_for,
                f"get_server_config('{protected_id}') was called inside /sub/ handler — "
                f"protected server was included in subscription output. "
                f"All config requests: {config_requested_for}",
            )

    def test_k_connect_handler_enabled_servers_excludes_protected(self):
        """
        handle_connect's enabled_servers must not request config for protected servers.

        RED: same filter bug — get_server_config("us2") IS called.
        Expected (GREEN): protected IDs excluded before get_server_config is called.
        """
        import sub_app as _sub

        all_servers = self._mixed_servers()
        config_requested_for: list[str] = []
        _original_cfg = _sub.get_server_config

        def _spy_get_config(sid):
            config_requested_for.append(sid)
            return _original_cfg(sid)

        async def _fake_get_sub(sub_id):
            return {
                "sub_id": sub_id, "vless_uuid": "test-uuid-k",
                "is_active": True, "end_date": "2027-01-01",
                "user_id": 1, "server_id": "fr1",
            }

        with mock.patch.object(ServerManager, "get_all_servers", lambda self_inner: all_servers), \
             mock.patch("sub_app.get_sub_by_xui_id", _fake_get_sub), \
             mock.patch("sub_app.get_server_config", _spy_get_config), \
             mock.patch("sub_app.server_manager.servers", {s.id: s for s in all_servers}):

            from aiohttp.test_utils import make_mocked_request
            request = make_mocked_request("GET", "/connect/test-sub-k",
                                          match_info={"sub_id": "test-sub-k"})
            _run(_sub.handle_connect(request))

        for protected_id in PROTECTED_SERVER_IDS:
            self.assertNotIn(
                protected_id, config_requested_for,
                f"get_server_config('{protected_id}') was called inside /connect/ handler — "
                f"protected server was included in user-facing output. "
                f"All config requests: {config_requested_for}",
            )


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 4: POLICY REGRESSION — canonical set is the single source of truth
# ═══════════════════════════════════════════════════════════════════════════════

class TestProtectedServerPolicyRegression(unittest.TestCase):
    """
    Verify that the canonical PROTECTED_SERVER_IDS from servers.py is the
    single source of truth and that no duplicate local set exists in bot.py.
    """

    def test_l_canonical_set_contains_us2_and_us2_ws(self):
        """servers.PROTECTED_SERVER_IDS must contain us2 and us2-ws."""
        self.assertIn("us2", PROTECTED_SERVER_IDS)
        self.assertIn("us2-ws", PROTECTED_SERVER_IDS)

    def test_m_bot_does_not_define_local_duplicate(self):
        """
        bot.py must not define its own _PROTECTED_SERVER_IDS duplicate set.

        RED: bot.py line 95 defines `_PROTECTED_SERVER_IDS = {"us2", "us2-ws"}`.
        Expected (GREEN): attribute removed; bot imports PROTECTED_SERVER_IDS from servers.
        """
        self.assertFalse(
            hasattr(_bot, "_PROTECTED_SERVER_IDS"),
            "bot._PROTECTED_SERVER_IDS local duplicate must be removed — "
            "use `from servers import PROTECTED_SERVER_IDS` instead",
        )

    def test_n_bot_uses_canonical_set_from_servers(self):
        """
        bot.PROTECTED_SERVER_IDS must be the same object as servers.PROTECTED_SERVER_IDS.

        RED: bot currently has its own _PROTECTED_SERVER_IDS, no canonical import.
        Expected (GREEN): bot re-exports the canonical frozenset.
        """
        self.assertTrue(
            hasattr(_bot, "PROTECTED_SERVER_IDS"),
            "bot must import and expose PROTECTED_SERVER_IDS from servers module",
        )
        self.assertIs(
            _bot.PROTECTED_SERVER_IDS, PROTECTED_SERVER_IDS,
            "bot.PROTECTED_SERVER_IDS must be the same object as servers.PROTECTED_SERVER_IDS",
        )

    def test_o_health_check_loop_still_skips_protected(self):
        """
        Regression: check_all_servers() must still exclude protected IDs.
        This guard existed before H0 — must not be broken by our changes.
        """
        health_checked: list[str] = []

        async def _fake_check(self_inner, server):
            health_checked.append(server.id)
            return True

        mgr = _mgr("fr1", "us1", "us2", "us2-ws")

        with mock.patch.object(ServerManager, "check_server_health", _fake_check):
            _run(mgr.check_all_servers())

        self.assertNotIn("us2", health_checked,
                         "check_all_servers() must never send health request to us2")
        self.assertNotIn("us2-ws", health_checked,
                         "check_all_servers() must never send health request to us2-ws")
        self.assertIn("fr1", health_checked)
        self.assertIn("us1", health_checked)


if __name__ == "__main__":
    unittest.main()
