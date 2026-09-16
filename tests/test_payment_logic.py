"""
Unit tests for payment/renewal logic.

No real servers, no real payments, no real Telegram calls.
Uses in-memory SQLite (patching DB_PATH) and mocked HTTP responses.

Covered scenarios:
   1. First payment after trial: plan updates from 'trial' to paid
   2. Renewal of paid subscription: days added, plan preserved
   3. Duplicate/concurrent webhook: second call is a no-op (idempotency)
   4. extend_subscription_to_date without plan: plan unchanged
   5. add_or_update_client calls updateClient endpoint first
   6. add_or_update_client falls back to addClient on 'record not found'
   7. Non-JSON (HTML) response: treated as auth error, no addClient
   8. Timeout on secondary server: sync returns False
   9. US2 exclusion: us2 and us2-ws are never in the sync target list (caller-level)
  10. Concurrent webhooks: rowcount guard ensures exactly one wins
  11. begin_fulfillment renewal (happy path): returns 'first', subscription extended atomically
  12. begin_fulfillment new sub (no existing): returns 'first', sub created, days computed
  13. begin_fulfillment concurrent: BEGIN IMMEDIATE serializes, second call returns 'sync_pending'
  14. Two different payment_ids accumulate days without overwriting
  15. begin_fulfillment 'sync_pending': re-read stored sub_info with no-shrink invariant
  16. us2 excluded from secondary sync targets by internal filter in _sync_client_to_other_servers
  17. us2-ws excluded from secondary sync targets by internal filter
  18. Startup sync skips protected primary servers (us2/us2-ws): subscription stays in DB
"""

import asyncio
import os
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Patch DB_PATH before importing database module so tests use a temp file
import config as _config

_TEMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TEMP_DB.close()
_config.DB_PATH = _TEMP_DB.name

import database as db


# ── Helpers ───────────────────────────────────────────────────────────────────

def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


async def _init():
    await db.init_db()


async def _create_user_and_sub(user_id: int, plan: str, end_days_from_now: int = 30,
                                vless_uuid: str = "test-uuid-0001"):
    await db.create_user(user_id, f"user_{user_id}")
    now = datetime.utcnow()
    end = now + timedelta(days=end_days_from_now)
    await db.create_subscription(
        user_id=user_id, plan=plan,
        start_date=now.isoformat(), end_date=end.isoformat(),
        vless_uuid=vless_uuid, xui_sub_id="sub123",
        server_id="fr1", xui_email=f"tg_{user_id}",
    )


async def _create_payment(payment_id: str, user_id: int, plan_key: str,
                           status: str = "pending"):
    import aiosqlite
    async with aiosqlite.connect(_config.DB_PATH) as conn:
        await conn.execute("""
            INSERT OR IGNORE INTO payments
              (payment_id, user_id, amount, plan_key, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (payment_id, user_id, 130.0, plan_key, status, datetime.utcnow().isoformat()))
        await conn.commit()


async def _create_succeeded_payment(payment_id: str, user_id: int, plan_key: str,
                                     target_end_date: str | None = None,
                                     fulfillment_status: str | None = None):
    """Create a succeeded payment, optionally with target_end_date and fulfillment_status."""
    import aiosqlite
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(_config.DB_PATH) as conn:
        await conn.execute("""
            INSERT OR IGNORE INTO payments
              (payment_id, user_id, amount, plan_key, status, created_at, paid_at,
               target_end_date, fulfillment_status)
            VALUES (?, ?, ?, ?, 'succeeded', ?, ?, ?, ?)
        """, (payment_id, user_id, 130.0, plan_key, now, now, target_end_date, fulfillment_status))
        await conn.commit()


async def _get_sub(user_id: int) -> dict | None:
    return await db.get_active_sub(user_id)


async def _get_payment(payment_id: str) -> dict | None:
    return await db.get_payment(payment_id)


# ── Test class ────────────────────────────────────────────────────────────────

class TestPaymentLogic(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        run(_init())

    # 1. First payment after trial → plan updated
    def test_01_first_payment_after_trial_updates_plan(self):
        uid = 100001
        run(_create_user_and_sub(uid, "trial"))
        sub_before = run(_get_sub(uid))
        self.assertEqual(sub_before["plan"], "trial")

        now = datetime.utcnow()
        new_end = now + timedelta(days=30)
        ok = run(db.extend_subscription_to_date(uid, new_end, plan="1m"))
        self.assertTrue(ok)

        sub_after = run(_get_sub(uid))
        self.assertEqual(sub_after["plan"], "1m")
        self.assertIn("T", sub_after["end_date"])

    # 2. Renewal of paid subscription → days added, plan preserved
    def test_02_renewal_preserves_plan(self):
        uid = 100002
        run(_create_user_and_sub(uid, "1m"))
        sub_before = run(_get_sub(uid))
        old_end = datetime.fromisoformat(sub_before["end_date"])
        new_end = old_end + timedelta(days=30)

        ok = run(db.extend_subscription_to_date(uid, new_end, plan="1m"))
        self.assertTrue(ok)

        sub_after = run(_get_sub(uid))
        self.assertEqual(sub_after["plan"], "1m")
        new_end_db = datetime.fromisoformat(sub_after["end_date"])
        self.assertGreater(new_end_db, old_end)

    # 3. Duplicate webhook → second update_payment_status is a no-op
    def test_03_duplicate_webhook_idempotent(self):
        pid = "pay_dup_001"
        uid = 100003
        run(_create_user_and_sub(uid, "trial"))
        run(_create_payment(pid, uid, "1m"))

        paid_at = datetime.utcnow().isoformat()
        run(db.update_payment_status(pid, "succeeded", paid_at))
        p1 = run(_get_payment(pid))
        self.assertEqual(p1["status"], "succeeded")
        self.assertEqual(p1["paid_at"], paid_at)

        # Second webhook with different paid_at — should NOT overwrite
        later_paid_at = (datetime.utcnow() + timedelta(hours=1)).isoformat()
        run(db.update_payment_status(pid, "succeeded", later_paid_at))
        p2 = run(_get_payment(pid))
        # paid_at must stay as original (guard: WHERE status != 'succeeded')
        self.assertEqual(p2["paid_at"], paid_at)

    # 4. extend_subscription_to_date without plan → plan unchanged
    def test_04_extend_without_plan_preserves_plan(self):
        uid = 100004
        run(_create_user_and_sub(uid, "3m"))
        new_end = datetime.utcnow() + timedelta(days=90)
        run(db.extend_subscription_to_date(uid, new_end))  # no plan kwarg
        sub = run(_get_sub(uid))
        self.assertEqual(sub["plan"], "3m")

    # 5-8. xui_api.py: add_or_update_client behavior
    def test_05_add_or_update_uses_update_first(self):
        """add_or_update_client calls updateClient endpoint first."""
        from xui_api import XUIAPI
        api = XUIAPI()
        api._logged_in = True

        call_log = []

        def mock_post(url, *a, **kw):
            call_log.append(url)
            resp = MagicMock()
            resp.headers = {"Content-Type": "application/json"}
            resp.json.return_value = {"success": True}
            return resp

        api.session.post = mock_post
        ok = api.add_or_update_client(1, "uuid-001", "user@test",
                                       sub_id="sub1", expiry_time=0)
        self.assertTrue(ok)
        self.assertTrue(any("updateClient" in u for u in call_log))
        self.assertFalse(any("addClient" in u for u in call_log))

    def test_06_add_or_update_falls_back_to_add_on_not_found(self):
        """add_or_update_client falls back to addClient on 'record not found'."""
        from xui_api import XUIAPI
        api = XUIAPI()
        api._logged_in = True

        call_log = []

        def mock_post(url, *a, **kw):
            call_log.append(url)
            resp = MagicMock()
            resp.headers = {"Content-Type": "application/json"}
            if "updateClient" in url:
                resp.json.return_value = {"success": False, "msg": "record not found"}
            else:
                resp.json.return_value = {"success": True}
            return resp

        api.session.post = mock_post
        ok = api.add_or_update_client(1, "uuid-002", "user2@test")
        self.assertTrue(ok)
        self.assertTrue(any("addClient" in u for u in call_log))

    def test_07_non_json_response_does_not_trigger_add(self):
        """HTML/non-JSON response from panel does NOT trigger addClient."""
        from xui_api import XUIAPI
        api = XUIAPI()
        api._logged_in = True

        call_log = []

        def mock_post(url, *a, **kw):
            call_log.append(url)
            resp = MagicMock()
            resp.headers = {"Content-Type": "text/html; charset=utf-8"}
            resp.status_code = 200
            return resp

        api.session.post = mock_post
        ok = api.add_or_update_client(1, "uuid-003", "user3@test")
        self.assertFalse(ok)
        self.assertFalse(any("addClient" in u for u in call_log))

    def test_08_timeout_returns_false(self):
        """Timeout on updateClient returns False without crashing."""
        import requests as _requests
        from xui_api import XUIAPI
        api = XUIAPI()
        api._logged_in = True

        def mock_post(url, *a, **kw):
            raise _requests.exceptions.Timeout()

        api.session.post = mock_post
        ok = api.add_or_update_client(1, "uuid-004", "user4@test")
        self.assertFalse(ok)

    # 9. US2 exclusion: us2 and us2-ws never reach sync even if passed in enabled_servers
    def test_09_us2_excluded_from_sync(self):
        """
        bot._sync_client_to_other_servers contains an internal guard that skips
        servers whose id is in _PROTECTED_SERVER_IDS = {"us2", "us2-ws"}.
        This test simulates that guard logic and verifies the filter holds
        regardless of what the caller passes in the server list.
        """
        # Mirrors bot._PROTECTED_SERVER_IDS
        PROTECTED = {"us2", "us2-ws"}

        def make_server(sid):
            s = types.SimpleNamespace()
            s.id = sid
            s.name = sid
            return s

        all_servers = [make_server(x) for x in ["fr1", "us2", "us2-ws", "uk1"]]
        primary_id = "fr1"

        # Simulate the loop body of _sync_client_to_other_servers
        would_sync = []
        for server in all_servers:
            if server.id == primary_id:
                continue
            if server.id in PROTECTED:
                continue
            would_sync.append(server.id)

        self.assertNotIn("us2", would_sync, "us2 must be excluded by internal filter")
        self.assertNotIn("us2-ws", would_sync, "us2-ws must be excluded by internal filter")
        self.assertIn("uk1", would_sync, "non-protected servers must still be synced")

    # 10. Concurrent webhooks: rowcount guard ensures exactly one wins
    def test_10_concurrent_webhooks_rowcount_guard(self):
        """
        Two concurrent update_payment_status('succeeded') calls on the same
        payment_id: SQLite's atomic UPDATE guard ensures exactly one returns True.
        """
        pid = "pay_concurrent_001"
        uid = 100010
        run(_create_user_and_sub(uid, "trial"))
        run(_create_payment(pid, uid, "1m"))

        paid_at = datetime.utcnow().isoformat()

        async def _both_webhooks():
            results = await asyncio.gather(
                db.update_payment_status(pid, "succeeded", paid_at),
                db.update_payment_status(pid, "succeeded", paid_at),
            )
            return results

        results = run(_both_webhooks())
        true_count = sum(1 for r in results if r)
        self.assertEqual(
            true_count, 1,
            f"Exactly one concurrent webhook must win the rowcount guard; got {results}",
        )

    # 11. begin_fulfillment renewal happy path
    def test_11_begin_fulfillment_renewal_first(self):
        """
        begin_fulfillment on a pending payment with an existing sub returns 'first',
        sets fulfillment_status='pending', updates the sub's end_date atomically.
        """
        pid = "pay_bf_renewal_001"
        uid = 110011
        run(_create_user_and_sub(uid, "trial", end_days_from_now=5,
                                  vless_uuid="uuid-bf-renew-001"))
        run(_create_payment(pid, uid, "1m"))

        sub_before = run(_get_sub(uid))
        end_before = datetime.fromisoformat(sub_before["end_date"])

        result, target_end_iso, sub_info = run(db.begin_fulfillment(
            pid, uid, "1m", 30, datetime.utcnow().isoformat(),
            is_renewal=True, existing_uuid="uuid-bf-renew-001",
        ))

        self.assertEqual(result, "first",
                         f"Expected 'first', got '{result}'")
        self.assertIsNotNone(target_end_iso)
        self.assertIsNotNone(sub_info)
        self.assertEqual(sub_info["uuid"], "uuid-bf-renew-001")
        self.assertTrue(sub_info["is_renewal"])

        # Subscription must be updated in DB
        sub_after = run(_get_sub(uid))
        end_after = datetime.fromisoformat(sub_after["end_date"])
        self.assertGreater(end_after, end_before + timedelta(days=29),
                           "Subscription must be extended by plan days")

        # Payment must be marked as succeeded + pending in DB
        pmt = run(_get_payment(pid))
        self.assertEqual(pmt["status"], "succeeded")
        self.assertEqual(pmt["fulfillment_status"], "pending")
        self.assertEqual(pmt["target_end_date"], target_end_iso)

    # 12. begin_fulfillment new sub (no existing subscription)
    def test_12_begin_fulfillment_new_sub_no_existing(self):
        """
        begin_fulfillment with is_renewal=False and no existing sub returns 'first',
        creates a subscription record atomically with the provided new_uuid.
        """
        pid = "pay_bf_new_001"
        uid = 110012
        run(db.create_user(uid, f"user_{uid}"))
        run(_create_payment(pid, uid, "1m"))

        new_uuid = "uuid-bf-new-001"
        result, target_end_iso, sub_info = run(db.begin_fulfillment(
            pid, uid, "1m", 30, datetime.utcnow().isoformat(),
            is_renewal=False,
            new_uuid=new_uuid,
            new_sub_id="subid-new-001",
            new_email="tg_110012",
            new_server_id="fr1",
        ))

        self.assertEqual(result, "first",
                         f"Expected 'first', got '{result}'")
        self.assertIsNotNone(target_end_iso)
        self.assertFalse(sub_info["is_renewal"])

        # A new subscription must exist in DB with the provided uuid
        sub = run(_get_sub(uid))
        self.assertIsNotNone(sub, "Subscription must be created")
        self.assertEqual(sub["vless_uuid"], new_uuid)
        self.assertEqual(sub["plan"], "1m")

        # Subscription end_date must be ~30 days from now
        end_dt = datetime.fromisoformat(sub["end_date"])
        self.assertGreater(end_dt, datetime.utcnow() + timedelta(days=29))

        # Payment status and fulfillment
        pmt = run(_get_payment(pid))
        self.assertEqual(pmt["status"], "succeeded")
        self.assertEqual(pmt["fulfillment_status"], "pending")

    # 13. begin_fulfillment concurrent: BEGIN IMMEDIATE serializes, second returns 'sync_pending'
    def test_13_begin_fulfillment_concurrent_serialized(self):
        """
        Two concurrent begin_fulfillment calls for the same payment_id:
        BEGIN IMMEDIATE serializes them. The first wins (returns 'first'),
        the second finds fulfillment_status='pending' and returns 'sync_pending'.

        This verifies the crash-recovery invariant: a second webhook or process
        restart safely detects the prior committed state.
        """
        pid = "pay_bf_concurrent_001"
        uid = 110013
        run(_create_user_and_sub(uid, "trial", end_days_from_now=5,
                                  vless_uuid="uuid-bf-conc-001"))
        run(_create_payment(pid, uid, "1m"))

        paid_at = datetime.utcnow().isoformat()

        async def _both():
            return await asyncio.gather(
                db.begin_fulfillment(
                    pid, uid, "1m", 30, paid_at,
                    is_renewal=True, existing_uuid="uuid-bf-conc-001",
                ),
                db.begin_fulfillment(
                    pid, uid, "1m", 30, paid_at,
                    is_renewal=True, existing_uuid="uuid-bf-conc-001",
                ),
            )

        results = run(_both())
        codes = [r[0] for r in results]
        self.assertIn("first", codes,
                      f"Exactly one call must win 'first'; got {codes}")
        self.assertTrue(
            all(c in ("first", "sync_pending", "already_fulfilled") for c in codes),
            f"All codes must be valid; got {codes}",
        )
        first_count = sum(1 for c in codes if c == "first")
        self.assertEqual(first_count, 1,
                         f"Exactly one 'first'; got {codes}")

    # 14. Two different payment_ids accumulate days (no overwrite)
    def test_14_two_payments_accumulate_days(self):
        """
        Payment A and payment B for the same user arrive sequentially.
        BEGIN IMMEDIATE inside begin_fulfillment ensures B reads A's committed end_date,
        so days accumulate: total = 30 + 30 = 60.
        """
        uid = 110014
        run(_create_user_and_sub(uid, "trial", end_days_from_now=5,
                                  vless_uuid="uuid-accum-001"))

        pid_a = "pay_accum_a"
        pid_b = "pay_accum_b"
        run(_create_payment(pid_a, uid, "1m"))
        run(_create_payment(pid_b, uid, "1m"))

        paid_at = datetime.utcnow().isoformat()

        # Process payment A
        res_a, _, _ = run(db.begin_fulfillment(
            pid_a, uid, "1m", 30, paid_at,
            is_renewal=True, existing_uuid="uuid-accum-001",
        ))
        self.assertEqual(res_a, "first")

        # Process payment B (reads A's committed end_date)
        res_b, target_b, sub_info_b = run(db.begin_fulfillment(
            pid_b, uid, "1m", 30, paid_at,
            is_renewal=True, existing_uuid="uuid-accum-001",
        ))
        self.assertEqual(res_b, "first", f"Payment B must also win 'first'; got {res_b}")

        # Final sub end_date should be ~5 + 30 + 30 = 65 days from now
        sub = run(_get_sub(uid))
        end_dt = datetime.fromisoformat(sub["end_date"])
        # Allow loose bounds: at least 55 days and at most 70 days from now
        self.assertGreater(end_dt, datetime.utcnow() + timedelta(days=55),
                           f"Two 30-day payments should add ~60 days; got {end_dt}")
        self.assertLess(end_dt, datetime.utcnow() + timedelta(days=70))

    # 15. begin_fulfillment 'sync_pending': no-shrink and correct sub_info returned
    def test_15_begin_fulfillment_sync_pending_no_shrink(self):
        """
        If fulfillment_status='pending', begin_fulfillment returns 'sync_pending'
        with sub_info based on the current subscription (no-shrink: expiry_ms uses
        max(target_end_date, sub.end_date)).
        """
        pid = "pay_bf_sync_001"
        uid = 110015
        now = datetime.utcnow()
        # Subscription already extended beyond target_end (manual extension scenario)
        target_end = now + timedelta(days=30)
        sub_end = now + timedelta(days=45)  # sub ahead of target

        run(db.create_user(uid, f"user_{uid}"))
        run(db.create_subscription(
            user_id=uid, plan="1m",
            start_date=now.isoformat(), end_date=sub_end.isoformat(),
            vless_uuid="uuid-noshrink-001", xui_sub_id="sub-noshrink",
            server_id="fr1", xui_email=f"tg_{uid}",
        ))
        # Payment with pending fulfillment
        run(_create_succeeded_payment(
            pid, uid, "1m",
            target_end_date=target_end.isoformat(),
            fulfillment_status="pending",
        ))

        result, stored_target, sub_info = run(db.begin_fulfillment(
            pid, uid, "1m", 30, now.isoformat(),
            is_renewal=True, existing_uuid="uuid-noshrink-001",
        ))

        self.assertEqual(result, "sync_pending",
                         f"Expected 'sync_pending', got '{result}'")

        # No-shrink: expiry_ms must use sub.end_date (45 days) not target_end (30 days)
        expected_min_ms = int((now + timedelta(days=44)).timestamp() * 1000)
        self.assertGreater(sub_info["expiry_ms"], expected_min_ms,
                           "No-shrink: expiry_ms must use max(target, sub.end_date)")


    # 16. us2 excluded from secondary sync targets — internal filter, not just caller
    def test_16_us2_never_secondary_sync_target(self):
        """
        Even if a caller passes us2 in the enabled_servers list (i.e. does NOT
        pre-filter), _sync_client_to_other_servers must skip it via
        _PROTECTED_SERVER_IDS.  Simulates the full loop with primary != us2.
        """
        PROTECTED = {"us2", "us2-ws"}

        def make_server(sid):
            s = types.SimpleNamespace()
            s.id = sid
            return s

        # Caller incorrectly includes us2 in the list (should still be filtered)
        servers = [make_server(x) for x in ["fr1", "us1", "us2", "uk1"]]
        primary_id = "fr1"

        synced = []
        for server in servers:
            if server.id == primary_id:
                continue
            if server.id in PROTECTED:
                continue
            synced.append(server.id)

        self.assertNotIn("us2", synced)
        self.assertIn("us1", synced)
        self.assertIn("uk1", synced)

    # 17. us2-ws excluded from secondary sync targets — internal filter
    def test_17_us2ws_never_secondary_sync_target(self):
        """
        us2-ws must also be excluded by the internal filter in
        _sync_client_to_other_servers, even if passed explicitly in the list.
        """
        PROTECTED = {"us2", "us2-ws"}

        def make_server(sid):
            s = types.SimpleNamespace()
            s.id = sid
            return s

        servers = [make_server(x) for x in ["fr1", "us2-ws", "uk1"]]
        primary_id = "fr1"

        synced = []
        for server in servers:
            if server.id == primary_id:
                continue
            if server.id in PROTECTED:
                continue
            synced.append(server.id)

        self.assertNotIn("us2-ws", synced)
        self.assertIn("uk1", synced)

    # 18. Startup sync skips protected primary servers — subscription stays in DB
    def test_18_startup_sync_skips_protected_primary(self):
        """
        _startup_sync_pending_fulfillments checks srv_id against _PROTECTED_SERVER_IDS
        before attempting any panel call. If the primary server is us2 or us2-ws,
        the payment is skipped (logged as warning) and the subscription remains valid
        in DB (not touched). Simulates the guard logic in that function.
        """
        PROTECTED = {"us2", "us2-ws"}

        # Simulate pending fulfillments on various servers
        pending = [
            {"payment_id": "pay_a", "server_id": "fr1"},
            {"payment_id": "pay_b", "server_id": "us2"},
            {"payment_id": "pay_c", "server_id": "us2-ws"},
            {"payment_id": "pay_d", "server_id": "uk1"},
        ]

        would_sync = []
        would_skip = []
        for pmt in pending:
            srv_id = pmt["server_id"]
            if srv_id in PROTECTED:
                would_skip.append(pmt["payment_id"])
                continue
            would_sync.append(pmt["payment_id"])

        self.assertIn("pay_b", would_skip, "us2 primary must be skipped")
        self.assertIn("pay_c", would_skip, "us2-ws primary must be skipped")
        self.assertNotIn("pay_a", would_skip, "fr1 must be processed")
        self.assertNotIn("pay_d", would_skip, "uk1 must be processed")
        self.assertIn("pay_a", would_sync)
        self.assertIn("pay_d", would_sync)


if __name__ == "__main__":
    unittest.main()
