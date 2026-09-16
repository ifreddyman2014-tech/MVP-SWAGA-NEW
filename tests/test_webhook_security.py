"""
P0-A: YooKassa webhook trust boundary — TDD security tests.

No real network calls. No production DB. Uses isolated temp SQLite.
YooKassa API is a fake/mock at the external boundary only.
Real handler + real DB functions are tested — only external I/O is mocked.

RED tests (1–6): fail on current production code, confirming the vulnerability.
GREEN tests (7–10): regression/happy-path; require the security fix.
"""

import asyncio
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Isolated DB ───────────────────────────────────────────────────────────────
# database.DB_PATH is set from config at import time.
# We patch database.DB_PATH directly in each test call so changes apply
# regardless of import order with test_payment_logic.py.

import database as _db
import config as _cfg

_WHSEC_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_WHSEC_DB.close()
_WHSEC_DB_PATH = _WHSEC_DB.name


def run(coro):
    return asyncio.run(coro)


# ── DB helpers ────────────────────────────────────────────────────────────────

def _db_init():
    with mock.patch("database.DB_PATH", _WHSEC_DB_PATH):
        run(_db.init_db())


def _db_create_user(user_id: int):
    with mock.patch("database.DB_PATH", _WHSEC_DB_PATH):
        run(_db.create_user(user_id, f"user_{user_id}"))


def _db_create_sub(user_id: int, plan: str = "trial",
                   uuid: str = "test-uuid-sec", days: int = 30):
    with mock.patch("database.DB_PATH", _WHSEC_DB_PATH):
        now = datetime.utcnow()
        run(_db.create_subscription(
            user_id=user_id, plan=plan,
            start_date=now.isoformat(),
            end_date=(now + timedelta(days=days)).isoformat(),
            vless_uuid=uuid, xui_sub_id="sub-sec",
            server_id="fr1", xui_email=f"tg_{user_id}",
        ))


def _db_create_payment(payment_id: str, user_id: int,
                        amount: float, plan_key: str,
                        server_id: str = "fr1",
                        status: str = "pending"):
    import aiosqlite

    async def _do():
        async with aiosqlite.connect(_WHSEC_DB_PATH) as conn:
            await conn.execute(
                """INSERT OR IGNORE INTO payments
                   (payment_id, user_id, amount, plan_key, server_id, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (payment_id, user_id, amount, plan_key, server_id, status,
                 datetime.utcnow().isoformat()),
            )
            await conn.commit()

    run(_do())


def _db_get_payment(payment_id: str):
    with mock.patch("database.DB_PATH", _WHSEC_DB_PATH):
        return run(_db.get_payment(payment_id))


def _db_get_sub(user_id: int):
    with mock.patch("database.DB_PATH", _WHSEC_DB_PATH):
        return run(_db.get_active_sub(user_id))


# ── Fake HTTP request ─────────────────────────────────────────────────────────

class _FakeRequest:
    """Minimal stand-in for aiohttp.web.Request."""
    def __init__(self, body: str = "{}"):
        self._body = body

    async def text(self) -> str:
        return self._body


# ── Mock factories ────────────────────────────────────────────────────────────

def _parse_webhook_mock(payment_id: str, status: str, amount: float,
                         user_id: int, plan_key: str, server_id: str):
    """Mock for yookassa_payment.parse_webhook — returns controlled dict."""
    def _mock(body: str):
        return {
            "event": f"payment.{status}",
            "payment_id": payment_id,
            "status": status,
            "amount": amount,
            "user_id": user_id,
            "plan_key": plan_key,
            "server_id": server_id,
        }
    return _mock


def _auth_payment_mock(payment_id: str,
                        status: str = "succeeded",
                        paid: bool = True,
                        amount_value: str = "130.00",
                        currency: str = "RUB"):
    """
    Mock for yookassa_payment.fetch_authoritative_payment.
    Returns a dict mimicking what the real function returns.
    """
    def _mock(pid: str):
        return {
            "id": payment_id,
            "status": status,
            "paid": paid,
            "amount_value": amount_value,
            "amount_currency": currency,
        }
    return _mock


# ── Helpers: check whether the security fix exists ───────────────────────────

def _fix_applied():
    """True if fetch_authoritative_payment exists in yookassa_payment (fix applied)."""
    import yookassa_payment
    return hasattr(yookassa_payment, "fetch_authoritative_payment")


# ── Test class ────────────────────────────────────────────────────────────────

class TestWebhookSecurity(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        _db_init()

    def setUp(self):
        self.callback_calls = []

        async def _recording_callback(payment_id, user_id, plan_key,
                                       server_id, amount, paid_at=""):
            self.callback_calls.append({
                "payment_id": payment_id,
                "user_id": user_id,
                "plan_key": plan_key,
                "server_id": server_id,
                "amount": amount,
            })

        import sub_app
        sub_app.set_payment_callback(_recording_callback)
        self._sub_app = sub_app

    def _call_handler(self, request=None):
        """Call the webhook handler with DB path patched to the test DB."""
        with mock.patch("database.DB_PATH", _WHSEC_DB_PATH):
            return run(self._sub_app.handle_yookassa_webhook(
                request or _FakeRequest()))

    # ──────────────────────────────────────────────────────────────────────────
    # RED #1 — Metadata Tampering
    # ──────────────────────────────────────────────────────────────────────────

    def test_01_metadata_tampering_entitlement_must_use_local_db(self):
        """
        LOCAL ORDER (DB):  payment_A → USER_A, plan=1m, 130 RUB, server=fr1
        WEBHOOK BODY:      payment_A, status=succeeded,
                           metadata TAMPERED: user_id=USER_B, plan=1y, server=uk1
        AUTHORITATIVE API: payment_A, paid=True, succeeded, 130 RUB

        DESIRED:  callback called with USER_A/1m/fr1 (from local DB)
                  USER_B must NEVER receive access.

        RED:  current handler passes webhook metadata directly → callback gets USER_B/1y.
        """
        USER_A = 301001
        USER_B = 301002
        PID = "pay_wsec_001"

        _db_create_user(USER_A)
        _db_create_sub(USER_A, plan="trial", uuid="uuid-wsec-001")
        _db_create_payment(PID, USER_A, 130.0, "1m", "fr1")

        # Tampered webhook: claims USER_B / 1y / uk1
        parse_mock = _parse_webhook_mock(PID, "succeeded", 130.0,
                                          USER_B, "1y", "uk1")
        auth_mock = _auth_payment_mock(PID, status="succeeded", paid=True,
                                        amount_value="130.00", currency="RUB")

        with mock.patch("yookassa_payment.parse_webhook", parse_mock):
            try:
                with mock.patch("yookassa_payment.fetch_authoritative_payment",
                                auth_mock):
                    self._call_handler()
            except AttributeError:
                # fetch_authoritative_payment not in production code yet (RED path)
                self._call_handler()

        # Must have fired with local trusted data, NOT with tampered metadata
        self.assertGreater(
            len(self.callback_calls), 0,
            "Callback must fire for a valid verified payment",
        )
        call = self.callback_calls[0]
        self.assertEqual(
            call["user_id"], USER_A,
            f"VULNERABILITY CONFIRMED: entitlement user_id={call['user_id']} "
            f"came from webhook metadata (USER_B={USER_B}), "
            f"not from local DB (USER_A={USER_A})",
        )
        self.assertEqual(
            call["plan_key"], "1m",
            f"VULNERABILITY CONFIRMED: plan_key={call['plan_key']} came from "
            f"tampered webhook metadata (1y), not local DB (1m)",
        )
        self.assertEqual(
            call["server_id"], "fr1",
            f"VULNERABILITY CONFIRMED: server_id={call['server_id']} came from "
            f"tampered webhook metadata (uk1), not local DB (fr1)",
        )

    # ──────────────────────────────────────────────────────────────────────────
    # RED #2 — Fake succeeded body: authoritative says pending/paid=false
    # ──────────────────────────────────────────────────────────────────────────

    def test_02_fake_succeeded_body_authoritative_pending(self):
        """
        LOCAL ORDER:  payment_B, USER_A, 1m, pending
        WEBHOOK BODY: payment_B, status=succeeded
        AUTHORITATIVE API: status=pending, paid=False

        DESIRED: NO callback call, NO fulfillment.

        RED: current handler has no authoritative check — fires callback anyway.
        """
        USER_A = 301003
        PID = "pay_wsec_002"

        _db_create_user(USER_A)
        _db_create_payment(PID, USER_A, 130.0, "1m")

        parse_mock = _parse_webhook_mock(PID, "succeeded", 130.0,
                                          USER_A, "1m", "fr1")
        auth_mock = _auth_payment_mock(PID, status="pending", paid=False,
                                        amount_value="130.00", currency="RUB")

        with mock.patch("yookassa_payment.parse_webhook", parse_mock):
            try:
                with mock.patch("yookassa_payment.fetch_authoritative_payment",
                                auth_mock):
                    self._call_handler()
            except AttributeError:
                self._call_handler()

        self.assertEqual(
            len(self.callback_calls), 0,
            f"VULNERABILITY CONFIRMED: callback fired despite authoritative "
            f"status=pending/paid=False. Calls: {self.callback_calls}",
        )

    # ──────────────────────────────────────────────────────────────────────────
    # RED #3 — Amount mismatch
    # ──────────────────────────────────────────────────────────────────────────

    def test_03_authoritative_amount_mismatch_no_fulfillment(self):
        """
        LOCAL ORDER:  payment_C, USER_A, 130.00 RUB
        AUTHORITATIVE: paid=True, succeeded, but amount=50.00 RUB

        DESIRED: NO fulfillment.

        RED: current handler has no amount verification.
        """
        USER_A = 301005
        PID = "pay_wsec_003"

        _db_create_user(USER_A)
        _db_create_payment(PID, USER_A, 130.0, "1m")

        parse_mock = _parse_webhook_mock(PID, "succeeded", 50.0,
                                          USER_A, "1m", "fr1")
        auth_mock = _auth_payment_mock(PID, paid=True, amount_value="50.00")

        with mock.patch("yookassa_payment.parse_webhook", parse_mock):
            try:
                with mock.patch("yookassa_payment.fetch_authoritative_payment",
                                auth_mock):
                    self._call_handler()
            except AttributeError:
                self._call_handler()

        self.assertEqual(
            len(self.callback_calls), 0,
            f"VULNERABILITY CONFIRMED: callback fired despite amount mismatch. "
            f"Calls: {self.callback_calls}",
        )

    # ──────────────────────────────────────────────────────────────────────────
    # RED #4 — Currency mismatch
    # ──────────────────────────────────────────────────────────────────────────

    def test_04_authoritative_currency_not_rub_no_fulfillment(self):
        """
        AUTHORITATIVE: paid=True, succeeded, amount correct, but currency=USD.

        DESIRED: reject, NO fulfillment.

        RED: current handler has no currency check.
        """
        USER_A = 301006
        PID = "pay_wsec_004"

        _db_create_user(USER_A)
        _db_create_payment(PID, USER_A, 130.0, "1m")

        parse_mock = _parse_webhook_mock(PID, "succeeded", 130.0,
                                          USER_A, "1m", "fr1")
        auth_mock = _auth_payment_mock(PID, paid=True,
                                        amount_value="130.00", currency="USD")

        with mock.patch("yookassa_payment.parse_webhook", parse_mock):
            try:
                with mock.patch("yookassa_payment.fetch_authoritative_payment",
                                auth_mock):
                    self._call_handler()
            except AttributeError:
                self._call_handler()

        self.assertEqual(
            len(self.callback_calls), 0,
            f"VULNERABILITY CONFIRMED: callback fired despite currency=USD. "
            f"Calls: {self.callback_calls}",
        )

    # ──────────────────────────────────────────────────────────────────────────
    # GREEN #5 — Unknown payment: no local DB record
    # (Already safe in current code — serves as regression test)
    # ──────────────────────────────────────────────────────────────────────────

    def test_05_unknown_payment_no_fulfillment(self):
        """
        Webhook for payment_id not in local DB.
        No entitlement must be created, even if authoritative says paid=True.
        Current code already handles this (regression guard).
        """
        PID = "pay_wsec_UNKNOWN_999"
        # intentionally NOT created in DB

        parse_mock = _parse_webhook_mock(PID, "succeeded", 130.0,
                                          99999, "1y", "fr1")
        auth_mock = _auth_payment_mock(PID, paid=True, status="succeeded")

        with mock.patch("yookassa_payment.parse_webhook", parse_mock):
            try:
                with mock.patch("yookassa_payment.fetch_authoritative_payment",
                                auth_mock):
                    self._call_handler()
            except AttributeError:
                self._call_handler()

        self.assertEqual(
            len(self.callback_calls), 0,
            "Unknown payment must never trigger fulfillment",
        )

    # ──────────────────────────────────────────────────────────────────────────
    # RED #6 — Authoritative API failure: fail-closed
    # ──────────────────────────────────────────────────────────────────────────

    def test_06_authoritative_api_failure_fail_closed(self):
        """
        Webhook received. YooKassa authoritative lookup raises (timeout/5xx).

        DESIRED: fail-closed — NO fulfillment, NO subscription mutation.
                 Handler may return 500 to allow YooKassa retry.

        RED: current handler has no authoritative call — fires callback on any
             webhook with status=succeeded.
        """
        USER_A = 301007
        PID = "pay_wsec_005"

        _db_create_user(USER_A)
        _db_create_payment(PID, USER_A, 130.0, "1m")

        parse_mock = _parse_webhook_mock(PID, "succeeded", 130.0,
                                          USER_A, "1m", "fr1")

        def _raising_auth(pid: str):
            raise TimeoutError("YooKassa API timeout")

        with mock.patch("yookassa_payment.parse_webhook", parse_mock):
            try:
                with mock.patch("yookassa_payment.fetch_authoritative_payment",
                                _raising_auth):
                    self._call_handler()
            except AttributeError:
                # fetch_authoritative_payment doesn't exist (pre-fix RED path)
                self._call_handler()

        self.assertEqual(
            len(self.callback_calls), 0,
            f"VULNERABILITY CONFIRMED: callback fired despite API timeout. "
            f"Calls: {self.callback_calls}",
        )

    # ──────────────────────────────────────────────────────────────────────────
    # GREEN #7 — Duplicate verified webhook: idempotent
    # (Requires security fix. Tests begin_fulfillment idempotency via DB.)
    # ──────────────────────────────────────────────────────────────────────────

    @unittest.skipUnless(_fix_applied(), "Requires security fix (fetch_authoritative_payment)")
    def test_07_duplicate_verified_webhook_idempotent(self):
        """
        Same verified succeeded webhook arrives twice.
        Subscription days must be accrued exactly once (begin_fulfillment idempotency).
        Both HTTP responses must be 200.
        """
        USER_A = 301070
        PID = "pay_wsec_007"

        _db_create_user(USER_A)
        _db_create_sub(USER_A, plan="trial", uuid="uuid-wsec-007", days=5)
        _db_create_payment(PID, USER_A, 130.0, "1m")

        fulfillment_results = []

        async def _fulfilling_callback(payment_id, user_id, plan_key,
                                        server_id, amount, paid_at=""):
            with mock.patch("database.DB_PATH", _WHSEC_DB_PATH):
                result, _, _ = await _db.begin_fulfillment(
                    payment_id, user_id, plan_key, 30,
                    paid_at or datetime.utcnow().isoformat(),
                    is_renewal=True, existing_uuid="uuid-wsec-007",
                )
            fulfillment_results.append(result)

        self._sub_app.set_payment_callback(_fulfilling_callback)

        parse_mock = _parse_webhook_mock(PID, "succeeded", 130.0,
                                          USER_A, "1m", "fr1")
        auth_mock = _auth_payment_mock(PID, paid=True, amount_value="130.00")

        with mock.patch("yookassa_payment.parse_webhook", parse_mock):
            with mock.patch("yookassa_payment.fetch_authoritative_payment", auth_mock):
                resp1 = self._call_handler()
                resp2 = self._call_handler()

        self.assertEqual(resp1.status, 200, "First webhook must return HTTP 200")
        self.assertEqual(resp2.status, 200, "Second webhook must return HTTP 200")
        self.assertEqual(len(fulfillment_results), 2,
                         "Both webhooks must reach the callback")
        self.assertIn("first", fulfillment_results,
                      "First webhook must win the fulfillment race")
        # Second must NOT win 'first' again — idempotency check
        second = fulfillment_results[1]
        self.assertIn(second, ("already_fulfilled", "sync_pending"),
                      f"Second webhook must be idempotent, got '{second}'")

    # ──────────────────────────────────────────────────────────────────────────
    # GREEN #8 — Legitimate payment: happy path
    # ──────────────────────────────────────────────────────────────────────────

    @unittest.skipUnless(_fix_applied(), "Requires security fix")
    def test_08_legitimate_payment_callback_fires_with_local_data(self):
        """
        All conditions match: local order = authoritative payment.
        Callback must fire exactly once with LOCAL user_id/plan/server.
        """
        USER_A = 301080
        PID = "pay_wsec_008"

        _db_create_user(USER_A)
        _db_create_sub(USER_A, plan="trial", uuid="uuid-wsec-008")
        _db_create_payment(PID, USER_A, 130.0, "1m", "fr1")

        parse_mock = _parse_webhook_mock(PID, "succeeded", 130.0,
                                          USER_A, "1m", "fr1")
        auth_mock = _auth_payment_mock(PID, paid=True, amount_value="130.00",
                                        currency="RUB")

        with mock.patch("yookassa_payment.parse_webhook", parse_mock):
            with mock.patch("yookassa_payment.fetch_authoritative_payment", auth_mock):
                resp = self._call_handler()

        self.assertEqual(resp.status, 200)
        self.assertEqual(len(self.callback_calls), 1,
                         "Callback must fire exactly once")
        call = self.callback_calls[0]
        self.assertEqual(call["payment_id"], PID)
        self.assertEqual(call["user_id"], USER_A)
        self.assertEqual(call["plan_key"], "1m")
        self.assertEqual(call["server_id"], "fr1")

    # ──────────────────────────────────────────────────────────────────────────
    # GREEN #9 — Discounted payment: not rejected for list price delta
    # ──────────────────────────────────────────────────────────────────────────

    @unittest.skipUnless(_fix_applied(), "Requires security fix")
    def test_09_discounted_payment_not_rejected_by_list_price(self):
        """
        Local order: plan=1y, amount=630 RUB (promo discount, list=900).
        Authoritative confirms 630.00 RUB.
        Must NOT be rejected because list price != 630.
        Amount comparison must be local_payment.amount vs authoritative, not list price.
        """
        USER_A = 301090
        PID = "pay_wsec_009"

        _db_create_user(USER_A)
        _db_create_sub(USER_A, plan="trial", uuid="uuid-wsec-009")
        _db_create_payment(PID, USER_A, 630.0, "1y", "fr1")  # discounted amount

        parse_mock = _parse_webhook_mock(PID, "succeeded", 630.0,
                                          USER_A, "1y", "fr1")
        auth_mock = _auth_payment_mock(PID, paid=True, amount_value="630.00",
                                        currency="RUB")

        with mock.patch("yookassa_payment.parse_webhook", parse_mock):
            with mock.patch("yookassa_payment.fetch_authoritative_payment", auth_mock):
                resp = self._call_handler()

        self.assertEqual(resp.status, 200)
        self.assertEqual(len(self.callback_calls), 1,
                         "Discounted payment must be VALID — callback must fire")
        call = self.callback_calls[0]
        self.assertEqual(call["plan_key"], "1y")

    # ──────────────────────────────────────────────────────────────────────────
    # GREEN #10 — Webhook metadata NEVER redirects entitlement (post-fix)
    # ──────────────────────────────────────────────────────────────────────────

    @unittest.skipUnless(_fix_applied(), "Requires security fix")
    def test_10_webhook_metadata_cannot_redirect_entitlement(self):
        """
        Post-fix regression: even with maximally tampered webhook metadata,
        entitlement must always come from the local DB.

        WEBHOOK METADATA:  user_id=USER_EVIL, plan=1y, server=uk1
        LOCAL DB ORDER:    USER_REAL, plan=1m, server=fr1
        AUTHORITATIVE:     paid=True, succeeded, 130 RUB

        EXPECTED CALL:     user_id=USER_REAL, plan=1m, server=fr1
        """
        USER_REAL = 301100
        USER_EVIL = 301101
        PID = "pay_wsec_010"

        _db_create_user(USER_REAL)
        _db_create_sub(USER_REAL, plan="trial", uuid="uuid-wsec-010")
        _db_create_payment(PID, USER_REAL, 130.0, "1m", "fr1")

        parse_mock = _parse_webhook_mock(PID, "succeeded", 130.0,
                                          USER_EVIL, "1y", "uk1")  # tampered
        auth_mock = _auth_payment_mock(PID, paid=True, amount_value="130.00",
                                        currency="RUB")

        with mock.patch("yookassa_payment.parse_webhook", parse_mock):
            with mock.patch("yookassa_payment.fetch_authoritative_payment", auth_mock):
                resp = self._call_handler()

        self.assertEqual(resp.status, 200)
        self.assertEqual(len(self.callback_calls), 1)
        call = self.callback_calls[0]

        self.assertNotEqual(call["user_id"], USER_EVIL,
                             "USER_EVIL must NEVER receive entitlement")
        self.assertEqual(call["user_id"], USER_REAL,
                         "Entitlement must use USER_REAL from local DB")
        self.assertEqual(call["plan_key"], "1m",
                         "Plan must come from local DB (1m), not webhook (1y)")
        self.assertEqual(call["server_id"], "fr1",
                         "Server must come from local DB (fr1), not webhook (uk1)")

    # ──────────────────────────────────────────────────────────────────────────
    # RED #11 — Verified payment must NOT be silently dropped when callback missing
    # ──────────────────────────────────────────────────────────────────────────

    def test_11_verified_payment_callback_missing_returns_retryable(self):
        """
        Payment fully verified (local order found, authoritative succeeded, paid,
        amount/currency match) but _payment_success_callback is None.

        CURRENT (BROKEN) behavior: HTTP 200 — YooKassa considers delivered,
        payment silently dropped, user never receives VPN access.

        REQUIRED behavior: HTTP 5xx so YooKassa retries until callback is live.
        No fulfillment mutation must occur.
        """
        USER_A = 301110
        PID = "pay_wsec_011"

        _db_create_user(USER_A)
        _db_create_sub(USER_A, plan="trial", uuid="uuid-wsec-011")
        _db_create_payment(PID, USER_A, 130.0, "1m")

        # Explicitly clear the callback — simulates handler receiving a request
        # before bot.py has registered its callback (startup race or restart).
        import sub_app
        sub_app.set_payment_callback(None)

        parse_mock = _parse_webhook_mock(PID, "succeeded", 130.0,
                                          USER_A, "1m", "fr1")
        auth_mock = _auth_payment_mock(PID, paid=True, amount_value="130.00",
                                        currency="RUB")

        with mock.patch("yookassa_payment.parse_webhook", parse_mock):
            with mock.patch("yookassa_payment.fetch_authoritative_payment", auth_mock):
                resp = self._call_handler()

        self.assertGreaterEqual(resp.status, 500,
            f"Verified payment with missing callback must return 5xx for retry, "
            f"got HTTP {resp.status}")
        self.assertEqual(len(self.callback_calls), 0,
            "No fulfillment must occur when callback is missing")


if __name__ == "__main__":
    unittest.main()
