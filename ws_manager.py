"""
Client management for standalone xray-ws servers.
Supports SSH (remote servers) and direct file I/O (localhost / fr1-ws).

Key-auth path: uses dedicated ed25519 automation keys, StrictHostKeyChecking=yes,
dedicated known_hosts, and BatchMode=yes — no sshpass, no StrictHostKeyChecking=no.
Legacy password path: retained for backward compatibility with dormant entries.
"""

import base64
import json
import logging
import subprocess

logger = logging.getLogger(__name__)

_LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")

# Dedicated known_hosts for ws_manager automation keys.
KNOWN_HOSTS_PATH = "/root/.ssh/swaga_ws_manager_known_hosts"


def _is_local(host: str) -> bool:
    return host in _LOCAL_HOSTS


def _ssh(host: str, password: str, command: str, timeout: int = 30) -> subprocess.CompletedProcess:
    """Legacy password-based SSH (sshpass). Retained for backward compat."""
    return subprocess.run(
        ["sshpass", "-p", password, "ssh",
         "-o", "StrictHostKeyChecking=no",
         "-o", "ConnectTimeout=10",
         f"root@{host}", command],
        capture_output=True, text=True, timeout=timeout,
    )


def _ssh_key(
    host: str,
    key_path: str,
    command: str,
    input_data: str | None = None,
    timeout: int = 30,
) -> subprocess.CompletedProcess:
    """Key-based SSH: ed25519 identity, StrictHostKeyChecking=yes, BatchMode=yes.
    Passes input_data as stdin when provided (used for base64-pipe write)."""
    return subprocess.run(
        ["ssh",
         "-i", key_path,
         "-o", f"UserKnownHostsFile={KNOWN_HOSTS_PATH}",
         "-o", "StrictHostKeyChecking=yes",
         "-o", "BatchMode=yes",
         "-o", "ConnectTimeout=10",
         f"root@{host}", command],
        input=input_data,
        capture_output=True, text=True, timeout=timeout,
    )


def _read_config(
    host: str, password: str, path: str, ssh_key: str = "",
) -> dict | None:
    if _is_local(host):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error("ws_manager: failed to read local %s: %s", path, e)
            return None
    if ssh_key:
        result = _ssh_key(host, ssh_key, f"cat {path}")
    else:
        result = _ssh(host, password, f"cat {path}")
    if result.returncode != 0:
        logger.error("ws_manager: failed to read %s on %s: %s", path, host, result.stderr)
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        logger.error("ws_manager: invalid JSON in %s on %s: %s", path, host, e)
        return None


def _write_config(
    host: str, password: str, path: str, config: dict, ssh_key: str = "",
) -> bool:
    if _is_local(host):
        try:
            with open(path, "w") as f:
                json.dump(config, f, indent=2)
            return True
        except Exception as e:
            logger.error("ws_manager: failed to write local %s: %s", path, e)
            return False
    config_b64 = base64.b64encode(json.dumps(config, indent=2).encode()).decode()
    if ssh_key:
        # Key-auth write: pass base64 via stdin → wrapper: base64 -d > {path}
        result = _ssh_key(host, ssh_key, f"base64 -d > {path}", input_data=config_b64)
    else:
        # Legacy: inline Python (preserved for backward compat)
        cmd = (
            f"python3 -c \""
            f"import base64; open('{path}', 'w').write(base64.b64decode('{config_b64}').decode())"
            f"\""
        )
        result = _ssh(host, password, cmd)
    if result.returncode != 0:
        logger.error("ws_manager: failed to write %s on %s: %s", path, host, result.stderr)
        return False
    return True


def _reload(
    host: str, password: str, service: str = "xray-ws", ssh_key: str = "",
) -> bool:
    if _is_local(host):
        result = subprocess.run(
            ["systemctl", "restart", service],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            logger.error("ws_manager: failed to restart %s locally: %s", service, result.stderr)
            return False
        return True
    if ssh_key:
        result = _ssh_key(host, ssh_key, f"systemctl restart {service}")
    else:
        result = _ssh(host, password, f"systemctl restart {service}")
    if result.returncode != 0:
        logger.error("ws_manager: failed to restart %s on %s: %s", service, host, result.stderr)
        return False
    return True


def add_client(
    host: str,
    password: str,
    config_path: str,
    uuid: str,
    email: str,
    ssh_key: str = "",
    fail_closed: bool = False,
) -> bool:
    """Add a VLESS client to xray-ws config.json and reload the service.

    Routing:
    - local host (127.0.0.1/localhost/::1) → direct file I/O on this machine
    - ssh_key provided → key-auth SSH (strict host-key checking, no sshpass)
    - fail_closed=True, remote host, no key → return False (no password fallback)
    - otherwise → legacy sshpass path (backward compat for dormant entries)
    """
    if not _is_local(host) and not ssh_key and fail_closed:
        logger.error(
            "ws_manager: add_client fail_closed=True but no ssh_key for remote host %s", host
        )
        return False

    config = _read_config(host, password, config_path, ssh_key=ssh_key)
    if config is None:
        return False

    try:
        clients = config["inbounds"][0]["settings"]["clients"]
    except (KeyError, IndexError) as e:
        logger.error("ws_manager: unexpected config structure on %s: %s", host, e)
        return False

    if any(c.get("id") == uuid for c in clients):
        logger.info("ws_manager: client %s already exists on %s", email, host)
        return True

    clients.append({
        "id": uuid,
        "email": email,
        "flow": "",
        "enable": True,
        "limitIp": 3,
        "totalGB": 0,
    })
    config["inbounds"][0]["settings"]["clients"] = clients

    if not _write_config(host, password, config_path, config, ssh_key=ssh_key):
        return False
    if not _reload(host, password, ssh_key=ssh_key):
        return False

    logger.info("ws_manager: client added — %s (%s) on %s", email, uuid[:8], host)
    return True


def delete_client(
    host: str,
    password: str,
    config_path: str,
    uuid: str,
    ssh_key: str = "",
    fail_closed: bool = False,
) -> bool:
    """Remove a VLESS client from xray-ws config.json and reload the service."""
    if not _is_local(host) and not ssh_key and fail_closed:
        logger.error(
            "ws_manager: delete_client fail_closed=True but no ssh_key for remote host %s", host
        )
        return False

    config = _read_config(host, password, config_path, ssh_key=ssh_key)
    if config is None:
        return False

    try:
        clients = config["inbounds"][0]["settings"]["clients"]
    except (KeyError, IndexError) as e:
        logger.error("ws_manager: unexpected config structure on %s: %s", host, e)
        return False

    new_clients = [c for c in clients if c.get("id") != uuid]
    if len(new_clients) == len(clients):
        logger.info("ws_manager: client %s not found on %s, skip", uuid[:8], host)
        return True

    config["inbounds"][0]["settings"]["clients"] = new_clients

    if not _write_config(host, password, config_path, config, ssh_key=ssh_key):
        return False
    if not _reload(host, password, ssh_key=ssh_key):
        return False

    logger.info("ws_manager: client deleted — %s from %s", uuid[:8], host)
    return True
