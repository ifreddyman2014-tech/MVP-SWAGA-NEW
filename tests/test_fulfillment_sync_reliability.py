"""
P0-B TDD tests: payment.fulfillment_status must remain 'pending' until
the primary VPN panel sync succeeds in handle_payment_success (renewal path).

P0-B invariant:
  PRIMARY server sync failure MUST leave fulfillment_status='pending'.
  Secondary sync (non-primary servers) is best-effort — its failure does NOT
  keep fulfillment pending.

RED tests (fail on unpatched bot.py):
  1. Renewal primary update_client raises  → status must stay 'pending'
  2. Renewal primary login returns False   → status must stay 'pending'

GREEN tests (pass on both patched and unpatched):
  3. New-sub primary _server_add_client fails → stays 'pending' (already correct)
  4. Normal renewal sync succeeds → status becomes 'fulfilled'
  5. Already-fulfilled payment → early return, no panel calls made
  6. Retry after failure → no double-extension of subscription end_date
  7. WS server renewal → 'fulfilled' without instantiating XUIAPI

Root cause (unpatched code):
  In handle_payment_success renewal path (bot.py ~2963-2978), the primary
  update_client() call is wrapped in a try/except that only logs a WARNING.
  Execution falls through to mark_payment_fulfilled() at line 2999
  unconditionally — regardless of whether the sync succeeded.

Fix (applied to make RED tests GREEN):
  Replace the inline try/except XUIAPI block with _server_sync_client(),
  which already handles both WS and XUI correctly and returns bool.
  Gate mark_payment_fulfilled() on the returned bool.
"""

import asyncio
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock

# ── bootstrap: stub heavy deps before importing bot ──────────────────────────

os.environ.setdefault("BOT_TOKEN", "123456789:AAHs-FakeTestTokenP0B_abc0")

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

_original_db_path = _config.DB_PATH

_TEMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TEMP_DB.close()
_TEMP_DB_PATH = _TEMP_DB.name
_config.DB_PATH = _TEMP_DB_PATH

import database as _db
import bot as _bot

_db.DB_PATH = _TEMP_DB_PATH  # override cached binding regardless of import order
_config.DB_PATH = _original_db_path  # restore for other test modules

from servers import ServerManager, VPNServer
import aiosqlite


# ── helpers ───────────────────────────────────────────────────────────────────

def run(coro):
    return asyncio.run(coro)


def _make_srv(server_id: str = "fr1", transport: str = "tcp") -> VPNServer:
    return VPNServer(
        id=server_id,
        name=f"Test {server_id}",
        host="10.0.0.1",
        xui_host="10.0.0.1",
        xui_port=2053,
        xui_web_path="/panel",
        xui_username="admin",
        xui_password="pass",
        enabled=True,
        transport=transport,
        flow="xtls-rprx-vision",
        inbound_id=1,
        vpn_port=54232,
    )


def _make_mgr(server_id: str = "fr1", transport: str = "tcp") -> ServerManager:
    mgr = ServerManager()
    mgr.servers[server_id] = _make_srv(server_id, transport=transport)
    return mgr


async def _get_fulfillment_status(payment_id: str) -> str | None:
    async with aiosqlite.connect(_db.DB_PATH) as conn:
        async with conn.execute(
            "SELECT fulfillment_status FROM payments WHERE payment_id = ?",
            (payment_id,),
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else None


async def _get_sub_end_date(user_id: int) -> str | None:
    async with aiosqlite.connect(_db.DB_PATH) as conn:
        async with conn.execute(
            "SELECT end_date FROM subscriptions WHERE user_id=? AND is_active=1",
            (user_id,),
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else None


async def _setup_renewal(uid: int, payment_id: str, server_id: str = "fr1") -> str:
    """Create user + active subscription + pending payment. Returns existing UUID."""
    await _db.create_user(uid, f"user_{uid}")
    now = datetime.utcnow()
    end = now + timedelta(days=30)
    uuid = f"uuid-p0b-{uid}"
    await _db.create_subscription(
        user_id=uid, plan="1m",
        start_date=now.isoformat(), end_date=end.isoformat(),
        vless_uuid=uuid, xui_sub_id=f"sub-{uid}",
        server_id=server_id, xui_email=f"tg_{uid}",
    )
    async with aiosqlite.connect(_db.DB_PATH) as conn:
        await conn.execute(
            "INSERT INTO payments "
            "(payment_id, user_id, amount, plan_key, status, created_at) "
            "VALUES (?, ?, ?, ?, 'pending', ?)",
            (payment_id, uid, 130.0, "1m", now.isoformat()),
        )
        await conn.commit()
    return uuid


async def _create_pending_payment(uid: int, payment_id: str) -> None:
    now = datetime.utcnow()
    async with aiosqlite.connect(_db.DB_PATH) as conn:
        await conn.execute(
            "INSERT INTO payments "
            "(payment_id, user_id, amount, plan_key, status, created_at) "
            "VALUES (?, ?, ?, ?, 'pending', ?)",
            (payment_id, uid, 130.0, "1m", now.isoformat()),
        )
        await conn.commit()


def _xui_mock(login_ok: bool = True,
              update_raises: Exception | None = None,
              aou_returns: bool = True):
    """
    Build a mock XUIAPI class.

    login_ok      — return value of login() (bool)
    update_raises — if set, update_client() raises this exception
    aou_returns   — drives ensure_client() return value:
                    True  → EnsureResult.UPDATED (sync succeeded)
                    False → EnsureResult.FAILED  (sync failed)
    """
    from xui_api import EnsureResult
    instance = mock.MagicMock()
    instance.login.return_value = login_ok
    if update_raises is not None:
        instance.update_client.side_effect = update_raises
    else:
        instance.update_client.return_value = mock.MagicMock()
    instance.add_or_update_client.return_value = aou_returns
    instance.ensure_client.return_value = EnsureResult.UPDATED if aou_returns else EnsureResult.FAILED
    cls = mock.MagicMock(return_value=instance)
    return cls, instance


# ── test class ────────────────────────────────────────────────────────────────

class TestFulfillmentSyncReliability(unittest.TestCase):
    """
    P0-B: fulfillment_status must stay 'pending' when primary VPN sync fails.

    Tests 1–2 are RED on unpatched bot.py and GREEN after the fix.
    Tests 3–7 are GREEN on both patched and unpatched code.
    """

    @classmethod
    def setUpClass(cls):
        run(_db.init_db())

    # ── TEST 1 (RED) ──────────────────────────────────────────────────────────

    def test_1_renewal_update_client_raises_stays_pending(self):
        """
        RED on unpatched code: update_client() raises ConnectionError.
        The exception is swallowed at bot.py ~2977 and mark_payment_fulfilled()
        is still called unconditionally → status becomes 'fulfilled'.

        After fix: primary_sync_ok=False → mark_payment_fulfilled NOT called
        → status stays 'pending'.
        """
        uid, pid = 20001, "p0b_001"
        run(_setup_renewal(uid, pid, server_id="fr1"))

        mock_cls, _ = _xui_mock(
            login_ok=True,
            update_raises=ConnectionError("Panel unreachable"),
            aou_returns=False,  # _server_sync_client also fails after the fix
        )
        mgr = _make_mgr("fr1")

        with mock.patch("servers.server_manager", mgr), \
             mock.patch("xui_api.XUIAPI", mock_cls), \
             mock.patch.object(_bot, "_sync_client_to_other_servers",
                               lambda *a, **kw: None):
            run(_bot.handle_payment_success(uid, "1m", "fr1", 130.0, payment_id=pid))

        status = run(_get_fulfillment_status(pid))
        self.assertEqual(
            status, "pending",
            f"[TEST 1 RED] Expected 'pending' (panel unreachable), got '{status}'. "
            "Bug: mark_payment_fulfilled called despite primary sync failure.",
        )

    # ── TEST 2 (RED) ──────────────────────────────────────────────────────────

    def test_2_renewal_login_failure_stays_pending(self):
        """
        RED on unpatched code: login() returns False.
        The `if login_resp.json().get("success"):` guard is False →
        update_client is never called → no exception is raised →
        execution falls through to mark_payment_fulfilled() → 'fulfilled'.

        After fix: _server_sync_client returns False on auth failure
        → primary_sync_ok=False → status stays 'pending'.
        """
        uid, pid = 20002, "p0b_002"
        run(_setup_renewal(uid, pid, server_id="fr1"))

        mock_cls, _ = _xui_mock(login_ok=False, aou_returns=False)
        mgr = _make_mgr("fr1")

        with mock.patch("servers.server_manager", mgr), \
             mock.patch("xui_api.XUIAPI", mock_cls), \
             mock.patch.object(_bot, "_sync_client_to_other_servers",
                               lambda *a, **kw: None):
            run(_bot.handle_payment_success(uid, "1m", "fr1", 130.0, payment_id=pid))

        status = run(_get_fulfillment_status(pid))
        self.assertEqual(
            status, "pending",
            f"[TEST 2 RED] Expected 'pending' (login failure), got '{status}'. "
            "Bug: mark_payment_fulfilled called despite auth failure.",
        )

    # ── TEST 3 (GREEN) ────────────────────────────────────────────────────────

    def test_3_new_sub_primary_failure_stays_pending(self):
        """
        GREEN: The new-sub path already correctly gates mark_payment_fulfilled
        on primary success (via raise RuntimeError → except → return).
        Verified here to document expected behavior and ensure no regression.
        """
        uid, pid = 20003, "p0b_003"
        run(_db.create_user(uid, f"user_{uid}"))
        run(_create_pending_payment(uid, pid))

        mgr = _make_mgr("fr1")

        with mock.patch("servers.server_manager", mgr), \
             mock.patch.object(_bot, "_server_add_client", return_value=False), \
             mock.patch.object(_bot, "_sync_client_to_other_servers",
                               lambda *a, **kw: None):
            run(_bot.handle_payment_success(uid, "1m", "fr1", 130.0, payment_id=pid))

        status = run(_get_fulfillment_status(pid))
        self.assertEqual(
            status, "pending",
            f"[TEST 3] New-sub primary failure must leave status 'pending', got '{status}'.",
        )

    # ── TEST 4 (GREEN) ────────────────────────────────────────────────────────

    def test_4_renewal_sync_success_becomes_fulfilled(self):
        """
        GREEN (both patched and unpatched): Normal renewal where the primary
        panel sync succeeds. Payment must become 'fulfilled'.
        """
        uid, pid = 20004, "p0b_004"
        run(_setup_renewal(uid, pid, server_id="fr1"))

        mock_cls, _ = _xui_mock(
            login_ok=True,
            update_raises=None,   # update_client succeeds (current code path)
            aou_returns=True,     # add_or_update_client succeeds (fix path)
        )
        mgr = _make_mgr("fr1")

        with mock.patch("servers.server_manager", mgr), \
             mock.patch("xui_api.XUIAPI", mock_cls), \
             mock.patch.object(_bot, "_sync_client_to_other_servers",
                               lambda *a, **kw: None):
            run(_bot.handle_payment_success(uid, "1m", "fr1", 130.0, payment_id=pid))

        status = run(_get_fulfillment_status(pid))
        self.assertEqual(
            status, "fulfilled",
            f"[TEST 4] Normal renewal must become 'fulfilled', got '{status}'.",
        )

    # ── TEST 5 (GREEN) ────────────────────────────────────────────────────────

    def test_5_already_fulfilled_noop(self):
        """
        GREEN: begin_fulfillment returns 'already_fulfilled' → handle_payment_success
        returns early without making any panel calls or changing the subscription.
        """
        uid, pid = 20005, "p0b_005"
        run(_setup_renewal(uid, pid, server_id="fr1"))

        async def _pre_fulfill():
            async with aiosqlite.connect(_db.DB_PATH) as conn:
                await conn.execute(
                    "UPDATE payments "
                    "SET status='succeeded', fulfillment_status='fulfilled' "
                    "WHERE payment_id=?",
                    (pid,),
                )
                await conn.commit()

        run(_pre_fulfill())

        mock_cls, mock_instance = _xui_mock()
        mgr = _make_mgr("fr1")

        with mock.patch("servers.server_manager", mgr), \
             mock.patch("xui_api.XUIAPI", mock_cls), \
             mock.patch.object(_bot, "_sync_client_to_other_servers",
                               lambda *a, **kw: None):
            run(_bot.handle_payment_success(uid, "1m", "fr1", 130.0, payment_id=pid))

        status = run(_get_fulfillment_status(pid))
        self.assertEqual(status, "fulfilled",
                         f"[TEST 5] Status must stay 'fulfilled', got '{status}'.")

        # No panel calls on early return
        self.assertFalse(
            mock_cls.called,
            "[TEST 5] XUIAPI must not be instantiated for already-fulfilled payment.",
        )

    # ── TEST 6 (GREEN) ────────────────────────────────────────────────────────

    def test_6_retry_after_failure_no_double_extension(self):
        """
        GREEN: After a primary sync failure leaves payment 'pending', a second
        call (simulating startup-sync / webhook retry) succeeds and marks
        payment fulfilled WITHOUT re-extending the subscription end_date.

        No-double-extension invariant:
          end_date_after_retry == end_date_after_first_call
        """
        uid, pid = 20006, "p0b_006"
        run(_setup_renewal(uid, pid, server_id="fr1"))

        mgr = _make_mgr("fr1")

        # First call: primary sync fails (exception)
        mock_fail, _ = _xui_mock(
            login_ok=True,
            update_raises=ConnectionError("Panel down"),
            aou_returns=False,
        )
        with mock.patch("servers.server_manager", mgr), \
             mock.patch("xui_api.XUIAPI", mock_fail), \
             mock.patch.object(_bot, "_sync_client_to_other_servers",
                               lambda *a, **kw: None):
            run(_bot.handle_payment_success(uid, "1m", "fr1", 130.0, payment_id=pid))

        end_after_first = run(_get_sub_end_date(uid))
        self.assertIsNotNone(end_after_first,
                             "[TEST 6] Subscription must exist after first call.")

        # begin_fulfillment always commits the extension atomically —
        # end_date should now be initial_end + 30 days ≈ 60 days from now
        self.assertGreater(
            datetime.fromisoformat(end_after_first),
            datetime.utcnow() + timedelta(days=45),
            "[TEST 6] begin_fulfillment must have atomically extended the subscription.",
        )

        # Second call: sync succeeds
        mock_ok, _ = _xui_mock(login_ok=True, aou_returns=True)
        with mock.patch("servers.server_manager", mgr), \
             mock.patch("xui_api.XUIAPI", mock_ok), \
             mock.patch.object(_bot, "_sync_client_to_other_servers",
                               lambda *a, **kw: None):
            run(_bot.handle_payment_success(uid, "1m", "fr1", 130.0, payment_id=pid))

        # Subscription end_date must NOT change on the retry
        end_after_retry = run(_get_sub_end_date(uid))
        self.assertEqual(
            end_after_first, end_after_retry,
            f"[TEST 6] Retry must not re-extend: "
            f"first={end_after_first}, retry={end_after_retry}.",
        )

        # Payment must be 'fulfilled' (first or second call, depending on code version)
        status = run(_get_fulfillment_status(pid))
        self.assertEqual(status, "fulfilled",
                         f"[TEST 6] Final status must be 'fulfilled', got '{status}'.")

    # ── TEST 7 (GREEN) ────────────────────────────────────────────────────────

    def test_7_ws_server_renewal_no_xui_instantiation(self):
        """
        GREEN: WS servers don't store expiry in the XUI panel — the DB is the
        source of truth. Renewal on a WS server must mark payment 'fulfilled'
        without ever instantiating XUIAPI.

        Both unpatched code (skips the `if transport != 'ws':` block) and
        patched code (_server_sync_client handles WS via ws_manager) must
        satisfy this.
        """
        uid, pid = 20007, "p0b_007"
        run(_setup_renewal(uid, pid, server_id="fr1-ws"))

        mock_cls, _ = _xui_mock()
        mgr = _make_mgr("fr1-ws", transport="ws")

        with mock.patch("servers.server_manager", mgr), \
             mock.patch("xui_api.XUIAPI", mock_cls), \
             mock.patch("ws_manager.add_client", return_value=True), \
             mock.patch.object(_bot, "_sync_client_to_other_servers",
                               lambda *a, **kw: None):
            run(_bot.handle_payment_success(uid, "1m", "fr1-ws", 130.0, payment_id=pid))

        status = run(_get_fulfillment_status(pid))
        self.assertEqual(
            status, "fulfilled",
            f"[TEST 7] WS renewal must become 'fulfilled', got '{status}'.",
        )

        self.assertFalse(
            mock_cls.called,
            "[TEST 7] XUIAPI must not be instantiated for WS server renewal.",
        )

    # ── TEST 8 (RED) ──────────────────────────────────────────────────────────

    def test_8_protected_primary_us2_renewal_stays_pending(self):
        """
        RED on unpatched code: subscription on us2, renewal webhook fires.
        Currently _server_sync_client(us2) is called → network to 31.57.38.104.

        After fix: renewal-path guard prevents _server_sync_client being called;
        primary_sync_ok stays False → payment remains 'pending'.
        """
        uid, pid = 20008, "p0b_008"
        run(_setup_renewal(uid, pid, server_id="us2"))

        mgr = _make_mgr("us2")  # us2 IS in server config — 7 real active users
        sync_spy = mock.MagicMock(return_value=True)  # would return True → mark fulfilled

        with mock.patch("servers.server_manager", mgr), \
             mock.patch.object(_bot, "_server_sync_client", sync_spy), \
             mock.patch.object(_bot, "_sync_client_to_other_servers",
                               lambda *a, **kw: None):
            run(_bot.handle_payment_success(uid, "1m", "us2", 130.0, payment_id=pid))

        sync_spy.assert_not_called()  # RED: spy IS called on unpatched code

        status = run(_get_fulfillment_status(pid))
        self.assertEqual(
            status, "pending",
            f"[TEST 8 RED] Expected 'pending' for protected us2 primary, got '{status}'. "
            "Bug: renewal path calls _server_sync_client for protected server.",
        )

    # ── TEST 9 (RED) ──────────────────────────────────────────────────────────

    def test_9_protected_primary_us2ws_renewal_stays_pending(self):
        """
        RED on unpatched code: subscription on us2-ws, renewal webhook fires.
        Currently _server_sync_client(us2-ws) is called → ws_manager.add_client.

        After fix: renewal-path guard prevents _server_sync_client being called.
        """
        uid, pid = 20009, "p0b_009"
        run(_setup_renewal(uid, pid, server_id="us2-ws"))

        mgr = _make_mgr("us2-ws", transport="ws")
        sync_spy = mock.MagicMock(return_value=True)

        with mock.patch("servers.server_manager", mgr), \
             mock.patch.object(_bot, "_server_sync_client", sync_spy), \
             mock.patch.object(_bot, "_sync_client_to_other_servers",
                               lambda *a, **kw: None):
            run(_bot.handle_payment_success(uid, "1m", "us2-ws", 130.0, payment_id=pid))

        sync_spy.assert_not_called()  # RED: spy IS called on unpatched code

        status = run(_get_fulfillment_status(pid))
        self.assertEqual(
            status, "pending",
            f"[TEST 9 RED] Expected 'pending' for protected us2-ws primary, got '{status}'. "
            "Bug: renewal path calls _server_sync_client for protected server.",
        )

    # ── TEST 10 (RED) ─────────────────────────────────────────────────────────

    def test_10_server_sync_client_protected_returns_false_no_network(self):
        """
        Defense-in-depth: _server_sync_client() itself must refuse to contact
        protected servers, returning False before any network call.

        RED on unpatched code: no guard → XUIAPI or ws_manager.add_client is invoked.
        After fix: guard at function entry returns False with no network.
        """
        us2_server = _make_srv("us2", transport="tcp")
        us2ws_server = _make_srv("us2-ws", transport="ws")

        mock_cls, mock_instance = _xui_mock(login_ok=True, aou_returns=True)

        with mock.patch("xui_api.XUIAPI", mock_cls), \
             mock.patch("ws_manager.add_client", return_value=True) as mock_ws:
            result_us2 = _bot._server_sync_client(
                us2_server, "test-uuid", "test@email"
            )
            result_us2ws = _bot._server_sync_client(
                us2ws_server, "test-uuid", "test@email"
            )

        self.assertFalse(
            result_us2,
            "[TEST 10] _server_sync_client(us2) must return False without network.",
        )
        self.assertFalse(
            result_us2ws,
            "[TEST 10] _server_sync_client(us2-ws) must return False without network.",
        )
        self.assertFalse(
            mock_cls.called,
            "[TEST 10] XUIAPI must not be instantiated for protected us2.",
        )
        self.assertFalse(
            mock_ws.called,
            "[TEST 10] ws_manager.add_client must not be called for protected us2-ws.",
        )
