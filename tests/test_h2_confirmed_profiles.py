"""
H2 Confirmed Profile Fulfillment — TDD tests (RED before implementation, GREEN after).

Covers spec scenarios A–R.
"""
import sys, os, unittest, asyncio
from unittest import mock
from dataclasses import dataclass, field
from typing import List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Minimal server stub ───────────────────────────────────────────────────────

@dataclass
class _Server:
    id: str
    name: str = "Test"
    host: str = "1.2.3.4"
    vpn_port: int = 443
    xui_host: str = "127.0.0.1"
    xui_port: int = 4444
    xui_web_path: str = "/panel"
    xui_username: str = "admin"
    xui_password: str = "pass"
    xui_ssl: bool = True
    xui_standard: bool = True
    transport: str = "tcp"
    inbound_id: int = 1
    flow: str = "xtls-rprx-vision"
    enabled: bool = True
    location: str = "US"
    reality_pbk: str = "pbk"
    reality_sid: str = "sid"
    reality_sni: str = "sni"
    reality_fp: str = "chrome"
    ws_host: str = ""
    ws_ssh_password: str = ""
    ws_config_path: str = ""
    ws_ssh_key: str = ""
    transport_path: str = "/"
    transport_host: str = ""
    xhttp_mode: str = ""


def _srv(sid, **kw):
    return _Server(id=sid, **kw)


def _prov():
    import provisioning
    return provisioning


def _ProvisioningResult():
    return _prov().ProvisioningResult


def _run(coro):
    return asyncio.run(coro)


# ══════════════════════════════════════════════════════════════════════════════
# A: all candidates provision successfully → all included
# ══════════════════════════════════════════════════════════════════════════════

class TestResolveAllSucceed(unittest.TestCase):

    def _resolve(self, servers, sync_returns):
        prov = _prov()
        with mock.patch.object(prov, "server_sync_client", side_effect=sync_returns):
            return prov.resolve_available_profiles(servers, "uuid1", "e@x", "s1", 9999)

    def test_A_all_available(self):
        r = self._resolve([_srv("fr1"), _srv("us1"), _srv("uk1")], [True, True, True])
        self.assertEqual(len(r.available_servers), 3)
        self.assertEqual(len(r.failed_servers), 0)

    def test_A_ids_preserved(self):
        r = self._resolve([_srv("fr1"), _srv("us1")], [True, True])
        self.assertIn("fr1", [s.id for s in r.available_servers])
        self.assertIn("us1", [s.id for s in r.available_servers])


# ══════════════════════════════════════════════════════════════════════════════
# B: one profile fails → working included, failed excluded
# ══════════════════════════════════════════════════════════════════════════════

class TestResolvePartialFailure(unittest.TestCase):

    def _resolve(self, servers, sync_returns):
        prov = _prov()
        with mock.patch.object(prov, "server_sync_client", side_effect=sync_returns):
            return prov.resolve_available_profiles(servers, "uuid1", "e@x", "s1", 9999)

    def test_B_partial(self):
        r = self._resolve([_srv("fr1"), _srv("us1"), _srv("uk1")], [True, False, True])
        self.assertIn("fr1", [s.id for s in r.available_servers])
        self.assertIn("uk1", [s.id for s in r.available_servers])
        self.assertIn("us1", [s.id for s in r.failed_servers])

    def test_B_count(self):
        r = self._resolve([_srv("fr1"), _srv("us1"), _srv("uk1"), _srv("x")],
                           [True, False, True, False])
        self.assertEqual(len(r.available_servers), 2)
        self.assertEqual(len(r.failed_servers), 2)


# ══════════════════════════════════════════════════════════════════════════════
# C: all fail → zero available
# ══════════════════════════════════════════════════════════════════════════════

class TestResolveAllFailed(unittest.TestCase):

    def test_C_zero_available(self):
        prov = _prov()
        srvs = [_srv("fr1"), _srv("us1")]
        with mock.patch.object(prov, "server_sync_client", side_effect=[False, False]):
            r = prov.resolve_available_profiles(srvs, "u", "e", "s", 9999)
        self.assertEqual(len(r.available_servers), 0)
        self.assertEqual(len(r.failed_servers), 2)


# ══════════════════════════════════════════════════════════════════════════════
# D/E: protected servers excluded BEFORE any I/O
# ══════════════════════════════════════════════════════════════════════════════

class TestProtectedExclusion(unittest.TestCase):

    def _run(self, servers):
        prov = _prov()
        called = []

        def recording_sync(srv, *a, **kw):
            called.append(srv.id)
            return True

        with mock.patch.object(prov, "server_sync_client", side_effect=recording_sync):
            r = prov.resolve_available_profiles(servers, "u", "e", "s", 9999)
        return r, called

    def test_D_us2_not_called(self):
        _, called = self._run([_srv("fr1"), _srv("us2"), _srv("us1")])
        self.assertNotIn("us2", called)

    def test_D_us2_not_in_available(self):
        r, _ = self._run([_srv("fr1"), _srv("us2"), _srv("us1")])
        self.assertNotIn("us2", [s.id for s in r.available_servers])

    def test_D_us2_not_in_failed(self):
        r, _ = self._run([_srv("fr1"), _srv("us2"), _srv("us1")])
        self.assertNotIn("us2", [s.id for s in r.failed_servers])

    def test_E_us2ws_not_called(self):
        _, called = self._run([_srv("fr1"), _srv("us2-ws"), _srv("uk1")])
        self.assertNotIn("us2-ws", called)

    def test_D_others_still_called(self):
        _, called = self._run([_srv("fr1"), _srv("us2"), _srv("us1")])
        self.assertIn("fr1", called)
        self.assertIn("us1", called)


# ══════════════════════════════════════════════════════════════════════════════
# F: standard XUI healthy client → ALREADY_OK, no duplicate
# ══════════════════════════════════════════════════════════════════════════════

class TestServerSyncStandard(unittest.TestCase):

    def test_F_already_ok_returned(self):
        from xui_api import EnsureResult
        prov = _prov()
        srv = _srv("fr1", xui_standard=True)
        with mock.patch("xui_api.XUIAPI") as cls:
            inst = cls.return_value
            inst.login.return_value = True
            inst.ensure_client.return_value = EnsureResult.ALREADY_OK
            result = prov.server_sync_client(srv, "u", "e", sub_id="s", expiry_ms=100)
        self.assertTrue(result)
        inst.ensure_client.assert_called_once()

    def test_F_failed_on_conflict(self):
        from xui_api import EnsureResult
        prov = _prov()
        srv = _srv("fr1", xui_standard=True)
        with mock.patch("xui_api.XUIAPI") as cls:
            inst = cls.return_value
            inst.login.return_value = True
            inst.ensure_client.return_value = EnsureResult.CONFLICT
            result = prov.server_sync_client(srv, "u", "e", sub_id="s", expiry_ms=100)
        self.assertFalse(result)


# ══════════════════════════════════════════════════════════════════════════════
# G: US1-xhttp alias — panel email uses _i3 suffix
# ══════════════════════════════════════════════════════════════════════════════

class TestUS1XhttpAlias(unittest.TestCase):

    def test_G_alias_suffix(self):
        from xui_api import EnsureResult
        prov = _prov()
        srv = _srv("us1-xhttp", xui_standard=True)
        with mock.patch("xui_api.XUIAPI") as cls:
            inst = cls.return_value
            inst.login.return_value = True
            inst.ensure_client.return_value = EnsureResult.CREATED
            prov.server_sync_client(srv, "u", "tg_123", sub_id="s", expiry_ms=100)
        call_email = inst.ensure_client.call_args[0][2]
        self.assertEqual(call_email, "tg_123_i3")


# ══════════════════════════════════════════════════════════════════════════════
# H: UK1-xhttp uses deployed UK1 adapter
# ══════════════════════════════════════════════════════════════════════════════

class TestUK1XhttpAdapter(unittest.TestCase):

    def test_H_uses_ensure_client_uk1(self):
        from xui_api import EnsureResult
        prov = _prov()
        srv = _srv("uk1-xhttp", xui_standard=False, xui_ssl=False,
                   xui_host="127.0.0.1", xui_port=13226)
        with mock.patch("xui_api.XUIAPI") as cls:
            inst = cls.return_value
            inst.login.return_value = True
            inst.ensure_client_uk1.return_value = EnsureResult.CREATED
            result = prov.server_sync_client(srv, "u", "e", sub_id="s", expiry_ms=100)
        self.assertTrue(result)
        inst.ensure_client_uk1.assert_called_once()
        inst.ensure_client.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# I: WS profile → ws_manager path
# ══════════════════════════════════════════════════════════════════════════════

class TestWSProfile(unittest.TestCase):

    def test_I_ws_uses_ws_manager(self):
        prov = _prov()
        srv = _srv("fr1-ws", transport="ws", ws_host="127.0.0.1",
                   ws_config_path="/etc/xray-ws/config.json")
        with mock.patch("ws_manager.add_client", return_value=True) as ws_add, \
             mock.patch("xui_api.XUIAPI") as xui_cls:
            result = prov.server_sync_client(srv, "u", "e", sub_id="s")
        self.assertTrue(result)
        ws_add.assert_called_once()
        xui_cls.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# J: exception isolation
# ══════════════════════════════════════════════════════════════════════════════

class TestExceptionIsolation(unittest.TestCase):

    def test_J_exception_isolated(self):
        prov = _prov()
        srvs = [_srv("fr1"), _srv("us1"), _srv("uk1")]

        def flaky(srv, *a, **kw):
            if srv.id == "us1":
                raise ConnectionError("panel unreachable")
            return True

        with mock.patch.object(prov, "server_sync_client", side_effect=flaky):
            r = prov.resolve_available_profiles(srvs, "u", "e", "s", 9999)

        self.assertIn("fr1", [s.id for s in r.available_servers])
        self.assertIn("uk1", [s.id for s in r.available_servers])
        self.assertIn("us1", [s.id for s in r.failed_servers])

    def test_J_all_raise(self):
        prov = _prov()
        srvs = [_srv("fr1"), _srv("us1")]
        with mock.patch.object(prov, "server_sync_client", side_effect=RuntimeError("chaos")):
            r = prov.resolve_available_profiles(srvs, "u", "e", "s", 9999)
        self.assertEqual(len(r.available_servers), 0)
        self.assertEqual(len(r.failed_servers), 2)


# ══════════════════════════════════════════════════════════════════════════════
# K: /sub — failed profile absent from generated output
# ══════════════════════════════════════════════════════════════════════════════

class TestSubConfirmedOnly(unittest.TestCase):

    def test_K_only_confirmed_in_sub(self):
        """
        /sub calls resolve_available_profiles and includes only available servers.
        Verify by asserting handle_subscription calls the resolver and builds
        VLESS links only for available_servers.
        """
        import base64
        import sub_app
        from aiohttp.test_utils import make_mocked_request
        from provisioning import ProvisioningResult

        fr1 = _srv("fr1")
        us1 = _srv("us1", host="9.9.9.9")

        prov_result = ProvisioningResult(available_servers=[fr1], failed_servers=[us1])

        sub = {
            "vless_uuid": "test-uuid", "is_active": 1,
            "end_date": "2030-01-01", "server_id": "fr1",
            "xui_sub_id": "sid1", "xui_email": "tg_123",
        }

        req = make_mocked_request("GET", "/sub/testid",
                                  match_info={"sub_id": "testid"})

        async def run():
            with mock.patch("sub_app.get_sub_by_xui_id",
                            new=mock.AsyncMock(return_value=sub)), \
                 mock.patch("sub_app.resolve_available_profiles",
                            return_value=prov_result), \
                 mock.patch("sub_app.server_manager") as sm:
                sm.servers = {"fr1": fr1, "us1": us1}
                sm.get_all_servers.return_value = [fr1, us1]
                return await sub_app.handle_subscription(req)

        resp = _run(run())
        body = base64.b64decode(resp.text).decode()
        # Only 1 confirmed server → exactly 1 VLESS link
        self.assertEqual(body.count("vless://"), 1, "Only confirmed server in /sub")
        # us1's distinct host must not appear
        self.assertNotIn("9.9.9.9", body)

    def test_K_resolve_called_with_enabled_non_protected(self):
        """sub_app.handle_subscription calls resolve_available_profiles."""
        import sub_app
        from aiohttp.test_utils import make_mocked_request
        from provisioning import ProvisioningResult

        fr1 = _srv("fr1")
        us2 = _srv("us2")  # protected

        prov_result = ProvisioningResult(available_servers=[fr1], failed_servers=[])
        resolve_calls = []

        def capturing(candidates, *a, **kw):
            resolve_calls.append([s.id for s in candidates])
            return prov_result

        sub = {
            "vless_uuid": "test-uuid", "is_active": 1,
            "end_date": "2030-01-01", "server_id": "fr1",
            "xui_sub_id": "sid1", "xui_email": "tg_123",
        }
        req = make_mocked_request("GET", "/sub/testid",
                                  match_info={"sub_id": "testid"})

        async def run():
            with mock.patch("sub_app.get_sub_by_xui_id",
                            new=mock.AsyncMock(return_value=sub)), \
                 mock.patch("sub_app.resolve_available_profiles",
                            side_effect=capturing), \
                 mock.patch("sub_app.server_manager") as sm:
                sm.servers = {"fr1": fr1, "us2": us2}
                sm.get_all_servers.return_value = [fr1, us2]
                return await sub_app.handle_subscription(req)

        _run(run())
        self.assertTrue(resolve_calls, "resolve_available_profiles must be called from /sub")
        # us2 (protected) must not appear in candidates passed to resolver
        for call_ids in resolve_calls:
            self.assertNotIn("us2", call_ids,
                             "Protected us2 must not be in resolver candidates")


# ══════════════════════════════════════════════════════════════════════════════
# L: /connect — failed profile not exposed
# ══════════════════════════════════════════════════════════════════════════════

class TestConnectConfirmedOnly(unittest.TestCase):

    def test_L_failed_host_absent_from_connect(self):
        import sub_app
        from aiohttp.test_utils import make_mocked_request
        from provisioning import ProvisioningResult

        fr1 = _srv("fr1")
        us1 = _srv("us1", host="9.9.9.9")

        prov_result = ProvisioningResult(available_servers=[fr1], failed_servers=[us1])

        sub = {
            "vless_uuid": "test-uuid", "is_active": 1,
            "end_date": "2030-01-01", "server_id": "fr1",
            "xui_sub_id": "sid1", "xui_email": "tg_123",
        }
        req = make_mocked_request("GET", "/connect/testid",
                                  match_info={"sub_id": "testid"})

        async def run():
            with mock.patch("sub_app.get_sub_by_xui_id",
                            new=mock.AsyncMock(return_value=sub)), \
                 mock.patch("sub_app.resolve_available_profiles",
                            return_value=prov_result), \
                 mock.patch("sub_app.server_manager") as sm:
                sm.servers = {"fr1": fr1, "us1": us1}
                sm.get_all_servers.return_value = [fr1, us1]
                return await sub_app.handle_connect(req)

        resp = _run(run())
        # us1's distinct host (9.9.9.9) must not appear in HTML
        self.assertNotIn("9.9.9.9", resp.text)


# ══════════════════════════════════════════════════════════════════════════════
# M: partial payment provisioning
# ══════════════════════════════════════════════════════════════════════════════

class TestPaymentPartial(unittest.TestCase):

    def test_M_partial_provisioning(self):
        """Payment DB succeeded; working profiles returned; failed endpoint absent."""
        import bot as b
        from provisioning import ProvisioningResult

        fr1 = _srv("fr1")
        us1 = _srv("us1")
        prov_result = ProvisioningResult(available_servers=[fr1], failed_servers=[us1])

        fulfillment = ("first", "2030-01-01T00:00:00", {
            "uuid": "u1", "xui_sub_id": "s1", "email": "tg_x",
            "server_id": "fr1", "end_date": "2030-01-01T00:00:00",
            "expiry_ms": 1900000000000,
        })
        mark_calls = []

        with mock.patch("bot.begin_fulfillment", new=mock.AsyncMock(return_value=fulfillment)), \
             mock.patch("bot.mark_payment_fulfilled",
                        new=mock.AsyncMock(side_effect=lambda p: mark_calls.append(p))), \
             mock.patch("bot.resolve_available_profiles", return_value=prov_result), \
             mock.patch("bot.server_manager") as sm, \
             mock.patch("bot.get_active_sub", new=mock.AsyncMock(return_value=None)), \
             mock.patch("bot.bot") as tgbot, \
             mock.patch("bot.notify_admins", new=mock.AsyncMock()), \
             mock.patch("bot.process_referral_bonus",
                        new=mock.AsyncMock(return_value=None)):
            sm.servers = {"fr1": fr1, "us1": us1}
            sm.get_all_servers.return_value = [fr1, us1]
            sm.get_best_server.return_value = fr1
            sm.get_server.return_value = fr1
            tgbot.send_message = mock.AsyncMock()

            _run(b.handle_payment_success(
                user_id=999, plan_key="1m", server_id="fr1",
                amount=130, payment_id="pay_m01",
            ))

        self.assertIn("pay_m01", mark_calls, "Payment must be fulfilled when >=1 confirmed")
        tgbot.send_message.assert_called()

    def test_N_zero_provisioning_no_fake_success(self):
        """Zero confirmed → payment NOT fulfilled, activation-problem message sent."""
        import bot as b
        from provisioning import ProvisioningResult

        zero = ProvisioningResult(available_servers=[], failed_servers=[_srv("fr1")])

        fulfillment = ("first", "2030-01-01T00:00:00", {
            "uuid": "u1", "xui_sub_id": "s1", "email": "tg_x",
            "server_id": "fr1", "end_date": "2030-01-01T00:00:00",
            "expiry_ms": 1900000000000,
        })
        mark_calls = []
        messages = []

        with mock.patch("bot.begin_fulfillment", new=mock.AsyncMock(return_value=fulfillment)), \
             mock.patch("bot.mark_payment_fulfilled",
                        new=mock.AsyncMock(side_effect=lambda p: mark_calls.append(p))), \
             mock.patch("bot.resolve_available_profiles", return_value=zero), \
             mock.patch("bot.server_manager") as sm, \
             mock.patch("bot.get_active_sub", new=mock.AsyncMock(return_value=None)), \
             mock.patch("bot.bot") as tgbot, \
             mock.patch("bot.notify_admins", new=mock.AsyncMock()), \
             mock.patch("bot.process_referral_bonus",
                        new=mock.AsyncMock(return_value=None)):
            sm.servers = {"fr1": _srv("fr1")}
            sm.get_all_servers.return_value = [_srv("fr1")]
            sm.get_best_server.return_value = _srv("fr1")
            sm.get_server.return_value = _srv("fr1")

            async def capture(uid, text, **kw):
                messages.append(text)
            tgbot.send_message = mock.AsyncMock(side_effect=capture)

            _run(b.handle_payment_success(
                user_id=999, plan_key="1m", server_id="fr1",
                amount=130, payment_id="pay_n01",
            ))

        self.assertNotIn("pay_n01", mark_calls,
                         "Payment must NOT be fulfilled when zero confirmed")
        self.assertTrue(messages, "User must receive a message")
        joined = " ".join(messages)
        self.assertNotIn("✅", joined, "Must not send fake success (✅)")


# ══════════════════════════════════════════════════════════════════════════════
# O/P: trial and renewal use same resolver
# ══════════════════════════════════════════════════════════════════════════════

class TestTrialAndRenewal(unittest.TestCase):

    def test_O_trial_calls_resolver(self):
        """Trial activation calls resolve_available_profiles."""
        import bot as b
        from provisioning import ProvisioningResult

        fr1 = _srv("fr1")
        prov_result = ProvisioningResult(available_servers=[fr1], failed_servers=[])
        calls = []

        def capturing(candidates, uuid, email, sub_id, expiry_ms):
            calls.append(True)
            return prov_result

        cb = mock.MagicMock()
        cb.from_user.id = 11111
        cb.message.answer = mock.AsyncMock()
        cb.answer = mock.AsyncMock()

        with mock.patch("bot.get_user",
                        new=mock.AsyncMock(return_value={"trial_used": False})), \
             mock.patch("bot.mark_trial_used", new=mock.AsyncMock()), \
             mock.patch("bot.get_active_sub", new=mock.AsyncMock(return_value=None)), \
             mock.patch("bot.deactivate_user_subs", new=mock.AsyncMock()), \
             mock.patch("bot.create_subscription", new=mock.AsyncMock()), \
             mock.patch("bot.process_referral_bonus",
                        new=mock.AsyncMock(return_value=None)), \
             mock.patch("bot.server_manager") as sm, \
             mock.patch("bot.resolve_available_profiles", side_effect=capturing):
            sm.servers = {"fr1": fr1}
            sm.get_all_servers.return_value = [fr1]
            sm.get_best_server.return_value = fr1

            _run(b._create_subscription_on_server(cb, "trial", None))

        self.assertGreater(len(calls), 0,
                           "resolve_available_profiles must be called for trial")

    def test_P_renewal_calls_resolver(self):
        """Renewal calls resolve_available_profiles."""
        import bot as b
        from provisioning import ProvisioningResult

        fr1 = _srv("fr1")
        prov_result = ProvisioningResult(available_servers=[fr1], failed_servers=[])
        calls = []

        def capturing(candidates, uuid, email, sub_id, expiry_ms):
            calls.append(True)
            return prov_result

        existing = {
            "vless_uuid": "e-uuid", "xui_sub_id": "esid",
            "server_id": "fr1", "xui_email": "tg_11111",
            "end_date": "2030-01-01T00:00:00", "is_active": 1,
        }
        fulfillment = ("first", "2031-01-01T00:00:00", {
            "uuid": "e-uuid", "xui_sub_id": "esid", "email": "tg_11111",
            "server_id": "fr1", "end_date": "2031-01-01T00:00:00",
            "expiry_ms": 1930000000000,
        })
        mark_calls = []

        with mock.patch("bot.begin_fulfillment",
                        new=mock.AsyncMock(return_value=fulfillment)), \
             mock.patch("bot.mark_payment_fulfilled",
                        new=mock.AsyncMock(side_effect=lambda p: mark_calls.append(p))), \
             mock.patch("bot.resolve_available_profiles", side_effect=capturing), \
             mock.patch("bot.server_manager") as sm, \
             mock.patch("bot.get_active_sub", new=mock.AsyncMock(return_value=existing)), \
             mock.patch("bot.bot") as tgbot, \
             mock.patch("bot.notify_admins", new=mock.AsyncMock()), \
             mock.patch("bot.process_referral_bonus",
                        new=mock.AsyncMock(return_value=None)):
            sm.servers = {"fr1": fr1}
            sm.get_all_servers.return_value = [fr1]
            sm.get_server.return_value = fr1
            tgbot.send_message = mock.AsyncMock()

            _run(b.handle_payment_success(
                user_id=11111, plan_key="1m", server_id="fr1",
                amount=130, payment_id="pay_p01",
            ))

        self.assertGreater(len(calls), 0,
                           "resolve_available_profiles must be called for renewal")
        self.assertIn("pay_p01", mark_calls)


# ══════════════════════════════════════════════════════════════════════════════
# Q: no-shrink (ensure_client + ensure_client_uk1)
# ══════════════════════════════════════════════════════════════════════════════

class TestNoShrink(unittest.TestCase):

    def test_Q_no_shrink_standard(self):
        from xui_api import XUIAPI, EnsureResult
        api = XUIAPI()
        api.base_url = "http://127.0.0.1:9999"
        client = {"id": "my-uuid", "email": "tg_x", "expiryTime": 9_999_999_999_000}
        with mock.patch.object(api, "get_inbound_clients", return_value=[client]), \
             mock.patch.object(api, "update_client") as upd:
            r = api.ensure_client(1, "my-uuid", "tg_x", expiry_time=1_900_000_000_000)
        self.assertEqual(r, EnsureResult.ALREADY_OK)
        upd.assert_not_called()

    def test_Q_no_shrink_uk1(self):
        from xui_api import XUIAPI, EnsureResult
        api = XUIAPI()
        api.base_url = "http://127.0.0.1:9999"
        client = {"id": "my-uuid", "email": "tg_x", "expiryTime": 9_999_999_999_000}
        with mock.patch.object(api, "get_inbound_clients_uk1", return_value=[client]), \
             mock.patch.object(api, "_uk1_update_client") as upd:
            r = api.ensure_client_uk1(2, "my-uuid", "tg_x", expiry_time=1_900_000_000_000)
        self.assertEqual(r, EnsureResult.ALREADY_OK)
        upd.assert_not_called()

    def test_Q_does_update_when_stale(self):
        from xui_api import XUIAPI, EnsureResult
        api = XUIAPI()
        api.base_url = "http://127.0.0.1:9999"
        client = {"id": "my-uuid", "email": "tg_x", "expiryTime": 1_000_000_000_000}
        with mock.patch.object(api, "get_inbound_clients", return_value=[client]), \
             mock.patch.object(api, "update_client", return_value=True) as upd:
            r = api.ensure_client(1, "my-uuid", "tg_x", expiry_time=1_900_000_000_000)
        self.assertEqual(r, EnsureResult.UPDATED)
        upd.assert_called_once()


# ══════════════════════════════════════════════════════════════════════════════
# R: idempotency
# ══════════════════════════════════════════════════════════════════════════════

class TestIdempotency(unittest.TestCase):

    def test_R_repeated_call(self):
        prov = _prov()
        fr1 = _srv("fr1")
        counts = [0]

        def sync_fn(srv, *a, **kw):
            counts[0] += 1
            return True

        with mock.patch.object(prov, "server_sync_client", side_effect=sync_fn):
            r1 = prov.resolve_available_profiles([fr1], "u", "e", "s", 9999)
            r2 = prov.resolve_available_profiles([fr1], "u", "e", "s", 9999)
        self.assertEqual(len(r1.available_servers), 1)
        self.assertEqual(len(r2.available_servers), 1)
        self.assertEqual(counts[0], 2)

    def test_R_no_expiry_regression(self):
        from xui_api import XUIAPI, EnsureResult
        expiry = 1_900_000_000_000
        api = XUIAPI()
        api.base_url = "http://127.0.0.1:9999"
        client = {"id": "my-uuid", "email": "tg_x", "expiryTime": expiry}
        with mock.patch.object(api, "get_inbound_clients", return_value=[client]), \
             mock.patch.object(api, "update_client") as upd:
            r = api.ensure_client(1, "my-uuid", "tg_x", expiry_time=expiry)
        self.assertEqual(r, EnsureResult.ALREADY_OK)
        upd.assert_not_called()


if __name__ == "__main__":
    unittest.main()
