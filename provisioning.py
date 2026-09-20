"""
Central profile provisioning resolver for SWAGA VPN (H2).

Single source of truth for: email alias scheme, per-server sync, confirmed-profile resolution.
Both bot.py (payment/trial/renewal) and sub_app.py (/sub, /connect) import from here.
"""
import logging
from dataclasses import dataclass, field
from typing import List

from servers import PROTECTED_SERVER_IDS

logger = logging.getLogger(__name__)

# ── Email alias scheme ────────────────────────────────────────────────────────
# Inbound-specific suffixes for panels that share a global email namespace.
# us1-xhttp lives on inbound 3 of US1 — suffix "_i3" disambiguates.

PANEL_EMAIL_SUFFIXES: dict = {
    "us1-xhttp": "_i3",
}


def panel_email(server_id: str, base_email: str) -> str:
    """Derive the panel-side email for a given server and logical/base email."""
    suffix = PANEL_EMAIL_SUFFIXES.get(server_id, "")
    return f"{base_email}{suffix}" if suffix and base_email else base_email


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class ProvisioningResult:
    available_servers: List = field(default_factory=list)
    failed_servers: List = field(default_factory=list)


# ── Per-server idempotent sync ────────────────────────────────────────────────

def server_sync_client(
    server,
    uuid: str,
    email: str,
    sub_id: str = "",
    expiry_ms: int = 0,
    flow: str = "",
) -> bool:
    """
    Idempotent sync of one client to one server.

    Protected servers: refused before any I/O.
    WS transport: ws_manager (already idempotent).
    Non-standard panels (uk1 fork): ensure_client_uk1.
    Standard panels: ensure_client with per-server email alias.
    """
    if getattr(server, "id", None) in PROTECTED_SERVER_IDS:
        logger.warning(
            "server_sync_client: refused contact with protected server %s",
            getattr(server, "id", "?"),
        )
        return False

    if getattr(server, "transport", "") == "ws":
        import ws_manager
        ws_host = getattr(server, "ws_host", "") or server.xui_host
        return ws_manager.add_client(
            ws_host,
            getattr(server, "ws_ssh_password", ""),
            getattr(server, "ws_config_path", ""),
            uuid, email,
            ssh_key=getattr(server, "ws_ssh_key", ""),
        )

    from xui_api import XUIAPI, EnsureResult
    srv_xui = XUIAPI()
    protocol = "https" if getattr(server, "xui_ssl", True) else "http"
    srv_xui.base_url = f"{protocol}://{server.xui_host}:{server.xui_port}{server.xui_web_path}"
    if not srv_xui.login(server.xui_username, server.xui_password):
        logger.warning("server_sync_client: auth failed on %s", server.name)
        return False

    if not getattr(server, "xui_standard", True):
        result = srv_xui.ensure_client_uk1(
            server.inbound_id, uuid, email,
            sub_id=sub_id, expiry_time=expiry_ms, flow=flow,
        )
        return result in (EnsureResult.CREATED, EnsureResult.UPDATED, EnsureResult.ALREADY_OK)

    derived = panel_email(server.id, email)
    extra = [email] if derived != email else None
    result = srv_xui.ensure_client(
        server.inbound_id, uuid, derived,
        sub_id=sub_id, expiry_time=expiry_ms, flow=flow,
        extra_conflict_emails=extra,
    )
    return result in (EnsureResult.CREATED, EnsureResult.UPDATED, EnsureResult.ALREADY_OK)


# ── Central resolver ──────────────────────────────────────────────────────────

def resolve_available_profiles(
    candidate_servers: list,
    uuid: str,
    email: str,
    sub_id: str,
    expiry_ms: int,
) -> ProvisioningResult:
    """
    Ensure the client exists on each candidate server and return confirmed/failed sets.

    - Protected servers (us2, us2-ws) excluded BEFORE any network call.
    - One server failure does not affect others (per-server exception isolation).
    - Returns only confirmed (available) servers for caller to use in user-facing output.
    - Idempotent: calling repeatedly is safe (read-first semantics in underlying adapters).
    """
    available = []
    failed = []

    for server in candidate_servers:
        sid = getattr(server, "id", None)
        if sid in PROTECTED_SERVER_IDS:
            logger.warning(
                "resolve_available_profiles: protected server %s excluded (no I/O)", sid
            )
            continue
        try:
            ok = server_sync_client(
                server, uuid, email,
                sub_id=sub_id,
                expiry_ms=expiry_ms,
                flow=getattr(server, "flow", ""),
            )
            if ok:
                available.append(server)
            else:
                logger.warning(
                    "resolve_available_profiles: sync failed for %s (uuid=%.8s)",
                    sid, uuid,
                )
                failed.append(server)
        except Exception as exc:
            logger.warning(
                "resolve_available_profiles: exception on %s: %s", sid, exc
            )
            failed.append(server)

    return ProvisioningResult(available_servers=available, failed_servers=failed)
