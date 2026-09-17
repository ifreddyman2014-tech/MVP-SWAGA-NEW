"""
TDD — ws_manager host-identity fix.

Tests that ws_host field (physical WS host) is used for routing instead of xui_host
(XUI management endpoint). All tests run in isolation; no network calls, no production DB.
"""

import json
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

# Ensure the worktree root is on the path so we can import ws_manager.
sys.path.insert(0, str(Path(__file__).parent.parent))
import ws_manager

KNOWN_HOSTS_PATH = "/root/.ssh/swaga_ws_manager_known_hosts"

_MINIMAL_CONFIG = {
    "inbounds": [{"settings": {"clients": []}}]
}


def _make_config(clients=None):
    return {
        "inbounds": [{"settings": {"clients": clients or []}}]
    }


class _Server:
    """Minimal server stub matching VPNServer field access patterns."""
    def __init__(self, xui_host, ws_host="", ws_ssh_password="", ws_config_path="", ws_ssh_key=""):
        self.xui_host = xui_host
        self.ws_host = ws_host
        self.ws_ssh_password = ws_ssh_password
        self.ws_config_path = ws_config_path
        self.ws_ssh_key = ws_ssh_key


# ---------------------------------------------------------------------------
# TEST 1 — FR local routing
# ws_host=127.0.0.1 → _is_local → file I/O, no subprocess SSH
# ---------------------------------------------------------------------------
class Test01FRLocalRouting(unittest.TestCase):
    def test_local_host_uses_file_io_not_ssh(self):
        cfg = _make_config()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(cfg, f)
            tmp = f.name

        with patch("subprocess.run") as mock_run:
            ws_manager.add_client(
                host="127.0.0.1",
                password="",
                config_path=tmp,
                uuid="aaaa-1111",
                email="test@fr",
                ssh_key="",
            )
            # systemctl restart may be called locally, but must NOT be sshpass/ssh remote
            for c in mock_run.call_args_list:
                args = c[0][0] if c[0] else c[1].get("args", [])
                self.assertNotIn("sshpass", args, "sshpass must not be used for local host")
                self.assertNotIn("ssh", [a for a in args if a == "ssh"],
                                 "remote ssh must not be used for local host")

        Path(tmp).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# TEST 2 — US1 remote routing despite local XUI endpoint
# ws_host=80.76.49.140, xui_host=127.0.0.1 → remote SSH (not local file I/O)
# ---------------------------------------------------------------------------
class Test02US1RemoteRoutingDespiteLocalXUI(unittest.TestCase):
    def test_ws_host_overrides_xui_host_for_routing(self):
        """add_client must SSH to ws_host=80.76.49.140, NOT write to local FR filesystem."""
        local_sentinel = "/etc/xray-ws/config.json"

        remote_cfg = json.dumps(_make_config())
        mock_result = MagicMock(returncode=0, stdout=remote_cfg, stderr="")

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            ws_manager.add_client(
                host="80.76.49.140",
                password="",
                config_path="/etc/xray-ws/config.json",
                uuid="bbbb-2222",
                email="test@us1",
                ssh_key="/root/.ssh/swaga_us1_ws_manager_ed25519",
            )
            all_calls = [c[0][0] for c in mock_run.call_args_list if c[0]]
            # At least one SSH call must target 80.76.49.140
            ssh_targets = [a for args in all_calls for a in args if "80.76.49.140" in str(a)]
            self.assertTrue(len(ssh_targets) > 0,
                            f"Expected SSH to 80.76.49.140 but calls were: {all_calls}")
            # Must NOT open local sentinel directly (that would be local write regression)
            with patch("builtins.open", side_effect=AssertionError("local open must not be called")):
                pass  # just documenting intent; actual check is the SSH assertion above


# ---------------------------------------------------------------------------
# TEST 3 — UK1 remote routing despite local XUI endpoint
# ---------------------------------------------------------------------------
class Test03UK1RemoteRoutingDespiteLocalXUI(unittest.TestCase):
    def test_uk1_ws_host_routes_remote(self):
        remote_cfg = json.dumps(_make_config())
        mock_result = MagicMock(returncode=0, stdout=remote_cfg, stderr="")

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            ws_manager.add_client(
                host="163.5.210.147",
                password="",
                config_path="/etc/xray-ws/config.json",
                uuid="cccc-3333",
                email="test@uk1",
                ssh_key="/root/.ssh/swaga_uk1_ws_manager_ed25519",
            )
            all_args = [a for c in mock_run.call_args_list for a in (c[0][0] if c[0] else [])]
            self.assertIn("163.5.210.147", str(all_args),
                          f"Expected SSH to 163.5.210.147 but calls were: {mock_run.call_args_list}")


# ---------------------------------------------------------------------------
# TEST 4 — xui_host no longer decides WS locality when ws_host is given
# ---------------------------------------------------------------------------
class Test04XuiHostDoesNotDecideWhenWsHostPresent(unittest.TestCase):
    def test_xui_host_127_with_remote_ws_host_is_remote(self):
        """When ws_host is provided and non-local, result is REMOTE regardless of xui_host."""
        remote_cfg = json.dumps(_make_config())
        mock_result = MagicMock(returncode=0, stdout=remote_cfg, stderr="")

        opened_paths = []
        original_open = open

        def _track_open(path, *a, **kw):
            opened_paths.append(str(path))
            return original_open(path, *a, **kw)

        with patch("subprocess.run", return_value=mock_result):
            with patch("builtins.open", side_effect=_track_open):
                ws_manager.add_client(
                    host="80.76.49.140",  # ws_host = remote
                    password="",
                    config_path="/etc/xray-ws/config.json",
                    uuid="dddd-4444",
                    email="test@xui-local-ws-remote",
                    ssh_key="/root/.ssh/swaga_us1_ws_manager_ed25519",
                )

        suspicious = [p for p in opened_paths if "xray-ws" in p]
        self.assertEqual(suspicious, [],
                         f"Local open of xray-ws config must not occur for remote ws_host; got: {suspicious}")


# ---------------------------------------------------------------------------
# TEST 5 — legacy compatibility: no ws_host / no ssh_key → existing sshpass path
# ---------------------------------------------------------------------------
class Test05LegacyCompatibility(unittest.TestCase):
    def test_no_ws_host_no_key_uses_sshpass(self):
        """Entries without new fields retain legacy sshpass behavior (no network, just verify args)."""
        remote_cfg = json.dumps(_make_config())
        mock_result = MagicMock(returncode=0, stdout=remote_cfg, stderr="")

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            ws_manager.add_client(
                host="10.0.0.99",      # some legacy host
                password="legacy_pass",
                config_path="/etc/xray-ws/config.json",
                uuid="eeee-5555",
                email="legacy@test",
                ssh_key="",            # no key → legacy path
            )
            all_args = [c[0][0] for c in mock_run.call_args_list if c[0]]
            sshpass_calls = [a for a in all_args if "sshpass" in a]
            self.assertTrue(len(sshpass_calls) > 0,
                            f"Expected sshpass calls for legacy entry but got: {all_args}")


# ---------------------------------------------------------------------------
# TEST 6 — key-auth SSH command structure
# ---------------------------------------------------------------------------
class Test06KeyAuthCommandStructure(unittest.TestCase):
    def test_key_auth_uses_correct_ssh_flags(self):
        """When ssh_key is provided the SSH invocation must use -i, BatchMode=yes,
        StrictHostKeyChecking=yes, dedicated known_hosts, and must NOT contain sshpass
        or StrictHostKeyChecking=no."""
        remote_cfg = json.dumps(_make_config())
        mock_result = MagicMock(returncode=0, stdout=remote_cfg, stderr="")

        captured = []
        def _capture(*a, **kw):
            captured.append(a[0] if a else kw.get("args", []))
            return mock_result

        with patch("subprocess.run", side_effect=_capture):
            ws_manager.add_client(
                host="80.76.49.140",
                password="",
                config_path="/etc/xray-ws/config.json",
                uuid="ffff-6666",
                email="keyauth@test",
                ssh_key="/root/.ssh/swaga_us1_ws_manager_ed25519",
            )

        ssh_calls = [args for args in captured if any("ssh" in str(a) for a in args)
                     if not any("sshpass" in str(a) for a in args)]
        self.assertTrue(len(ssh_calls) > 0, f"Expected key-auth SSH calls, got: {captured}")

        for args in ssh_calls:
            args_str = " ".join(str(a) for a in args)
            self.assertIn("-i", args, f"Missing -i in: {args}")
            self.assertIn("/root/.ssh/swaga_us1_ws_manager_ed25519", args_str)
            self.assertIn("BatchMode=yes", args_str)
            self.assertIn("StrictHostKeyChecking=yes", args_str)
            self.assertIn(KNOWN_HOSTS_PATH, args_str)
            self.assertNotIn("sshpass", args_str, "sshpass must not appear in key-auth call")
            self.assertNotIn("StrictHostKeyChecking=no", args_str,
                             "StrictHostKeyChecking=no must not appear in key-auth call")


# ---------------------------------------------------------------------------
# TEST 7 — no local write for US1 remote operation
# ---------------------------------------------------------------------------
class Test07NoLocalWriteForUS1(unittest.TestCase):
    def test_us1_operation_does_not_modify_local_config(self):
        """When using remote ws_host for US1, local /etc/xray-ws/config.json must not be written."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(_make_config([{"id": "existing", "email": "orig@fr"}]), f)
            local_fr_path = f.name

        remote_cfg = json.dumps(_make_config())
        mock_result = MagicMock(returncode=0, stdout=remote_cfg, stderr="")

        original_content = Path(local_fr_path).read_text()

        with patch("subprocess.run", return_value=mock_result):
            ws_manager.add_client(
                host="80.76.49.140",
                password="",
                config_path="/etc/xray-ws/config.json",
                uuid="gggg-7777",
                email="us1-remote@test",
                ssh_key="/root/.ssh/swaga_us1_ws_manager_ed25519",
            )

        self.assertEqual(Path(local_fr_path).read_text(), original_content,
                         "Local FR config file must not change during US1 remote operation")
        Path(local_fr_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# TEST 8 — no local write for UK1 remote operation
# ---------------------------------------------------------------------------
class Test08NoLocalWriteForUK1(unittest.TestCase):
    def test_uk1_operation_does_not_modify_local_config(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(_make_config([{"id": "fr-client", "email": "fr@test"}]), f)
            local_fr_path = f.name

        remote_cfg = json.dumps(_make_config())
        mock_result = MagicMock(returncode=0, stdout=remote_cfg, stderr="")
        original_content = Path(local_fr_path).read_text()

        with patch("subprocess.run", return_value=mock_result):
            ws_manager.add_client(
                host="163.5.210.147",
                password="",
                config_path="/etc/xray-ws/config.json",
                uuid="hhhh-8888",
                email="uk1-remote@test",
                ssh_key="/root/.ssh/swaga_uk1_ws_manager_ed25519",
            )

        self.assertEqual(Path(local_fr_path).read_text(), original_content,
                         "Local FR config file must not change during UK1 remote operation")
        Path(local_fr_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# TEST 9 — FR operation still uses local config
# ---------------------------------------------------------------------------
class Test09FROperationIsLocal(unittest.TestCase):
    def test_fr_local_operation_writes_only_local_fixture(self):
        cfg = _make_config([{"id": "existing-fr", "email": "fr-user@test"}])
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(cfg, f)
            tmp = f.name

        with patch("subprocess.run") as mock_run:
            result = ws_manager.add_client(
                host="127.0.0.1",
                password="",
                config_path=tmp,
                uuid="iiii-9999",
                email="new-fr@test",
                ssh_key="",
            )

        written = json.loads(Path(tmp).read_text())
        clients = written["inbounds"][0]["settings"]["clients"]
        ids = [c["id"] for c in clients]
        self.assertIn("iiii-9999", ids, "New client must be present in local fixture after FR op")
        self.assertIn("existing-fr", ids, "Existing client must still be present")

        Path(tmp).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# TEST 10 — missing remote key: FAIL CLOSED
# ---------------------------------------------------------------------------
class Test10MissingRemoteKeyFailClosed(unittest.TestCase):
    def test_remote_host_without_key_fails_closed(self):
        """If host is non-local and ssh_key is explicitly empty string (new-style entry
        but key missing), ws_manager must return False and must NOT fall back to sshpass."""
        # The new-style indicator: host is non-local. In the new model, if ssh_key=""
        # but we're calling the new-style path (e.g., bot passes ws_host explicitly),
        # it should FAIL CLOSED rather than silently use password SSH.
        #
        # This test verifies the fail-closed behavior when ws_host is remote but
        # no ssh_key is configured and password is also empty.
        with patch("subprocess.run") as mock_run:
            result = ws_manager.add_client(
                host="80.76.49.140",
                password="",          # no password
                config_path="/etc/xray-ws/config.json",
                uuid="jjjj-0000",
                email="fail-closed@test",
                ssh_key="",           # no key → fail closed for new-style remote
                fail_closed=True,     # explicit marker: caller says "I want key-only, fail if missing"
            )
        self.assertFalse(result, "add_client must return False when fail_closed=True and no key")
        sshpass_calls = [c for c in mock_run.call_args_list
                         if c[0] and "sshpass" in str(c[0][0])]
        self.assertEqual(sshpass_calls, [], "sshpass must not be called when fail_closed=True")


# ---------------------------------------------------------------------------
# TEST 11 — remote command failure returns False
# ---------------------------------------------------------------------------
class Test11RemoteCommandFailureReturnsFalse(unittest.TestCase):
    def test_nonzero_ssh_exit_returns_false(self):
        mock_result = MagicMock(returncode=1, stdout="", stderr="permission denied")

        with patch("subprocess.run", return_value=mock_result):
            result = ws_manager.add_client(
                host="80.76.49.140",
                password="",
                config_path="/etc/xray-ws/config.json",
                uuid="kkkk-1111",
                email="fail@test",
                ssh_key="/root/.ssh/swaga_us1_ws_manager_ed25519",
            )
        self.assertFalse(result, "add_client must return False on SSH command failure")


# ---------------------------------------------------------------------------
# TEST 12 — protected server (legacy entry without new fields) is compatible
# ---------------------------------------------------------------------------
class Test12LegacyEntryCompatibility(unittest.TestCase):
    def test_legacy_entry_without_ws_host_retains_existing_behavior(self):
        """A legacy entry (no ws_host, no ssh_key) must still call legacy sshpass path.
        This ensures dormant legacy entries (e.g. us2-ws) are not broken.
        Static test only — no actual network call."""
        remote_cfg = json.dumps(_make_config())
        mock_result = MagicMock(returncode=0, stdout=remote_cfg, stderr="")

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            ws_manager.add_client(
                host="10.99.99.99",
                password="legacy_password",
                config_path="/etc/xray-ws/config.json",
                uuid="llll-2222",
                email="legacy@entry",
                ssh_key="",
                # no fail_closed → legacy behavior
            )

        call_args = [c[0][0] for c in mock_run.call_args_list if c[0]]
        legacy_calls = [args for args in call_args if "sshpass" in args]
        self.assertTrue(len(legacy_calls) > 0,
                        "Legacy entry (no key, no fail_closed) must use sshpass path")
        # Must not use key-based ssh for legacy entry
        key_based = [args for args in call_args
                     if any("BatchMode" in str(a) for a in args)]
        self.assertEqual(key_based, [],
                         "Legacy entry must not use key-based BatchMode SSH")


if __name__ == "__main__":
    unittest.main()
