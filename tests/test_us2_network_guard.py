"""
TDD tests for US2/US2-WS network guard (P0-US2 NETWORK GUARD).

Tests A–G are RED on unpatched servers.py (no guard exists).
After implementation all tests must be GREEN.

Protected servers: us2, us2-ws
Invariant: NO automatic health/failover network request to protected servers
           at any point after vpnbot startup.
"""

import asyncio
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from servers import ServerManager, VPNServer


# ── helpers ──────────────────────────────────────────────────────────────────

def _srv(server_id: str, enabled: bool = True) -> VPNServer:
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
    )


def _run(coro):
    return asyncio.run(coro)


def _manager(*server_ids: str) -> ServerManager:
    mgr = ServerManager()
    for sid in server_ids:
        mgr.servers[sid] = _srv(sid)
    return mgr


# ── tests ─────────────────────────────────────────────────────────────────────

class TestUS2NetworkGuard(unittest.TestCase):

    # ── TEST A ────────────────────────────────────────────────────────────────

    def test_a_check_all_servers_does_not_dispatch_to_protected(self):
        """
        check_all_servers() must NOT call check_server_health for us2/us2-ws.

        RED on unpatched code: check_all_servers iterates self.servers.values()
        which includes all servers, so dispatched will contain us2/us2-ws.
        """
        mgr = _manager("fr1", "us1", "uk1", "us2", "us2-ws")
        dispatched: list[str] = []

        async def spy(server: VPNServer) -> bool:
            dispatched.append(server.id)
            return True

        with mock.patch.object(mgr, "check_server_health", side_effect=spy):
            _run(mgr.check_all_servers())

        # Protected — must NOT be dispatched to network check
        self.assertNotIn(
            "us2", dispatched,
            "check_all_servers dispatched network check to protected server us2",
        )
        self.assertNotIn(
            "us2-ws", dispatched,
            "check_all_servers dispatched network check to protected server us2-ws",
        )

        # Normal servers — must still be dispatched
        self.assertIn("fr1", dispatched)
        self.assertIn("us1", dispatched)
        self.assertIn("uk1", dispatched)

    # ── TEST B ────────────────────────────────────────────────────────────────

    def test_b_check_server_health_us2_no_aiohttp(self):
        """
        check_server_health(us2) must not instantiate aiohttp.ClientSession.

        RED on unpatched code: the method always creates a ClientSession
        and makes an HTTP POST to the XUI login endpoint.
        """
        mgr = _manager("us2")
        us2 = mgr.servers["us2"]

        with mock.patch("servers.aiohttp.ClientSession") as mock_session:
            _run(mgr.check_server_health(us2))

        mock_session.assert_not_called()

    # ── TEST C ────────────────────────────────────────────────────────────────

    def test_c_check_server_health_us2ws_no_aiohttp(self):
        """
        check_server_health(us2-ws) must not instantiate aiohttp.ClientSession.

        RED on unpatched code.
        """
        mgr = _manager("us2-ws")
        us2ws = mgr.servers["us2-ws"]

        with mock.patch("servers.aiohttp.ClientSession") as mock_session:
            _run(mgr.check_server_health(us2ws))

        mock_session.assert_not_called()

    # ── TEST D ────────────────────────────────────────────────────────────────

    def test_d_normal_server_still_attempts_network(self):
        """
        Guard must not block normal servers.
        check_server_health(fr1) must still attempt network (ClientSession used).

        This is a regression/GREEN test — passes on both patched and unpatched code.
        Raises ConnectionError intentionally to avoid real network; the
        method catches it and returns False.
        """
        mgr = _manager("fr1")
        fr1 = mgr.servers["fr1"]

        attempted: list[bool] = []

        def tracking_session(*args, **kwargs):
            attempted.append(True)
            raise ConnectionError("test sentinel — no real network")

        with mock.patch("servers.aiohttp.ClientSession", side_effect=tracking_session):
            _run(mgr.check_server_health(fr1))

        self.assertTrue(
            len(attempted) > 0,
            "Guard must not prevent network attempt for normal server fr1",
        )

    # ── TEST E ────────────────────────────────────────────────────────────────

    def test_e_health_check_loop_first_iteration_no_protected_network(self):
        """
        _health_check_loop first iteration must not dispatch check_server_health
        to protected servers, even though there is no initial sleep in the loop.

        RED on unpatched code: loop calls check_all_servers() which dispatches
        check_server_health to ALL servers including protected ones.

        The loop is broken safely after first asyncio.sleep call (= after the
        first check_all_servers completes).
        """
        mgr = _manager("fr1", "us1", "uk1", "us2", "us2-ws")
        dispatched: list[str] = []

        async def spy(server: VPNServer) -> bool:
            dispatched.append(server.id)
            return True

        async def run_one_iteration() -> None:
            async def mock_sleep(_: float) -> None:
                raise asyncio.CancelledError()

            with mock.patch.object(mgr, "check_server_health", side_effect=spy):
                with mock.patch("asyncio.sleep", side_effect=mock_sleep):
                    try:
                        await mgr._health_check_loop()
                    except asyncio.CancelledError:
                        pass

        _run(run_one_iteration())

        self.assertNotIn(
            "us2", dispatched,
            "_health_check_loop first iteration contacted protected server us2",
        )
        self.assertNotIn(
            "us2-ws", dispatched,
            "_health_check_loop first iteration contacted protected server us2-ws",
        )

    # ── TEST F ────────────────────────────────────────────────────────────────

    def test_f_protected_absent_from_check_all_servers_results(self):
        """
        Protected servers must be absent from the dict returned by check_all_servers().

        _scheduler_server_failover iterates health_results.items() — if us2/us2-ws
        appear there with is_healthy=False, the failover logic will treat them as
        failed servers and eventually send admin alerts or trigger cleanup.

        RED on unpatched code: results include all servers.
        """
        mgr = _manager("fr1", "us1", "uk1", "us2", "us2-ws")

        async def spy(server: VPNServer) -> bool:
            return True

        with mock.patch.object(mgr, "check_server_health", side_effect=spy):
            results = _run(mgr.check_all_servers())

        self.assertNotIn(
            "us2", results,
            "us2 appears in check_all_servers results — failover scheduler will process it",
        )
        self.assertNotIn(
            "us2-ws", results,
            "us2-ws appears in check_all_servers results — failover scheduler will process it",
        )

        # Normal servers must still appear in results
        self.assertIn("fr1", results)
        self.assertIn("us1", results)
        self.assertIn("uk1", results)

    # ── TEST G — constant ─────────────────────────────────────────────────────

    def test_g_protected_server_ids_constant_exported(self):
        """
        servers.py must export PROTECTED_SERVER_IDS containing at least us2
        and us2-ws as a frozenset (or equivalent iterable supporting `in`).

        RED on unpatched code: constant does not exist.
        """
        try:
            from servers import PROTECTED_SERVER_IDS
        except ImportError:
            self.fail(
                "PROTECTED_SERVER_IDS not exported from servers.py — "
                "add: PROTECTED_SERVER_IDS = frozenset({'us2', 'us2-ws'})"
            )

        self.assertIn("us2", PROTECTED_SERVER_IDS)
        self.assertIn("us2-ws", PROTECTED_SERVER_IDS)
        self.assertNotIn("fr1", PROTECTED_SERVER_IDS)
        self.assertNotIn("us1", PROTECTED_SERVER_IDS)


if __name__ == "__main__":
    unittest.main()
