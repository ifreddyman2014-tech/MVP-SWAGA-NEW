"""
Client management for standalone xray-ws servers.
Supports SSH (remote servers) and direct file I/O (localhost / fr1-ws).
"""

import base64
import json
import logging
import subprocess

logger = logging.getLogger(__name__)

_LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")


def _is_local(host: str) -> bool:
    return host in _LOCAL_HOSTS


def _ssh(host: str, password: str, command: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["sshpass", "-p", password, "ssh",
         "-o", "StrictHostKeyChecking=no",
         "-o", "ConnectTimeout=10",
         f"root@{host}", command],
        capture_output=True, text=True, timeout=timeout,
    )


def _read_config(host: str, password: str, path: str) -> dict | None:
    if _is_local(host):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error("ws_manager: failed to read local %s: %s", path, e)
            return None
    result = _ssh(host, password, f"cat {path}")
    if result.returncode != 0:
        logger.error("ws_manager: failed to read %s on %s: %s", path, host, result.stderr)
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        logger.error("ws_manager: invalid JSON in %s on %s: %s", path, host, e)
        return None


def _write_config(host: str, password: str, path: str, config: dict) -> bool:
    if _is_local(host):
        try:
            with open(path, "w") as f:
                json.dump(config, f, indent=2)
            return True
        except Exception as e:
            logger.error("ws_manager: failed to write local %s: %s", path, e)
            return False
    config_b64 = base64.b64encode(json.dumps(config, indent=2).encode()).decode()
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


def _reload(host: str, password: str, service: str = "xray-ws") -> bool:
    if _is_local(host):
        result = subprocess.run(
            ["systemctl", "restart", service],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            logger.error("ws_manager: failed to restart %s locally: %s", service, result.stderr)
            return False
        return True
    result = _ssh(host, password, f"systemctl restart {service}")
    if result.returncode != 0:
        logger.error("ws_manager: failed to restart %s on %s: %s", service, host, result.stderr)
        return False
    return True


def add_client(host: str, password: str, config_path: str, uuid: str, email: str) -> bool:
    """Add a VLESS client to xray-ws config.json via SSH and reload the service."""
    config = _read_config(host, password, config_path)
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

    if not _write_config(host, password, config_path, config):
        return False
    if not _reload(host, password):
        return False

    logger.info("ws_manager: client added — %s (%s) on %s", email, uuid[:8], host)
    return True


def delete_client(host: str, password: str, config_path: str, uuid: str) -> bool:
    """Remove a VLESS client from xray-ws config.json via SSH and reload the service."""
    config = _read_config(host, password, config_path)
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

    if not _write_config(host, password, config_path, config):
        return False
    if not _reload(host, password):
        return False

    logger.info("ws_manager: client deleted — %s from %s", uuid[:8], host)
    return True
