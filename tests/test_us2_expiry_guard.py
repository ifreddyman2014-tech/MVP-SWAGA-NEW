"""
TDD tests for US2/US2-WS expiry/revocation guard (P0-US2 EXPIRY GUARD).

Tests A-G are RED on unpatched bot.py (no guard in _delete_client_from_all_servers).
After implementation all tests must be GREEN.

Protected servers: us2, us2-ws
Invariant: _delete_client_from_all_servers() must NEVER call
           _server_delete_client() for a protected server ID.
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

# ── bootstrap: stub heavy deps before importing bot ─────────────────────────

os.environ.setdefault("BOT_TOKEN", "123456789:AAHs-FakeTestTokenForUnitTests_abc0")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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

_original_db_path = _config.DB_PATH  # save before overwriting

_TEMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TEMP_DB.close()
_config.DB_PATH = _TEMP_DB.name

import database as _db  # imported by bot at module level
import bot as _bot

_config.DB_PATH = _original_db_path  # restore so other test modules see their own DB path
from servers import ServerManager, VPNServer


# ── helpers ──────────────────────────────────────────────────────────────────

def _srv(server_id: str, enabled: bool = True, transport: str = "tcp") -> VPNServer:
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
    )


def _mgr(*server_ids: str, **kwargs) -> ServerManager:
    mgr = ServerManager()
    for sid in server_ids:
        mgr.servers[sid] = _srv(sid, **kwargs)
    return mgr


def _run_delete(mgr: ServerManager, uuid: str = "test-uuid") -> list[str]:
    """
    Call _delete_client_from_all_servers with a spy on _server_delete_client.
    Returns list of server IDs that the spy was invoked for.
    """
    called_for: list[str] = []

    def spy(server, uid: str) -> bool:
        called_for.append(server.id)
        return True

    with mock.patch.object(_bot, "_server_delete_client", side_effect=spy), \
         mock.patch("servers.server_manager", mgr):
        _bot._delete_client_from_all_servers(uuid, inbound_id_fallback=1)

    return called_for


# ── tests ─────────────────────────────────────────────────────────────────────

class TestUS2ExpiryGuard(unittest.TestCase):

    # ── TEST A ────────────────────────────────────────────────────────────────

    def test_a_delete_all_skips_protected_servers(self):
        """
        _delete_client_from_all_servers() must not call _server_delete_client
        for us2/us2-ws when mixed with normal servers.

        RED on unpatched code: the loop iterates ALL enabled servers and calls
        _server_delete_client for each, including protected ones.
        """
        mgr = _mgr("fr1", "us1", "uk1", "us2", "us2-ws")
        called_for = _run_delete(mgr)

        self.assertNotIn(
            "us2", called_for,
            "_server_delete_client must not be called for protected server us2",
        )
        self.assertNotIn(
            "us2-ws", called_for,
            "_server_delete_client must not be called for protected server us2-ws",
        )
        # Normal servers must still be deleted
        self.assertIn("fr1", called_for)
        self.assertIn("us1", called_for)
        self.assertIn("uk1", called_for)

    # ── TEST B ────────────────────────────────────────────────────────────────

    def test_b_protected_enabled_true_still_skipped(self):
        """
        Protected server with enabled=True must still be skipped.

        The guard must be based on server.id, NOT on server.enabled.
        RED on unpatched code: enabled=True means the server enters the loop.
        """
        mgr = _mgr("fr1", "us2")  # us2 is enabled=True by default in _srv()
        self.assertTrue(mgr.servers["us2"].enabled, "precondition: us2 is enabled")

        called_for = _run_delete(mgr)

        self.assertNotIn(
            "us2", called_for,
            "us2 with enabled=True must still be skipped — guard based on ID, not enabled flag",
        )
        self.assertIn("fr1", called_for)

    # ── TEST C ────────────────────────────────────────────────────────────────

    def test_c_normal_servers_still_deleted(self):
        """
        Guard must not break normal server revocation.
        fr1, us1, uk1 must receive _server_delete_client calls.

        Regression test — passes on both patched and unpatched code.
        """
        mgr = _mgr("fr1", "us1", "uk1")
        called_for = _run_delete(mgr)

        self.assertIn("fr1", called_for)
        self.assertIn("us1", called_for)
        self.assertIn("uk1", called_for)

    # ── TEST D ────────────────────────────────────────────────────────────────

    def test_d_skip_is_before_lower_level_helper(self):
        """
        The guard must skip protected servers BEFORE calling _server_delete_client.
        The lower-level helper (_server_delete_client) must never receive a
        protected server object.

        RED on unpatched code: no guard → helper called for all servers.
        """
        mgr = _mgr("fr1", "us2", "us2-ws")
        received_servers: list[str] = []

        def spy(server, uuid: str) -> bool:
            received_servers.append(server.id)
            return True

        with mock.patch.object(_bot, "_server_delete_client", side_effect=spy), \
             mock.patch("servers.server_manager", mgr):
            _bot._delete_client_from_all_servers("uuid-d", inbound_id_fallback=1)

        self.assertNotIn(
            "us2", received_servers,
            "_server_delete_client received protected server us2 — guard fires too late or missing",
        )
        self.assertNotIn(
            "us2-ws", received_servers,
            "_server_delete_client received protected server us2-ws — guard missing",
        )
        self.assertIn("fr1", received_servers)

    # ── TEST E ────────────────────────────────────────────────────────────────

    def test_e_scheduler_expiry_path_normal_delete_no_protected(self):
        """
        Simulate the path used by _scheduler_expiration_check:
          expired UUID → _delete_client_from_all_servers → skip protected

        The scheduler calls _delete_client_from_all_servers for each expired sub.
        Normal servers must be revoked; protected servers must be skipped.
        """
        mgr = _mgr("fr1", "us1", "uk1", "us2", "us2-ws")
        called_for = _run_delete(mgr, uuid="expiry-sub-uuid-001")

        # Simulates what happens at midnight when a subscription expires
        self.assertNotIn(
            "us2", called_for,
            "Expiry scheduler path must not contact us2",
        )
        self.assertNotIn(
            "us2-ws", called_for,
            "Expiry scheduler path must not contact us2-ws",
        )
        self.assertIn("fr1", called_for)
        self.assertIn("us1", called_for)

    # ── TEST F ────────────────────────────────────────────────────────────────

    def test_f_multiple_expired_uuids_protected_never_called(self):
        """
        When _delete_client_from_all_servers is called for multiple UUIDs
        (as happens when several subscriptions expire at once), protected
        servers must be skipped for ALL of them.

        RED on unpatched code: protected servers called for each UUID.
        """
        mgr = _mgr("fr1", "us1", "uk1", "us2", "us2-ws")
        all_called: list[str] = []

        def spy(server, uuid: str) -> bool:
            all_called.append(server.id)
            return True

        uuids = ["uuid-alpha", "uuid-beta", "uuid-gamma"]
        with mock.patch.object(_bot, "_server_delete_client", side_effect=spy), \
             mock.patch("servers.server_manager", mgr):
            for uuid in uuids:
                _bot._delete_client_from_all_servers(uuid, inbound_id_fallback=1)

        protected_calls = [s for s in all_called if s in ("us2", "us2-ws")]
        self.assertEqual(
            protected_calls, [],
            f"Protected servers were called for some UUID(s): {protected_calls}",
        )
        # fr1 must have been called once per UUID
        fr1_calls = all_called.count("fr1")
        self.assertEqual(fr1_calls, len(uuids),
            f"fr1 should be called once per UUID ({len(uuids)}), got {fr1_calls}")

    # ── TEST G ────────────────────────────────────────────────────────────────

    def test_g_us2ws_specifically_skipped(self):
        """
        us2-ws (WS transport variant) must also be skipped.

        RED on unpatched code: all servers including ws variants receive
        _server_delete_client calls (which for ws uses SSH, not XUI API).
        """
        mgr = _mgr("fr1", "us2-ws")
        called_for = _run_delete(mgr)

        self.assertNotIn(
            "us2-ws", called_for,
            "us2-ws (WS transport) must be skipped — SSH network call must not occur",
        )
        self.assertIn("fr1", called_for)


if __name__ == "__main__":
    unittest.main()
